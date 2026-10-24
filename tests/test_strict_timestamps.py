"""Synthetic regressions; local Qwen proposed the parser case matrix, reviewed here."""

import json
import sqlite3
from datetime import UTC, date, datetime, timedelta

import pytest
from test_continuous import AT, TARGET, metar

from premetar.clock_audit import summarize
from premetar.continuous.reference_gate import ReferenceGate
from premetar.pws.daily import make_report
from premetar.pws.daily_time import bucket_start, local_day_bounds
from premetar.pws.integrity import backfill, prediction_issues
from premetar.pws.models import Airport, Reading, Sensor, Station
from premetar.pws.timestamps import assess_time

pytest_plugins = ["test_continuous"]


def base_row():
    return dict(
        station_id="opensensemap:test",
        provider="opensensemap",
        provider_sensor_id="t",
        temperature_c=18.4,
        raw_unit="C",
        observation_time="2026-10-24T12:00:00Z",
        first_receive_time="2026-10-24T12:00:30Z",
        evidence_class="REALTIME_CAPTURED",
        timestamp_provenance="SENSOR_MEASUREMENT_TIME",
        timestamp_semantics_verified=True,
    )


@pytest.mark.parametrize(
    "changes,status",
    [
        ({}, "VALID"),
        ({"observation_time": None}, "UNKNOWN_TIMESTAMP_PROVENANCE"),
        ({"observation_time": "not-a-time"}, "INVALID_TIMESTAMP"),
        ({"observation_time": "2026-10-24T12:00:00"}, "INVALID_TIMESTAMP"),
        ({"timestamp_provenance": "PROVIDER_INGEST_TIME"}, "UNKNOWN_TIMESTAMP_PROVENANCE"),
        ({"timestamp_semantics_verified": False}, "UNKNOWN_TIMESTAMP_PROVENANCE"),
        ({"provider": "sensor_community"}, "UNKNOWN_TIMESTAMP_PROVENANCE"),
        ({"first_receive_time": None}, "QUARANTINED"),
        ({"first_receive_time": "invalid"}, "INVALID_TIMESTAMP"),
        ({"observation_time": "2026-10-24T11:55:29Z"}, "STALE"),
        ({"observation_time": "2026-10-24T12:00:31Z"}, "INVALID_TIMESTAMP"),
        ({"temperature_c": float("nan")}, "QUARANTINED"),
        ({"temperature_c": 999}, "QUARANTINED"),
        ({"raw_unit": "unknown"}, "QUARANTINED"),
    ],
)
def test_strict_case_matrix(changes, status):
    result = assess_time({**base_row(), **changes})
    assert result.status == status
    assert result.eligible == (status == "VALID")


def test_no_later_decision_can_repair_future_at_receipt():
    row = {**base_row(), "observation_time": "2026-10-24T12:00:31Z"}
    assert not assess_time(row, datetime(2026, 10, 24, 12, 1, tzinfo=UTC)).eligible


def test_asof_and_months_old_eham_excluded():
    row = base_row()
    assert not assess_time(row, datetime(2026, 10, 24, 12, tzinfo=UTC)).eligible
    assert not assess_time(row, datetime(2026, 10, 24, 12, 6, tzinfo=UTC)).eligible
    row["observation_time"] = "2026-01-01T12:00:00Z"
    assert assess_time(row).status == "STALE"


@pytest.mark.parametrize(
    "day,hours", [(date(2026, 10, 24), 24), (date(2026, 10, 25), 25), (date(2026, 3, 29), 23)]
)
def test_warsaw_exclusive_day_boundaries(day, hours):
    start, end = local_day_bounds(day, "Europe/Warsaw")
    assert (end - start).total_seconds() == hours * 3600
    if day.day == 24:
        assert start == datetime(2026, 10, 23, 22, tzinfo=UTC)
        assert end == datetime(2026, 10, 24, 22, tzinfo=UTC)


def test_dst_bucket_distinguishes_repeated_hour():
    a = datetime(2026, 10, 25, 0, 32, tzinfo=UTC)
    b = a + timedelta(hours=1)
    assert bucket_start(b, 5, "Europe/Warsaw") - bucket_start(a, 5, "Europe/Warsaw") == timedelta(
        hours=1
    )


def test_gate_is_source_and_airport_scoped():
    gate = ReferenceGate()
    gate.begin("knmi", {"EHAM"}, AT)
    gate.begin("awc", {"EHAM", "EDDM"}, AT)
    gate.end("knmi")
    with pytest.raises(ValueError, match="PENDING_DURABLE_PARSE"):
        gate.check("EHAM")
    gate.check("EPWA")
    gate.end("awc")
    gate.check("EHAM")


async def test_first_receipt_across_providers_and_append_only_exclusions(store):
    # The later provider cannot mask the earlier KNMI receipt; nominal time is future.
    await metar(store, TARGET, AT - timedelta(seconds=1), source="knmi_metar")
    await metar(store, TARGET, AT + timedelta(seconds=30), source="awc")
    prediction = dict(
        id="excluded",
        airport_icao="EDDM",
        created_at=AT.isoformat(),
        decision_time=AT.isoformat(),
        target_time=TARGET.isoformat(),
        input_observation_ids=[],
    )

    def check():
        c = store.connection
        assert ("TARGET_ALREADY_RECEIVED", "") in prediction_issues(c, prediction)
        earlier = {
            **prediction,
            "created_at": (AT - timedelta(seconds=2)).isoformat(),
            "decision_time": (AT - timedelta(seconds=2)).isoformat(),
        }
        assert prediction_issues(c, earlier) == []
        with c:
            c.execute(
                "INSERT INTO pws_predictions VALUES(?,?,?,?,?,?,?)",
                (
                    "excluded",
                    "EDDM",
                    AT.isoformat(),
                    AT.isoformat(),
                    TARGET.isoformat(),
                    "synthetic",
                    json.dumps(prediction),
                ),
            )
        before = c.execute("SELECT data_json FROM pws_predictions").fetchall()
        backfill(c)
        backfill(c)
        assert c.execute("SELECT count(*) FROM prediction_exclusions").fetchone()[0] == 1
        assert c.execute("SELECT data_json FROM pws_predictions").fetchall() == before
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            c.execute("DELETE FROM prediction_exclusions")
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    await store._call(check)


async def test_empty_daily_readonly_snapshot_while_writer_active(store, tmp_path):
    reader = sqlite3.connect(f"file:{store.database.as_posix()}?mode=ro", uri=True)
    try:
        reader.execute("BEGIN")
        result = make_report(reader, "EPWA", date(2026, 10, 24), tmp_path / "report")
        assert result["total_valid_observations"] == 0
        assert result["buckets"] == []
        await metar(store, AT, AT + timedelta(seconds=30))
        assert reader.execute("SELECT count(*) FROM observations").fetchone()[0] == 0
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            reader.execute("DELETE FROM observations")
    finally:
        reader.close()
    assert (tmp_path / "report/EPWA_2026-10-24_observations.csv").is_file()


def test_clock_audit_requires_independent_comparisons():
    def entry(server, offset):
        return dict(
            command=["w32tm", "/stripchart", "/computer:" + server],
            returncode=0,
            stdout="\n".join([f"12:00:00, {offset:+.7f}s"] * 5),
        )

    raw = dict(verified_at=AT.isoformat(), evidence=[entry("a", 1.05)])
    assert summarize(raw)["verification_status"] == "UNKNOWN"
    raw["evidence"].append(entry("b", 1.051))
    assert summarize(raw)["verification_status"] == "FAILED"
    raw["evidence"] = [entry("a", 0.05), entry("b", 0.051)]
    assert summarize(raw)["verification_status"] == "VERIFIED"


async def test_daily_dedup_quantization_and_conservative_physical_votes(store, tmp_path):
    airport = Airport(
        icao="EDDM", name="fixture", latitude=48.35, longitude=11.81, reference="synthetic"
    )
    reading = Reading(
        provider_sensor_id="t",
        observation_time=TARGET - timedelta(minutes=1),
        temperature_c=17.5,
        raw_unit="C",
        timestamp_provenance="SENSOR_MEASUREMENT_TIME",
        timestamp_semantics_verified=True,
    )
    stations = [
        Station(
            provider="opensensemap",
            provider_station_id=f"test{i}",
            latitude=48.35 + i * 0.0001,
            longitude=11.81,
            sensors=[Sensor(provider_sensor_id="t", unit="C")],
        )
        for i in range(2)
    ]
    received = TARGET - timedelta(seconds=30)
    packets = []
    for i in range(2):
        packets.append(
            await store.capture(
                dict(
                    source="pws_opensensemap",
                    request_url="https://example.test",
                    http_status=200,
                    headers={},
                    request_start=received.isoformat(),
                    request_end=received.isoformat(),
                    received_at=received.isoformat(),
                    monotonic_ns=i,
                    request_start_monotonic_ns=i,
                ),
                b"synthetic",
            )
        )
    for station in stations:
        await store._call(store.discover, airport, station, packets[0])
        await store._call(store.ingest, station, reading, packets[0], False)
        await store._call(store.ingest, station, reading, packets[1], False)
    await metar(store, TARGET, TARGET + timedelta(minutes=2), temp=18)

    def inspect():
        c = store.connection
        with c:
            for station in stations:
                c.execute(
                    "INSERT INTO pws_selections VALUES(NULL,?,?,?,?,?)",
                    (station.station_id, "EDDM", AT.isoformat(), 1, "synthetic"),
                )
        result = make_report(
            c, "EDDM", date(2026, 11, 1), tmp_path / "daily", now=TARGET + timedelta(minutes=3)
        )
        assert result["total_valid_observations"] == 2
        assert result["usable_stations"] == 2
        assert result["buckets"][0]["provider_stations"] == 2
        assert result["buckets"][0]["conservative_spatial_groups"] == 1
        assert result["buckets"][0]["verified_independent_physical_stations"] is None
        assert len(result["comparisons"]) == 2
        assert all(
            p["interval_residual_c"] == 0 and p["exact_integer_match"]
            for p in result["comparisons"]
        )
        assert result["total_predictions"] == 0
        assert result["exploratory_cycles"]

    await store._call(inspect)


async def test_reference_gate_blocks_while_raw_capture_is_delayed(monkeypatch):
    import asyncio

    import httpx

    from premetar.collector import poll_source
    from premetar.sources import configured_sources

    entered, release, stop = asyncio.Event(), asyncio.Event(), asyncio.Event()
    gate = ReferenceGate()

    class DelayedStore:
        async def capture(self, packet, body):
            entered.set()
            await release.wait()
            return {**packet, "id": "synthetic"}

        async def parse_and_save(self, *args):
            stop.set()
            return []

    source = configured_sources({"EDDM"}, {"awc"}, 60)[0]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[]))
    ) as client:
        task = asyncio.create_task(poll_source(source, DelayedStore(), client, stop, {}, gate))
        await asyncio.wait_for(entered.wait(), 2)
        with pytest.raises(ValueError, match="PENDING_DURABLE_PARSE"):
            gate.check("EDDM")
        release.set()
        await asyncio.wait_for(task, 2)
    gate.check("EDDM")


def test_clock_cli_keeps_native_unicode_evidence_in_files(monkeypatch):
    from typer.testing import CliRunner

    from premetar.cli import app

    monkeypatch.setattr(
        "premetar.clock_audit.run_audit",
        lambda _: dict(
            verification_status="UNKNOWN", evidence=[{"stdout": "\ufffd native localized output"}]
        ),
    )
    result = CliRunner().invoke(app, ["continuous", "clock-audit"])
    assert result.exit_code == 0
    assert "UNKNOWN" in result.stdout
    assert "native localized" not in result.stdout
