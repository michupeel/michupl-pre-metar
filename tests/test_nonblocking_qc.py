"""Synthetic concurrent disk work; real-data before/after runs are separate artifacts."""

import asyncio
import json
import sqlite3
import threading
import time
from datetime import timedelta

import pytest
from test_continuous import AT, metar

from premetar.continuous.analytical_qc import (
    AnalyticalQC,
    calculate_quality,
    migrate,
    publish_quality,
)
from premetar.continuous.config import Config
from premetar.continuous.data import schedule, settle
from premetar.model import utc_now
from premetar.performance import Timings, timed_operation
from premetar.pws.models import Sensor, Station
from premetar.pws.providers import reading
from premetar.pws.repository import parameter_available
from premetar.pws.service import settings
from premetar.timing_summary import summarize_timings

pytest_plugins = ["test_continuous"]


def test_reviewed_percentiles_validation_and_no_mutation():
    records = [dict(operation_name="a", queue_wait_ms=i, success=True) for i in range(1, 101)]
    records += [
        dict(operation_name="a", queue_wait_ms=v)
        for v in [True, None, -1, float("nan"), float("inf")]
    ]
    records.append(dict(operation_name="b", queue_wait_ms=7, success=False))
    result = summarize_timings(records)
    assert result["a"]["queue_wait_ms_p95"] == 95
    assert result["a"]["queue_wait_ms_p99"] == 99
    assert result["a"]["failed_count"] == 0
    assert result["b"]["failed_count"] == 1
    assert result["b"]["queue_wait_ms_p99"] == 7
    assert len(records) == 106 and summarize_timings([]) == {}


def test_timing_errors_have_no_exception_text():
    timings = Timings()
    with pytest.raises(ValueError), timed_operation("TEST", timings):
        raise ValueError("do not log secret text")
    record = timings.samples["TEST"][0]
    assert record["error"] == "ValueError" and not record["success"]
    assert "secret" not in json.dumps(record)


async def test_long_analysis_does_not_occupy_writer_or_event_loop(store, monkeypatch):
    await store._call(migrate, store.connection)
    started = threading.Event()
    release = threading.Event()

    def long_qc(database, airport, config, cancel, recorder):
        started.set()
        while not release.wait(0.01):
            if cancel.is_set():
                raise InterruptedError("cancelled")
        return dict(
            id="synthetic",
            airport=airport,
            input_cutoff_time=AT.isoformat(),
            qualities=[],
            calibrations=[],
        )

    monkeypatch.setattr("premetar.continuous.analytical_qc.calculate_quality", long_qc)
    monkeypatch.setattr("premetar.continuous.data.utc_now", lambda: AT)
    await metar(store, AT - timedelta(minutes=25), AT - timedelta(minutes=23), 17)
    qc = AnalyticalQC(store, Config(airports=["EDDM"]))
    task = asyncio.create_task(qc.once("EDDM"))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        start = time.monotonic()
        await metar(store, AT - timedelta(minutes=55), AT - timedelta(minutes=53), 16)
        await store._call(
            schedule,
            store.connection,
            Config(airports=["EDDM"], checkpoints=[300]),
            store.run_id,
            AT,
        )
        await store._call(settle, store.connection, AT)
        await store.heartbeat()
        assert time.monotonic() - start < 1
        assert not task.done()
        # Actual source measurement processing proceeds while analytics is held.
        airport = settings().airports[0]
        station = Station(
            provider="opensensemap",
            provider_station_id="synthetic",
            exposure="outdoor",
            latitude=airport.latitude,
            longitude=airport.longitude,
            sensors=[Sensor(provider_sensor_id="t", unit="C")],
        )
        packet = await store.capture(
            dict(
                source="pws_opensensemap",
                request_url="https://example.test",
                http_status=200,
                headers={},
                received_at=AT.isoformat(),
                request_start=AT.isoformat(),
                request_end=AT.isoformat(),
                monotonic_ns=1,
                request_start_monotonic_ns=0,
            ),
            b"synthetic",
        )
        await store._call(store.discover, airport, station, packet)
        identity = await store._call(store.ingest, station, reading("t", 18, "C", AT), packet)
        assert identity
    finally:
        qc.cancel.set()
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        qc.executor.shutdown(wait=True)
    assert (
        await store._call(lambda: store.connection.execute("PRAGMA integrity_check").fetchone()[0])
        == "ok"
    )


async def test_publication_commit_proof_idempotence_and_atomic_failure(store):
    await store._call(migrate, store.connection)
    batch = dict(
        id="batch",
        airport="EDDM",
        input_cutoff_time=(utc_now() - timedelta(hours=1)).isoformat(),
        qualities=[],
        calibrations=[],
    )
    await store._call(publish_quality, store.connection, store.run_id, batch)
    await store._call(publish_quality, store.connection, store.run_id, batch)

    def verify():
        assert not parameter_available(
            store.connection, {"qc_batch_id": "batch"}, utc_now() - timedelta(hours=1)
        )
        assert parameter_available(store.connection, {"qc_batch_id": "batch"}, utc_now())
        assert not parameter_available(store.connection, {"qc_batch_id": "unfinished"}, utc_now())
        assert (
            store.connection.execute("SELECT count(*) FROM analytical_qc_batches").fetchone()[0]
            == 1
        )
        with pytest.raises(sqlite3.IntegrityError), store.connection:
            store.connection.execute("UPDATE analytical_qc_batches SET published_at='changed'")
        broken = {
            **batch,
            "id": "broken",
            "qualities": [
                dict(
                    station_id="nonexistent",
                    airport_icao="EDDM",
                    algorithm_version="test",
                    data_json="{}",
                )
            ],
        }
        with pytest.raises(sqlite3.IntegrityError):
            publish_quality(store.connection, store.run_id, broken)
        assert not store.connection.execute(
            "SELECT 1 FROM analytical_qc_batches WHERE id='broken'"
        ).fetchone()
        assert not store.connection.in_transaction

    await store._call(verify)


async def test_busy_publication_fails_fast_and_restores_timeout(store):
    await store._call(migrate, store.connection)
    external = sqlite3.connect(store.database)
    external.execute("BEGIN IMMEDIATE")
    try:
        start = time.monotonic()
        with pytest.raises(sqlite3.OperationalError):
            await store._call(
                publish_quality,
                store.connection,
                store.run_id,
                dict(
                    id="busy",
                    airport="EDDM",
                    input_cutoff_time=AT.isoformat(),
                    qualities=[],
                    calibrations=[],
                ),
            )
        assert time.monotonic() - start < 0.5
    finally:
        external.rollback()
        external.close()
    assert (
        await store._call(lambda: store.connection.execute("PRAGMA busy_timeout").fetchone()[0])
        == 30000
    )


async def test_snapshot_cancellation_and_connection_ownership(store):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(InterruptedError):
        await asyncio.to_thread(calculate_quality, store.database, "EDDM", Config(), cancel)
    await store.heartbeat()
    assert (
        await store._call(lambda: store.connection.execute("PRAGMA foreign_key_check").fetchall())
        == []
    )


async def test_bounded_queue_finishes_cancelled_inflight_transaction(store):
    await asyncio.gather(
        *(
            store._call(lambda: store.connection.execute("SELECT 1").fetchone()[0])
            for _ in range(150)
        )
    )
    assert store.timings.snapshot()["DATABASE_OPERATION"]["count"] >= 150
    task = asyncio.create_task(store._call(time.sleep, 0.05))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await store.heartbeat()


async def test_qc_shutdown_is_cooperative_without_publishing(store, monkeypatch):
    started = threading.Event()

    def held(database, airport, config, cancel, recorder):
        started.set()
        while not cancel.wait(0.01):
            pass
        raise InterruptedError("stop requested")

    async def immediate(stop, seconds):
        if started.is_set():
            await stop.wait()

    monkeypatch.setattr("premetar.continuous.analytical_qc.calculate_quality", held)
    monkeypatch.setattr("premetar.continuous.analytical_qc.wait_or_stop", immediate)
    stop = asyncio.Event()
    qc = AnalyticalQC(store, Config(airports=["EDDM"]))
    task = asyncio.create_task(qc.run(stop))
    assert await asyncio.to_thread(started.wait, 1)
    await store.heartbeat()
    stop.set()
    await asyncio.wait_for(task, 1)
    assert qc.cancel.is_set()


def test_optimized_peer_windows_equal_original_full_scan():
    from test_pws_quality import CONFIG, NOW, row, station

    from premetar.pws.models import utc
    from premetar.pws.quality import (
        effective_time,
        eligible,
        historical_peer_differences,
        peer_comparison,
    )

    s = station("local", 52, 4)
    history = [
        row(18 + i / 10, event=NOW - timedelta(minutes=i), receive=NOW - timedelta(minutes=i))
        for i in range(10)
    ]
    peers = [
        (
            station(str(n), 52 + 0.01 * n, 4),
            [
                row(
                    18 + n / 10,
                    event=NOW - timedelta(minutes=i),
                    receive=NOW - timedelta(minutes=i, seconds=-30),
                )
                for i in range(20)
            ],
        )
        for n in range(1, 5)
    ]
    expected = []
    for r in sorted(history, key=lambda r: r["first_receive_time"]):
        at = utc(__import__("datetime").datetime.fromisoformat(r["first_receive_time"]))
        available = []
        for other, data in peers:
            candidates = [p for p in data if eligible(p, at, CONFIG)]
            if candidates:
                available.append((other, max(candidates, key=lambda p: str(effective_time(p)))))
        c = peer_comparison(s, r["temperature_c"], at, available, CONFIG)
        if c["difference_c"] is not None:
            expected.append((effective_time(r), c["difference_c"]))
    assert historical_peer_differences(s, history, peers, CONFIG) == expected


async def test_candidate_quality_lookup_uses_asof_index(store):
    await store._call(migrate, store.connection)

    def verify():
        plan = store.connection.execute(
            "EXPLAIN QUERY PLAN SELECT data_json FROM pws_quality_results WHERE station_id=? AND airport_icao=? AND created_at<=? ORDER BY created_at DESC,id DESC LIMIT 1",
            ("s", "EPWA", AT.isoformat()),
        ).fetchall()
        assert any("pws_quality_asof" in row[-1] for row in plan)

    await store._call(verify)
