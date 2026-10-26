"""Synthetic actual-forecast audit fixtures, never observed weather results."""

import importlib.util
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

SPEC = importlib.util.spec_from_file_location(
    "early_metar_prospective",
    Path(__file__).resolve().parents[1] / "scripts/research/early_metar_prospective.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fixture_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript("""
        CREATE TABLE observations(id INTEGER PRIMARY KEY,identity TEXT,station_icao TEXT,product_type TEXT,event_time TEXT,temperature_c REAL,startup_censored INTEGER,coverage_gap INTEGER,data_json TEXT,collector_receive_time TEXT);
        CREATE TABLE report_receipts(id INTEGER PRIMARY KEY,observation_id INTEGER,collector_receive_time TEXT);
        CREATE TABLE pws_predictions(id TEXT PRIMARY KEY,airport_icao TEXT,created_at TEXT,decision_time TEXT,target_time TEXT,data_json TEXT);
        CREATE TABLE prediction_exclusions(prediction_id TEXT,reason TEXT);
        CREATE TABLE continuous_settlements(id INTEGER PRIMARY KEY,prediction_id TEXT,report_identity TEXT,settled_at TEXT,reference_first_seen TEXT,official_integer INTEGER,correction INTEGER,data_json TEXT);
        CREATE TABLE pws_observations(id TEXT PRIMARY KEY,sensor_id TEXT,observation_time TEXT,temperature_c REAL,first_receive_time TEXT,data_json TEXT);
        CREATE TABLE pws_sensors(sensor_id TEXT PRIMARY KEY,station_id TEXT,provider_sensor_id TEXT);
        CREATE TABLE pws_stations(station_id TEXT PRIMARY KEY,provider TEXT);
        """)
        for ident, event, receipt, temp in (
            (1, "2026-10-25T12:00:00+00:00", "2026-10-25T12:02:00+00:00", 12),
            (2, "2026-10-25T12:30:00+00:00", "2026-10-25T12:32:00+00:00", 13),
        ):
            conn.execute(
                "INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?)",
                (ident, str(ident), "EPWA", "METAR", event, temp, 0, 0, "{}", receipt),
            )
            conn.execute("INSERT INTO report_receipts VALUES(?,?,?)", (ident, ident, receipt))
        add_forecast(conn, "base", "previous_metar", 12)
        add_forecast(conn, "pws", "nearest", 13)


def add_forecast(
    conn: sqlite3.Connection,
    identity: str,
    method: str,
    integer: int,
    *,
    checkpoint: str = "T-60s",
    inputs: list[Any] | None = None,
) -> None:
    pred = dict(
        id=identity,
        airport_icao="EPWA",
        created_at="2026-10-25T12:29:00+00:00",
        decision_time="2026-10-25T12:29:00+00:00",
        input_cutoff_time="2026-10-25T12:29:00+00:00",
        target_time="2026-10-25T12:30:00+00:00",
        estimate_c=integer,
        integer_temperature=integer,
        method=method,
        checkpoint=checkpoint,
        input_observation_ids=inputs if inputs is not None else [1],
        contributions=[],
    )
    conn.execute(
        "INSERT INTO pws_predictions VALUES(?,?,?,?,?,?)",
        (
            identity,
            "EPWA",
            pred["created_at"],
            pred["decision_time"],
            pred["target_time"],
            json.dumps(pred),
        ),
    )
    conn.execute(
        "INSERT INTO continuous_settlements(prediction_id,report_identity,settled_at,reference_first_seen,official_integer,correction,data_json) VALUES(?,?,?,?,?,?,?)",
        (
            identity,
            "2",
            "2026-10-25T12:32:01+00:00",
            "2026-10-25T12:32:00+00:00",
            13,
            0,
            json.dumps(dict(valid_prospective=True, startup_censored=False, coverage_gap=False)),
        ),
    )


def readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def test_audit_preserves_originals_and_uses_same_target_baseline(tmp_path: Path) -> None:
    path = tmp_path / "forecast.sqlite3"
    fixture_db(path)
    before = path.read_bytes()
    with readonly(path) as conn:
        result = MODULE.audit_prospective(conn)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM pws_predictions")
    assert path.read_bytes() == before
    assert result["airports"]["EPWA"]["valid_forecasts"] == 2
    group = result["groups"]["EPWA|T-60s|nearest"]
    assert group["matched_candidate"]["n"] == 1
    assert group["matched_incremental_correct"] == 1
    assert group["matched_incremental_harm"] == 0
    assert group["matched_recorded_baseline"]["correct_integer"] == 0
    assert result["valid"][0]["lead_seconds"] == 180


def test_earlier_receipt_from_other_provider_closes_target(tmp_path: Path) -> None:
    path = tmp_path / "forecast.sqlite3"
    fixture_db(path)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO report_receipts VALUES(3,2,'2026-10-25T12:28:00+00:00')")
    with readonly(path) as conn:
        result = MODULE.audit_prospective(conn)
    assert result["valid"] == []
    assert all("TARGET_ALREADY_RECEIVED" in r["reasons"] for r in result["excluded"])


def test_invalid_pws_timestamp_is_excluded(tmp_path: Path) -> None:
    path = tmp_path / "forecast.sqlite3"
    fixture_db(path)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO pws_stations VALUES('station','opensensemap')")
        conn.execute("INSERT INTO pws_sensors VALUES('sensor','station','provider-sensor')")
        conn.execute(
            "INSERT INTO pws_observations VALUES(?,?,?,?,?,?)",
            (
                "untimed",
                "sensor",
                None,
                13,
                "2026-10-25T12:28:30+00:00",
                json.dumps(
                    dict(temperature_c=13, raw_unit="°C", evidence_class="REALTIME_CAPTURED")
                ),
            ),
        )
        add_forecast(conn, "bad", "nearest", 13, inputs=["untimed"])
    with readonly(path) as conn:
        result = MODULE.audit_prospective(conn)
    excluded = next(r for r in result["excluded"] if r["prediction_id"] == "bad")
    assert "MISSING_MEASUREMENT_TIME" in excluded["reasons"]
    assert "UNKNOWN_TIMESTAMP_PROVENANCE" in excluded["reasons"]


def test_matching_never_uses_different_checkpoint_or_target() -> None:
    shared = dict(
        airport_icao="EHAM",
        checkpoint="T-60s",
        target_time="2026-10-25T12:50:00+00:00",
        created_at="2026-10-25T12:49:00+00:00",
        actual_integer=15,
        previous_integer=14,
        interval_error=0,
        lead_seconds=180,
    )
    records = [
        dict(**shared, prediction_id="base", method="previous_metar", predicted_integer=14),
        dict(**shared, prediction_id="a", method="nearest", predicted_integer=15),
        {
            **shared,
            "prediction_id": "unmatched",
            "method": "nearest",
            "predicted_integer": 15,
            "checkpoint": "T-300s",
        },
    ]
    groups = MODULE.match_recorded_baselines(records)
    assert groups["EHAM|T-60s|nearest"]["matched_candidate"]["n"] == 1
    assert groups["EHAM|T-300s|nearest"]["matched_candidate"]["n"] == 0
    assert groups["EHAM|T-300s|nearest"]["missing_recorded_baseline"] == 1


def test_ambiguous_initial_outcomes_are_not_selected_by_success(tmp_path: Path) -> None:
    path = tmp_path / "forecast.sqlite3"
    fixture_db(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO observations VALUES(3,'third','EPWA','METAR','2026-10-25T12:30:00+00:00',14,0,0,'{}','2026-10-25T12:33:00+00:00')"
        )
        conn.execute("INSERT INTO report_receipts VALUES(3,3,'2026-10-25T12:33:00+00:00')")
    with readonly(path) as conn:
        result = MODULE.audit_prospective(conn)
    assert not result["valid"]
    assert all("AMBIGUOUS_INITIAL_TEMPERATURE" in r["reasons"] for r in result["excluded"])


def test_early_correction_closes_target_before_later_initial(tmp_path: Path) -> None:
    path = tmp_path / "forecast.sqlite3"
    fixture_db(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO observations VALUES(3,'cor','EPWA','METAR','2026-10-25T12:30:00+00:00',13,0,0,?, '2026-10-25T12:28:00+00:00')",
            (json.dumps(dict(cor=True)),),
        )
        conn.execute("INSERT INTO report_receipts VALUES(3,3,'2026-10-25T12:28:00+00:00')")
    with readonly(path) as conn:
        result = MODULE.audit_prospective(conn)
    assert not result["valid"]
    assert all("TARGET_ALREADY_RECEIVED" in r["reasons"] for r in result["excluded"])


def test_censored_first_receipt_is_not_replaced_by_later_uncensored_copy(tmp_path: Path) -> None:
    path = tmp_path / "forecast.sqlite3"
    fixture_db(path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE observations SET startup_censored=1 WHERE id=2")
        conn.execute(
            "INSERT INTO observations VALUES(3,'2','EPWA','METAR','2026-10-25T12:30:00+00:00',13,0,0,'{}','2026-10-25T12:33:00+00:00')"
        )
        conn.execute("INSERT INTO report_receipts VALUES(3,3,'2026-10-25T12:33:00+00:00')")
    with readonly(path) as conn:
        result = MODULE.audit_prospective(conn)
    assert not result["valid"]
    assert all("CENSORED_REFERENCE_RECEIPT" in r["reasons"] for r in result["excluded"])
