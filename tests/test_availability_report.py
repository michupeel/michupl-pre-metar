"""Synthetic read-only report regressions; no provider requests."""

import json
import sqlite3
from datetime import UTC, datetime

from premetar.pws.availability_report import availability_snapshot, write_availability

AT = datetime(2026, 10, 25, 10, tzinfo=UTC)


def database(checks=True):
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
    CREATE TABLE pws_stations(station_id TEXT,provider TEXT,data_json TEXT);
    CREATE TABLE pws_airport_stations(station_id TEXT,airport_icao TEXT,distance_km REAL);
    CREATE TABLE pws_sensors(sensor_id TEXT,station_id TEXT,data_json TEXT);
    INSERT INTO pws_stations VALUES('opensensemap:one','opensensemap','{}');
    INSERT INTO pws_airport_stations VALUES('opensensemap:one','EPWA',1.5);
    INSERT INTO pws_sensors VALUES('sensor-a','opensensemap:one','{"phenomenon":"temperature"}');
    INSERT INTO pws_sensors VALUES('sensor-b','opensensemap:one','{"phenomenon":"temperature"}');
    """)
    if checks:
        conn.executescript("""
        CREATE TABLE pws_sensor_checks(id INTEGER PRIMARY KEY,airport_icao TEXT,sensor_id TEXT,checked_at TEXT,status TEXT,outcome TEXT,data_json TEXT);
        CREATE TABLE pws_selection_versions(id INTEGER PRIMARY KEY,airport_icao TEXT,provider TEXT,reason TEXT,data_json TEXT);
        """)
    return conn


def check(conn, clock, status="ACTIVE"):
    conn.execute(
        "INSERT INTO pws_sensor_checks VALUES(NULL,'EPWA','sensor-a',? ,?,'SUCCESS_NEW_MEASUREMENT',?)",
        (
            clock,
            status,
            json.dumps(
                dict(
                    measurement_time=clock,
                    temperature_c=12,
                    age_seconds=10,
                    mode="ACTIVE",
                    first_receive_time=clock,
                    raw_unit="C",
                    timestamp_provenance="SENSOR_MEASUREMENT_TIME",
                    timestamp_semantics_verified=True,
                    evidence_class="REALTIME_CAPTURED",
                )
            ),
        ),
    )


def test_missing_availability_schema_is_read_only_unverified(tmp_path):
    conn = database(False)
    conn.execute("PRAGMA query_only=ON")
    report = availability_snapshot(conn, {"EPWA"}, AT)
    assert report["initialization"] == "NOT_INITIALIZED"
    assert report["airports"][0]["unverified"] == 2
    assert report["airports"][0]["eligible_active"] == 0
    write_availability(report, tmp_path)
    assert (tmp_path / "availability_sensors.csv").is_file()


def test_expired_check_is_not_reported_current_active():
    conn = database()
    check(conn, "2026-10-25T09:50:00Z")
    report = availability_snapshot(conn, now=AT)
    assert report["sensors"][0]["status"] == "STALE"
    assert report["sensors"][0]["stored_status"] == "ACTIVE"
    assert report["airports"][0]["eligible_active"] == 0


def test_latest_selection_and_checks_preserve_distinct_instruments(tmp_path):
    conn = database()
    check(conn, "2026-10-25T09:50:00Z", "NO_MEASUREMENT")
    check(conn, "2026-10-25T09:59:00Z")
    for selected in ([], ["sensor-a"]):
        conn.execute(
            "INSERT INTO pws_selection_versions VALUES(NULL,'EPWA','opensensemap','Availability only',?)",
            (
                json.dumps(
                    dict(selected_sensor_ids=selected, rationale={"sensor-a": "Fresh measurement"})
                ),
            ),
        )
    conn.execute("PRAGMA query_only=ON")
    report = availability_snapshot(conn, now=AT)
    summary = report["airports"][0]
    assert summary["temperature_sensors"] == 2
    assert summary["active_provider_stations"] == 1
    assert summary["selected_provider_stations"] == 1
    assert report["sensors"][0]["selection_version"] == 2
    assert report["sensors"][0]["selection_rationale"] == "Fresh measurement"
    write_availability(report, tmp_path)
    assert "Fresh measurement" in (tmp_path / "availability.md").read_text(encoding="utf-8")


def test_future_or_naive_active_check_is_invalid():
    for clock in ("2026-10-25T10:00:01Z", "2026-10-25T09:59:00"):
        conn = database()
        check(conn, clock)
        assert availability_snapshot(conn, now=AT)["sensors"][0]["status"] == "INVALID"


def test_legacy_empty_rows_are_reported_but_not_measurements(tmp_path):
    from datetime import date

    from premetar.continuous.data import migrate
    from premetar.pws.daily import make_report
    from premetar.pws.models import Sensor, Station
    from premetar.pws.repository import SCHEMA as PWS_SCHEMA
    from premetar.store import SCHEMA

    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    conn.executescript(PWS_SCHEMA)
    migrate(conn)
    station = Station(
        provider="opensensemap",
        provider_station_id="old-empty",
        latitude=52.16,
        longitude=20.97,
        sensors=[Sensor(provider_sensor_id="t", unit="C")],
    )
    with conn:
        conn.execute("INSERT INTO pws_providers VALUES('opensensemap','{}','VERIFIED')")
        conn.execute("INSERT INTO pws_airports VALUES('EPWA','{}')")
        conn.execute(
            "INSERT INTO pws_stations VALUES(?,?,?,?,?,?)",
            (
                station.station_id,
                "opensensemap",
                "old-empty",
                AT.isoformat(),
                AT.isoformat(),
                station.model_dump_json(),
            ),
        )
        conn.execute(
            "INSERT INTO pws_airport_stations VALUES(?,?,?)", (station.station_id, "EPWA", 1.0)
        )
        conn.execute(
            "INSERT INTO pws_sensors VALUES(?,?,?,?)",
            (
                station.station_id + ":t",
                station.station_id,
                "t",
                station.sensors[0].model_dump_json(),
            ),
        )
        conn.execute(
            "INSERT INTO pws_observations VALUES(?,?,NULL,NULL,NULL,?,'REALTIME_CAPTURED','{}')",
            ("historical-empty", station.station_id + ":t", AT.isoformat()),
        )
    conn.execute("PRAGMA query_only=ON")
    result = make_report(conn, "EPWA", date(2026, 10, 25), tmp_path / "report", now=AT)
    assert result["legacy_empty_poll_records"] == 1
    assert result["actual_temperature_records_in_day"] == 0
    assert result["total_valid_observations"] == 0
    assert result["normalized_provider_records_in_day"] == 1
    assert conn.execute("SELECT count(*) FROM pws_observations").fetchone()[0] == 1


def test_recovery_hysteresis_and_provider_scope():
    conn = database()
    check(conn, "2026-10-25T09:59:00Z")
    payload = json.loads(conn.execute("SELECT data_json FROM pws_sensor_checks").fetchone()[0])
    payload["mode"] = "INACTIVE"
    conn.execute("UPDATE pws_sensor_checks SET data_json=?", (json.dumps(payload),))
    conn.execute("INSERT INTO pws_stations VALUES('sensor_community:two','sensor_community','{}')")
    conn.execute("INSERT INTO pws_airport_stations VALUES('sensor_community:two','EPWA',2)")
    conn.execute("INSERT INTO pws_sensors VALUES('sc-sensor','sensor_community:two','{}')")
    report = availability_snapshot(conn, now=AT)
    assert report["airports"][0]["active_temperature_sensors"] == 1
    assert report["airports"][0]["eligible_active"] == 0
    assert report["airports"][0]["temperature_sensors"] == 2
    assert (
        availability_snapshot(conn, now=AT, provider=None)["airports"][0]["temperature_sensors"]
        == 3
    )


def test_preflight_inventory_and_current_run_poll_counts_are_separate(tmp_path):
    conn = database()
    for name in ("run_id", "station_id", "raw_id", "observation_id"):
        conn.execute(f"ALTER TABLE pws_sensor_checks ADD COLUMN {name} TEXT")
    conn.executescript("""
        CREATE TABLE runs(id TEXT,started_at TEXT);
        INSERT INTO runs VALUES('new-run','2026-10-25T09:00:00Z');
        CREATE TABLE pws_preflight_runs(id INTEGER PRIMARY KEY,run_id TEXT,airport_icao TEXT,completed_at TEXT,data_json TEXT);
    """)
    payload = dict(measurement_time="2026-10-25T09:50:00Z", temperature_c=12, mode="ACTIVE")
    for run, raw, outcome in (
        ("old-run", "old", "SUCCESS_NEW_MEASUREMENT"),
        ("new-run", "r1", "SUCCESS_NEW_MEASUREMENT"),
        ("new-run", "r2", "SUCCESS_UNCHANGED_MEASUREMENT"),
    ):
        conn.execute(
            "INSERT INTO pws_sensor_checks(airport_icao,sensor_id,checked_at,status,outcome,data_json,run_id,station_id,raw_id,observation_id) VALUES('EPWA','sensor-a','2026-10-25T09:50:00Z','ACTIVE',?, ?,?,'opensensemap:one',?,'same-source-measurement')",
            (outcome, json.dumps(payload), run, raw),
        )
    for count in (100, 123):
        conn.execute(
            "INSERT INTO pws_preflight_runs VALUES(NULL,'new-run','EPWA','2026-10-25T09:55:00Z',?)",
            (
                json.dumps(
                    dict(
                        discovered_stations=count,
                        temperature_sensors=150,
                        checked_stations=99,
                        preflight_capped=True,
                    )
                ),
            ),
        )
    conn.execute("PRAGMA query_only=ON")
    report = availability_snapshot(conn, now=AT)
    summary = report["airports"][0]
    assert summary["fresh_discovered_stations"] == 123
    assert summary["retained_inventory_stations"] == 1
    assert summary["fresh_temperature_sensors"] == 150
    assert summary["active_at_last_check"] == 1
    assert summary["eligible_active"] == 0
    assert summary["current_run_sensor_poll_attempts"] == 2
    assert summary["current_run_unique_source_measurement_ids"] == 1
    assert {
        r["outcome"]: r["sensor_poll_attempts"] for r in summary["current_run_sensor_poll_outcomes"]
    } == {"SUCCESS_NEW_MEASUREMENT": 1, "SUCCESS_UNCHANGED_MEASUREMENT": 1}
    write_availability(report, tmp_path)
    assert "Fresh stations" in (tmp_path / "availability.md").read_text(encoding="utf-8")


def test_empty_payload_missing_clocks_do_not_inflate_invalid_timestamp_count():
    conn = database()
    conn.execute("INSERT INTO pws_sensors VALUES('sensor-c','opensensemap:one','{}')")
    examples = (
        (
            "sensor-a",
            "NO_MEASUREMENT",
            None,
            None,
            ["MISSING_MEASUREMENT_TIME", "UNKNOWN_TIMESTAMP_PROVENANCE"],
        ),
        ("sensor-b", "INVALID", 12, "12", ["FUTURE_MEASUREMENT_AT_RECEIPT"]),
        ("sensor-c", "INVALID", None, "malformed", ["INVALID_MEASUREMENT_TIMESTAMP"]),
    )
    for sensor, status, temperature, raw, reasons in examples:
        conn.execute(
            "INSERT INTO pws_sensor_checks VALUES(NULL,'EPWA',?,'2026-10-25T09:59:00Z',?,'INVALID_MEASUREMENT',?)",
            (
                sensor,
                status,
                json.dumps(
                    dict(
                        temperature_c=temperature,
                        raw_temperature=raw,
                        reasons=reasons,
                        mode="INACTIVE",
                    )
                ),
            ),
        )
    report = availability_snapshot(conn, now=AT)
    summary = report["airports"][0]
    assert summary["no_measurement"] == 1
    assert summary["invalid_timestamps"] == 2
    assert "MISSING_MEASUREMENT_TIME" in report["sensors"][0]["reasons"]
    assert report["sensors"][2]["raw_temperature"] == "malformed"
