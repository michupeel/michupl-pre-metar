"""Synthetic timing, lifecycle, settlement and Windows behavior tests."""

import json
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from xml.etree import ElementTree as ET

import pytest
import pytest_asyncio

from premetar.continuous.config import Config
from premetar.continuous.data import baseline, migrate, schedule, settle
from premetar.continuous.locking import acquire
from premetar.continuous.polling import next_interval, observation_interval, provider_state
from premetar.continuous.reporting import report
from premetar.continuous.windows import NS, owned, task_xml
from premetar.parsers import parse_metar
from premetar.pws.providers import OpenSenseMap, SensorCommunity
from premetar.pws.repository import PWSStore, rows
from premetar.pws.service import settings

AT = datetime(2026, 10, 31, 23, 45, tzinfo=UTC)
TARGET = AT + timedelta(minutes=5)


@pytest_asyncio.fixture
async def store(tmp_path):
    s = PWSStore(tmp_path / "test.db", tmp_path / "raw", "synthetic")
    await s.open({"synthetic": True}, {"awc": 60, "knmi_metar": 60})
    await s._call(s.register, settings().airports, [OpenSenseMap, SensorCommunity])
    await s._call(migrate, s.connection)
    yield s
    await s.close("test")


async def metar(
    store, event, receive, temp=18, kind="METAR", cor=False, source="awc", startup=False
):
    tac = (
        f"{kind} {'COR ' if cor else ''}EDDM {event:%d%H%M}Z AUTO 00000KT 9999 {temp:02d}/10 Q1013"
    )
    body = tac.encode()
    packet = await store.capture(
        dict(
            source=source,
            request_url="https://example.test",
            http_status=200,
            headers={},
            request_start=(receive - timedelta(seconds=1)).isoformat(),
            request_end=receive.isoformat(),
            received_at=receive.isoformat(),
            monotonic_ns=time.perf_counter_ns(),
            request_start_monotonic_ns=time.perf_counter_ns() - 100,
        ),
        body,
    )
    await store.parse_and_save(
        packet,
        body,
        lambda b, anchor: [parse_metar(b.decode(), anchor, source)],
        {"EDDM"},
        startup,
        False,
    )


def test_polling_timezones_dedup_sort_and_bounds():
    times = [AT + timedelta(minutes=i) for i in range(4)]
    assert observation_interval(list(reversed(times)) + times) == 60
    assert observation_interval(times[:3]) is None
    assert next_interval(times, 300, 1800) == 300
    assert next_interval([], 300, 1800, 10) == 1800
    with pytest.raises(ValueError):
        observation_interval([datetime(2026, 1, 1)])
    for minimum, maximum in [(0, 1), (1, float("inf")), (float("nan"), 10), (10, 1)]:
        with pytest.raises(ValueError):
            next_interval([], minimum, maximum)


def test_provider_states():
    assert provider_state(disabled=True, auth_failed=True) == "DISABLED"
    assert provider_state(auth_failed=True, rate_limited=True) == "AUTH_FAILED"
    assert provider_state(rate_limited=True) == "RATE_LIMITED"
    assert provider_state() == "STALE"
    assert provider_state(last_data_age=10, failures=1) == "DEGRADED"
    assert provider_state(last_data_age=10) == "HEALTHY"


def test_config_rejects_unverified_sources_and_unsafe_polls():
    for update in [
        {"providers": ["netatmo"]},
        {"minimum_poll_interval": 1},
        {"checkpoints": [60, 60]},
        {"airports": ["XXXX"]},
    ]:
        with pytest.raises(ValueError):
            Config(**update)


def test_task_xml_quotes_namespace_and_restart():
    python = r"C:\Weather & Research\.venv\Scripts\pythonw.exe"
    root = r"C:\Weather & Research"
    config = root + r"\configs\continuous v1.json"
    xml = task_xml(python, root, config, "S-1-5-21-123")
    tree = ET.fromstring(xml)
    ns = {"t": NS}
    assert tree.findtext("t:Actions/t:Exec/t:Command", namespaces=ns) == python
    assert '"' + config + '"' in tree.findtext("t:Actions/t:Exec/t:Arguments", namespaces=ns)
    assert tree.findtext("t:Settings/t:RestartOnFailure/t:Interval", namespaces=ns) == "PT1M"
    assert tree.findtext("t:Settings/t:MultipleInstancesPolicy", namespaces=ns) == "IgnoreNew"
    assert (
        tree.findtext("t:Principals/t:Principal/t:LogonType", namespaces=ns) == "InteractiveToken"
    )
    assert owned(xml, python, root, config)
    assert not owned(xml.replace("continuous-v1", "unrelated"), python, root, config)
    assert not owned(xml, python + "other", root, config)


def test_single_instance_lock_rejects_live_and_unknown(tmp_path):
    path = tmp_path / "db.lock"
    handle = acquire(path, "synthetic")
    try:
        with pytest.raises(FileExistsError):
            acquire(path, "other", True)
    finally:
        handle.close()
    path.write_text("legacy-unknown")
    with pytest.raises(FileExistsError):
        acquire(path, "other", True)


async def test_baseline_asof_delayed_future_and_quantized_reference(store, monkeypatch):
    await metar(store, AT - timedelta(minutes=25), AT - timedelta(minutes=23), 17)
    await metar(store, AT - timedelta(minutes=55), AT - timedelta(minutes=53), 16)
    # Received later: not eligible even though measurement nominal is earlier.
    await metar(store, AT - timedelta(minutes=25), AT + timedelta(seconds=1), 30, cor=True)
    monkeypatch.setattr("premetar.continuous.data.utc_now", lambda: AT)

    def run():
        with store.connection:
            p = baseline(store.connection, "EDDM", TARGET, "previous_metar", store.run_id, "T-300s")
            trend = baseline(
                store.connection,
                "EDDM",
                TARGET,
                "simple_recent_metar_trend",
                store.run_id,
                "T-300s",
            )
        assert p["integer_temperature"] == 17
        assert trend["integer_temperature"] == 18
        assert p["created_at"] == AT.isoformat()

    await store._call(run)


async def test_scheduler_idempotent_missed_and_month_rollover(store, monkeypatch):
    await metar(store, AT - timedelta(minutes=25), AT - timedelta(minutes=23))
    monkeypatch.setattr("premetar.continuous.data.utc_now", lambda: AT)
    monkeypatch.setattr("premetar.pws.analysis.utc_now", lambda: AT)
    cfg = Config(airports=["EDDM"], checkpoints=[300])
    await store._call(schedule, store.connection, cfg, store.run_id, AT)
    before = await store._call(rows, store.connection, "SELECT * FROM continuous_checkpoints")
    await store._call(schedule, store.connection, cfg, store.run_id, AT)
    after = await store._call(rows, store.connection, "SELECT * FROM continuous_checkpoints")
    assert before == after
    generated = [r for r in after if r["status"] == "GENERATED"]
    assert len(generated) == 2  # previous METAR and persistence; trend unavailable
    assert all(datetime.fromisoformat(r["target"]) == TARGET for r in generated)
    assert any(r["status"] == "MISSED" for r in after)
    # New day uses UTC calendar and does not replay elapsed checkpoints.
    later = datetime(2026, 11, 1, 0, 17, tzinfo=UTC)
    await store._call(schedule, store.connection, cfg, store.run_id, later)
    assert all(
        r["status"] != "GENERATED"
        for r in await store._call(
            rows,
            store.connection,
            "SELECT * FROM continuous_checkpoints WHERE target LIKE '2026-11-01%'",
        )
    )


async def test_settlement_speci_corrections_duplicates_and_immutability(
    store, monkeypatch, tmp_path
):
    await metar(store, AT - timedelta(minutes=25), AT - timedelta(minutes=23), 17)
    monkeypatch.setattr("premetar.continuous.data.utc_now", lambda: AT)

    def forecast():
        with store.connection:
            return baseline(
                store.connection, "EDDM", TARGET, "previous_metar", store.run_id, "T-300s"
            )

    prediction = await store._call(forecast)
    await metar(store, TARGET, TARGET + timedelta(minutes=1), 17, kind="SPECI")
    assert await store._call(settle, store.connection, TARGET + timedelta(minutes=1)) == 0
    await metar(store, TARGET, TARGET + timedelta(minutes=2), 18)
    assert await store._call(settle, store.connection, TARGET + timedelta(minutes=2)) == 1
    await metar(store, TARGET, TARGET + timedelta(minutes=3), 18, source="knmi_metar")
    assert await store._call(settle, store.connection, TARGET + timedelta(minutes=3)) == 0
    await metar(store, TARGET, TARGET + timedelta(minutes=4), 19, cor=True)
    assert await store._call(settle, store.connection, TARGET + timedelta(minutes=4)) == 1
    assert await store._call(settle, store.connection, TARGET + timedelta(minutes=5)) == 0

    def verify():
        conn = store.connection
        outcomes = rows(conn, "SELECT * FROM continuous_settlements ORDER BY id")
        assert len(outcomes) == 2
        assert outcomes[0]["official_integer"] == 18 and outcomes[1]["official_integer"] == 19
        assert outcomes[0]["reference_first_seen"] == (TARGET + timedelta(minutes=2)).isoformat()
        assert outcomes[1]["correction"] == 1
        assert conn.execute(
            "SELECT data_json FROM pws_predictions WHERE id=?", (prediction["id"],)
        ).fetchone()[0] == json.dumps(prediction)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE continuous_settlements SET official_integer=99")
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        report(conn, tmp_path / "report")
        assert "INSUFFICIENT DATA" in (tmp_path / "report" / "prediction_accuracy.md").read_text()

    await store._call(verify)


async def test_transaction_rollback_and_migration_repeat(store):
    def verify():
        conn = store.connection
        migrate(conn)
        before = conn.execute("SELECT count(*) FROM continuous_checkpoints").fetchone()[0]
        with pytest.raises(RuntimeError), conn:
            conn.execute(
                "INSERT INTO continuous_checkpoints VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    "fixture",
                    "EDDM",
                    TARGET.isoformat(),
                    60,
                    "previous_metar",
                    AT.isoformat(),
                    "MISSED",
                    None,
                    None,
                ),
            )
            raise RuntimeError("synthetic interruption")
        assert conn.execute("SELECT count(*) FROM continuous_checkpoints").fetchone()[0] == before

    await store._call(verify)


async def test_early_received_nominal_future_blocks_baseline(store, monkeypatch):
    await metar(store, AT - timedelta(minutes=25), AT - timedelta(minutes=23), 17)
    # Synthetic analogue of observed KNMI early nominal future report.
    await metar(store, TARGET, AT - timedelta(seconds=1), 19, source="knmi_metar")
    monkeypatch.setattr("premetar.continuous.data.utc_now", lambda: AT)
    with pytest.raises(ValueError, match="TARGET_ALREADY_RECEIVED"):
        await store._call(
            baseline, store.connection, "EDDM", TARGET, "previous_metar", store.run_id, "T-300s"
        )


def test_crash_recovery_releases_os_lock(tmp_path):
    import subprocess
    import sys

    lock = tmp_path / "interrupted.lock"
    script = "import os,sys; from pathlib import Path; from premetar.continuous.locking import acquire; h=acquire(Path(sys.argv[1]),'crash-fixture'); os._exit(0)"
    subprocess.run([sys.executable, "-c", script, str(lock)], check=True, timeout=10)
    handle = acquire(lock, "recovered", True)
    handle.close()
    lock.unlink()


async def test_sqlite_lock_contention_bounded_and_recoverable(store):
    def timeout():
        store.connection.execute("PRAGMA busy_timeout=10")

    await store._call(timeout)
    other = sqlite3.connect(store.database, timeout=0.01)
    other.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            await store._call(
                lambda: store.connection.execute(
                    "INSERT INTO continuous_cursor VALUES('lock-fixture',?)", (AT.isoformat(),)
                )
            )
    finally:
        other.rollback()
        other.close()

    def retry():
        with store.connection:
            store.connection.execute(
                "INSERT INTO continuous_cursor VALUES('lock-fixture',?)", (AT.isoformat(),)
            )
        assert store.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    await store._call(retry)


async def test_resume_records_gap_without_backdating(store, monkeypatch):
    cfg = Config(airports=["EDDM"], checkpoints=[300])
    monkeypatch.setattr("premetar.continuous.data.utc_now", lambda: AT)
    monkeypatch.setattr("premetar.pws.analysis.utc_now", lambda: AT)
    await store._call(schedule, store.connection, cfg, store.run_id, AT - timedelta(hours=2))
    await store._call(schedule, store.connection, cfg, store.run_id, AT)
    data = await store._call(
        rows,
        store.connection,
        "SELECT * FROM continuous_checkpoints WHERE reason='CHECKPOINT_ELAPSED'",
    )
    assert len(data) >= 14
    assert all(r["prediction_id"] is None and r["status"] == "MISSED" for r in data)


def test_lead_percentiles_and_no_nonfinite_values():
    from premetar.continuous.statistics import lead_summary

    assert lead_summary([10, 20, 30]) == dict(N=3, p10=12, p50=20, p90=28, maximum=30)
    assert lead_summary([])["p50"] is None
    for value in (float("nan"), float("inf"), 0, -1):
        with pytest.raises(ValueError):
            lead_summary([value])


async def test_continuous_public_jobs_isolate_auth_and_preserve_raw(tmp_path, monkeypatch):
    import httpx

    from premetar.collector import collect
    from premetar.parsers import parse_awc
    from premetar.sources import HttpSource

    sc = {
        "id": 1,
        "timestamp": "2026-10-31 23:44:00",
        "location": {"id": 10, "latitude": "48.35", "longitude": "11.81", "indoor": 0},
        "sensor": {"id": 123, "sensor_type": {"name": "BME280"}},
        "sensordatavalues": [{"value_type": "temperature", "value": "18.2"}],
    }
    monkeypatch.setattr(
        "premetar.collector.clock_status",
        lambda: dict(warning="synthetic", synchronization_confirmed=False),
    )

    def response(request):
        if request.url.host == "metar.test":
            return httpx.Response(
                200,
                json=[
                    dict(icaoId="EDDM", rawOb="METAR EDDM 312320Z AUTO 00000KT 9999 18/10 Q1013")
                ],
            )
        if request.url.host == "api.opensensemap.org":
            return httpx.Response(401, json={"error": "synthetic"})
        return httpx.Response(200, json=[sc])

    cfg = Config(
        airports=["EDDM"],
        database_path=tmp_path / "continuous.db",
        raw_storage_path=tmp_path / "raw",
    )
    await collect(
        [HttpSource("awc", "https://metar.test", frozenset({"EDDM"}), parse_awc)],
        {"EDDM"},
        cfg.database_path,
        cfg.raw_storage_path,
        0.2,
        False,
        httpx.MockTransport(response),
        continuous_config=cfg,
    )
    with sqlite3.connect(cfg.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM pws_observations").fetchone()[0] > 0
        assert conn.execute("SELECT count(*) FROM errors").fetchone()[0] > 0
        assert conn.execute("SELECT count(*) FROM raw_payloads").fetchone()[0] >= 3
        assert conn.execute("SELECT count(*) FROM observations").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert not cfg.database_path.with_suffix(".db.lock").exists()


def test_day_blocks_require_targets_and_days_and_are_reproducible():
    from premetar.continuous.statistics import day_block_interval

    assert day_block_interval([("2026-01-01", 1)] * 100)["status"] == "INSUFFICIENT DATA"
    values = [(f"2026-01-{d:02d}", float(d % 3)) for d in range(1, 8) for _ in range(20)]
    result = day_block_interval(values)
    assert result == day_block_interval(values)
    assert result["N"] == 140 and result["days"] == 7
    assert result["lower"] <= sum(v for _, v in values) / len(values) <= result["upper"]


async def test_experiment_configuration_is_frozen(store):
    from premetar.continuous.data import freeze_experiment

    cfg = Config()
    await store._call(freeze_experiment, store.connection, cfg)
    await store._call(freeze_experiment, store.connection, cfg)
    with pytest.raises(ValueError, match="configuration changed"):
        await store._call(freeze_experiment, store.connection, Config(checkpoints=[60]))


def test_task_verification_checks_sid_and_security_settings():
    from premetar.continuous.windows import verified

    xml = task_xml("pythonw.exe", "root", "config", "sid")
    assert verified(xml, "pythonw.exe", "root", "config", "sid")
    assert not verified(xml, "pythonw.exe", "root", "config", "other")
    assert not verified(
        xml.replace("LeastPrivilege", "HighestAvailable"), "pythonw.exe", "root", "config", "sid"
    )
    assert not verified(
        xml.replace("IgnoreNew", "Parallel"), "pythonw.exe", "root", "config", "sid"
    )


async def test_future_nominal_settles_when_due_without_new_report(store, monkeypatch):
    await metar(store, AT - timedelta(minutes=25), AT - timedelta(minutes=23), 17)
    monkeypatch.setattr("premetar.continuous.data.utc_now", lambda: AT)

    def forecast():
        with store.connection:
            return baseline(
                store.connection, "EDDM", TARGET, "previous_metar", store.run_id, "T-300s"
            )

    p = await store._call(forecast)
    await metar(store, TARGET, AT + timedelta(minutes=2), 18, source="knmi_metar")
    assert await store._call(settle, store.connection, AT + timedelta(minutes=2), 0) == 0
    maxid = await store._call(
        lambda: store.connection.execute("SELECT max(id) FROM observations").fetchone()[0]
    )
    assert await store._call(settle, store.connection, TARGET, maxid) == 1
    data = await store._call(
        rows,
        store.connection,
        "SELECT * FROM continuous_settlements WHERE prediction_id=?",
        (p["id"],),
    )
    assert json.loads(data[0]["data_json"])["lead_seconds"] == 120


async def test_qc_publication_is_after_input_cutoff(store, monkeypatch):
    from premetar.continuous.engine import refresh_quality
    from premetar.pws.models import Sensor, Station
    from premetar.pws.service import settings

    station = Station(
        provider="opensensemap",
        provider_station_id="qc-fixture",
        latitude=48.35,
        longitude=11.81,
        sensors=[Sensor(provider_sensor_id="t", unit="C")],
    )
    packet = await store.capture(
        dict(
            source="pws_opensensemap",
            request_url="https://example.test",
            http_status=200,
            headers={},
            request_start=AT.isoformat(),
            request_end=AT.isoformat(),
            received_at=AT.isoformat(),
            monotonic_ns=time.perf_counter_ns(),
            request_start_monotonic_ns=time.perf_counter_ns(),
        ),
        b"synthetic-discovery",
    )
    await store._call(store.discover, settings().airports[0], station, packet)
    clocks = iter([AT, AT + timedelta(seconds=1)])
    monkeypatch.setattr("premetar.continuous.engine.utc_now", lambda: next(clocks))
    await store._call(refresh_quality, store, "EDDM", Config())
    data = await store._call(rows, store.connection, "SELECT * FROM pws_quality_results")
    assert data
    for item in data:
        payload = json.loads(item["data_json"])
        assert item["created_at"] == (AT + timedelta(seconds=1)).isoformat()
        assert payload["input_cutoff_time"] == AT.isoformat()
        assert payload["published_at"] == item["created_at"]


def test_operational_logs_are_structured_utc():
    import logging

    from premetar.continuous.cli import JsonFormatter

    record = logging.LogRecord(
        "premetar", logging.WARNING, "fixture", 1, "error_class=%s", ("TimeoutError",), None
    )
    payload = json.loads(JsonFormatter().format(record))
    assert payload["at"].endswith("+00:00")
    assert payload["event"] == "error_class=TimeoutError"


async def test_nearest_precedes_cluster_deduplication(store):
    from premetar.pws.analysis import predict
    from premetar.pws.models import QCConfig, Reading, Sensor, Station
    from premetar.pws.service import settings

    received = AT - timedelta(seconds=1)
    packet = await store.capture(
        dict(
            source="pws_opensensemap",
            request_url="https://example.test",
            http_status=200,
            headers={},
            request_start=received.isoformat(),
            request_end=received.isoformat(),
            received_at=received.isoformat(),
            monotonic_ns=time.perf_counter_ns(),
            request_start_monotonic_ns=time.perf_counter_ns(),
        ),
        b"synthetic-nearest",
    )
    for name, latitude, temp in [("a-far", 48.350, 19), ("z-near", 48.349, 18)]:
        station = Station(
            provider="opensensemap",
            provider_station_id=name,
            latitude=latitude,
            longitude=11.813,
            exposure="outdoor",
            sensors=[Sensor(provider_sensor_id="t", unit="C")],
        )
        await store._call(store.discover, settings().airports[0], station, packet)
        await store._call(
            store.ingest,
            station,
            Reading(
                provider_sensor_id="t",
                observation_time=AT - timedelta(minutes=1),
                temperature_c=temp,
                raw_unit="C",
                raw_temperature=str(temp),
                timestamp_provenance="SENSOR_MEASUREMENT_TIME",
                timestamp_semantics_verified=True,
            ),
            packet,
        )

        def choose(station_id=station.station_id):
            with store.connection:
                store.connection.execute(
                    "INSERT INTO pws_selections VALUES(NULL,?,?,?,?,?)",
                    (station_id, "EDDM", received.isoformat(), 1, "synthetic"),
                )

        await store._call(choose)

    def forecast():
        with store.connection:
            return predict(
                store.connection, "EDDM", TARGET, QCConfig(), method="nearest", created=AT
            )

    p = await store._call(forecast)
    assert p["estimate_c"] == 18
    assert p["contributions"][0]["station_id"] == "opensensemap:z-near"


def test_windows_canonical_xml_requires_independent_limited_evidence():
    from premetar.continuous.windows import verified

    xml = task_xml("pythonw.exe", "root", "config", "sid")
    tree = ET.fromstring(xml)
    principal = tree.find("t:Principals/t:Principal", {"t": NS})
    principal.remove(principal.find("t:RunLevel", {"t": NS}))
    tree.find("t:Triggers/t:LogonTrigger/t:UserId", {"t": NS}).text = "DOMAIN\\User"
    canonical = ET.tostring(tree, encoding="unicode")
    assert not verified(canonical, "pythonw.exe", "root", "config", "sid")
    assert verified(
        canonical,
        "pythonw.exe",
        "root",
        "config",
        "sid",
        account_name="domain\\user",
        effective_run_level="Limited",
    )
    assert not verified(
        canonical,
        "pythonw.exe",
        "root",
        "config",
        "sid",
        account_name="other\\user",
        effective_run_level="Limited",
    )
    assert not verified(
        canonical,
        "pythonw.exe",
        "root",
        "config",
        "sid",
        account_name="domain\\user",
        effective_run_level="Highest",
    )


def test_registered_task_verification_queries_root_folder(monkeypatch):
    import subprocess

    from premetar.continuous import windows

    sid = "S-1-5-21-123"
    tree = ET.fromstring(task_xml("pythonw.exe", "root", "config", sid))
    principal = tree.find("t:Principals/t:Principal", {"t": NS})
    principal.remove(principal.find("t:RunLevel", {"t": NS}))
    tree.find("t:Triggers/t:LogonTrigger/t:UserId", {"t": NS}).text = "DOMAIN\\User"

    def respond(args):
        if args[0] == "whoami":
            return subprocess.CompletedProcess(args, 0, '"domain\\user","' + sid + '"\n', "")
        assert "-TaskPath ([string][char]92)" in args[-1]
        return subprocess.CompletedProcess(args, 0, '{"run_level":"Limited"}', "")

    monkeypatch.setattr(windows, "run", respond)
    assert windows.verify_registered(
        ET.tostring(tree, encoding="unicode"), "pythonw.exe", "root", "config", sid
    )
