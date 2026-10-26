"""Synthetic normalized records test as-of safeguards; no live DB is accessed."""

import json
import sqlite3
import sys
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.research.early_metar_data import (  # noqa: E402
    asof_eligible,
    calibration,
    clock,
    latest,
    load_dataset,
    metadata_at,
    previous_reference,
    reference_series,
    selection_at,
)


def reference(temperature: int, received: str, *, correction: bool = False) -> dict:
    return dict(
        report_identity=received,
        report_type="METAR",
        correction=correction,
        observation_time_utc="2026-10-26T12:00:00Z",
        first_received_utc=received,
        temperature_c=temperature,
    )


def test_future_conflicting_initial_does_not_erase_earlier_reference() -> None:
    references, excluded = reference_series(
        [reference(10, "2026-10-26T12:02:00Z"), reference(11, "2026-10-26T12:08:00Z")]
    )
    assert excluded == {"AMBIGUOUS_INITIAL_TEMPERATURE": 1}
    assert len(references) == 1
    assert references[0]["temperature_c"] == 10
    assert references[0]["_ambiguous_from"] == clock("2026-10-26T12:08:00Z")
    assert (
        previous_reference(references, clock("2026-10-26T12:30:00Z"), clock("2026-10-26T12:07:59Z"))
        is references[0]
    )
    assert (
        previous_reference(references, clock("2026-10-26T12:30:00Z"), clock("2026-10-26T12:08:00Z"))
        is None
    )


def test_earlier_cor_closes_window_without_revealing_later_initial_outcome() -> None:
    references, _ = reference_series(
        [
            reference(10, "2026-10-26T12:02:00Z", correction=True),
            reference(11, "2026-10-26T12:04:00Z"),
        ]
    )
    assert references[0]["_closure"] == clock("2026-10-26T12:02:00Z")
    assert references[0]["_received"] == clock("2026-10-26T12:04:00Z")
    assert (
        previous_reference(references, clock("2026-10-26T12:30:00Z"), clock("2026-10-26T12:03:00Z"))
        is None
    )


@pytest.mark.parametrize("temperature", [float("nan"), float("inf"), True, 10.5, "10"])
def test_reference_temperature_cannot_be_truncated_or_nonfinite(temperature: object) -> None:
    r = {**reference(10, "2026-10-26T12:02:00Z"), "temperature_c": temperature}
    references, excluded = reference_series([r])
    assert references == []
    assert excluded == {"INVALID_INITIAL_TEMPERATURE": 1}


def test_earliest_any_version_censoring_is_retained() -> None:
    cor = {**reference(10, "2026-10-26T12:02:00Z", correction=True), "startup_censored": True}
    initial = {**reference(10, "2026-10-26T12:03:00Z"), "startup_censored": False}
    references, _ = reference_series([cor, initial])
    assert references[0]["_closure_censored"] is True
    assert references[0]["_closure"] == clock("2026-10-26T12:02:00Z")


def pairs(start: str = "2026-10-26T06:00:00Z") -> list[dict]:
    beginning = clock(start)
    return [
        dict(
            _event=beginning + timedelta(minutes=30 * i),
            _received=beginning + timedelta(minutes=30 * i + 2),
            offset_midpoint_c=2,
            report_identity=str(i),
        )
        for i in range(12)
    ]


def test_calibration_has_causal_target_receipt_and_window_guards() -> None:
    at = clock("2026-10-26T18:00:00Z")
    sensor = {"pairs": pairs()}
    sensor["pairs"].extend(
        [
            dict(
                _event=at,
                _received=at - timedelta(seconds=1),
                offset_midpoint_c=999,
                report_identity="target",
            ),
            dict(
                _event=at - timedelta(minutes=1),
                _received=at,
                offset_midpoint_c=999,
                report_identity="equal_receipt",
            ),
            dict(
                _event=at - timedelta(minutes=2),
                _received=at + timedelta(seconds=1),
                offset_midpoint_c=999,
                report_identity="future_receipt",
            ),
        ]
    )
    result = calibration(sensor, "CAL-2", at, at)
    assert result is not None
    assert result["calibration_n"] == 12 and result["offset_c"] == 2
    assert result["offset_lower_c"] == 1.5 and result["offset_upper_c"] == 2.5
    assert calibration({"pairs": pairs()}, "CAL-2", at, at + timedelta(microseconds=1)) is None
    assert calibration({"pairs": pairs()}, "CAL-1", at, at + timedelta(microseconds=1)) is not None
    assert calibration({"pairs": []}, "CAL-0", at, at)["offset_c"] == 0
    with pytest.raises(ValueError):
        calibration(sensor, "CAL-99", at, at)


@pytest.mark.parametrize("known_clock", ["_ambiguous_from", "_pws_conflict_from"])
def test_calibration_removes_contradicted_pairs_only_when_known(known_clock: str) -> None:
    at = clock("2026-10-26T18:00:00Z")
    history = pairs()
    history[0][known_clock] = at + timedelta(minutes=1)
    sensor = {"pairs": history}
    assert calibration(sensor, "CAL-1", at, at) is not None
    assert calibration(sensor, "CAL-1", at, at + timedelta(minutes=1)) is None


def connection(*, bad_second_unit: bool = False) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
    CREATE TABLE pws_airports(icao TEXT,data_json TEXT);
    CREATE TABLE raw_payloads(id TEXT,run_id TEXT);
    CREATE TABLE pws_arrivals(observation_id TEXT,received_at TEXT,startup_censored INTEGER,raw_id TEXT);
    CREATE TABLE observations(id INTEGER,identity TEXT,event_time TEXT,station_icao TEXT,product_type TEXT,temperature_c REAL,data_json TEXT,source TEXT,raw_text TEXT,startup_censored INTEGER,coverage_gap INTEGER);
    CREATE TABLE report_receipts(observation_id INTEGER,collector_receive_time TEXT);
    CREATE TABLE pws_stations(station_id TEXT,provider TEXT,provider_station_id TEXT,data_json TEXT);
    CREATE TABLE pws_sensors(sensor_id TEXT,station_id TEXT,provider_sensor_id TEXT,data_json TEXT);
    CREATE TABLE pws_airport_stations(station_id TEXT,airport_icao TEXT,distance_km REAL);
    CREATE TABLE pws_discoveries(station_id TEXT,airport_icao TEXT,at TEXT,data_json TEXT,id INTEGER);
    CREATE TABLE pws_selections(station_id TEXT,airport_icao TEXT,created_at TEXT,id INTEGER,selected INTEGER);
    CREATE TABLE pws_observations(id TEXT,sensor_id TEXT,observation_time TEXT,first_receive_time TEXT,temperature_c REAL,evidence_class TEXT,data_json TEXT);
    """)
    location = dict(latitude=52.165, longitude=20.967, exposure="outdoor", mobile=False)
    for airport in ("EDDM", "EHAM", "EPWA", "EGLL"):
        conn.execute("INSERT INTO pws_airports VALUES(?,?)", (airport, json.dumps(location)))
    conn.execute(
        "INSERT INTO pws_stations VALUES(?,?,?,?)",
        ("opensensemap:box", "opensensemap", "box", json.dumps(location)),
    )
    conn.execute(
        "INSERT INTO pws_sensors VALUES(?,?,?,?)",
        ("sensor", "opensensemap:box", "temperature", json.dumps(dict(phenomenon="temperature"))),
    )
    conn.execute("INSERT INTO pws_airport_stations VALUES(?,?,?)", ("opensensemap:box", "EPWA", 0))
    conn.execute(
        "INSERT INTO pws_discoveries VALUES(?,?,?,?,?)",
        ("opensensemap:box", "EPWA", "2026-10-26T11:00:00Z", json.dumps(location), 1),
    )
    conn.execute(
        "INSERT INTO pws_selections VALUES(?,?,?,?,?)",
        ("opensensemap:box", "EPWA", "2026-10-26T11:00:00Z", 1, 0),
    )
    conn.execute(
        "INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            1,
            "ref",
            "2026-10-26T12:00:00Z",
            "EPWA",
            "METAR",
            10,
            "{}",
            "synthetic",
            "SYNTHETIC",
            0,
            0,
        ),
    )
    conn.execute("INSERT INTO report_receipts VALUES(?,?)", (1, "2026-10-26T12:00:30Z"))
    for identity, received, temperature, flags in [
        ("first", "2026-10-26T12:00:10Z", 10, []),
        ("duplicate", "2026-10-26T12:00:20Z", 10, []),
        ("conflicting", "2026-10-26T12:01:00Z", 11, ["CONFLICTING_DUPLICATE"]),
    ]:
        value = dict(
            provider_sensor_id="temperature",
            raw_unit="unknown" if bad_second_unit and identity == "conflicting" else "°C",
            quality_flags=flags,
            timestamp_provenance="SENSOR_MEASUREMENT_TIME",
            timestamp_semantics_verified=True,
        )
        conn.execute(
            "INSERT INTO pws_observations VALUES(?,?,?,?,?,?,?)",
            (
                identity,
                "sensor",
                "2026-10-26T12:00:00Z",
                received,
                temperature,
                "REALTIME_CAPTURED",
                json.dumps(value),
            ),
        )
        conn.execute("INSERT INTO raw_payloads VALUES(?,?)", (identity, "synthetic"))
        conn.execute("INSERT INTO pws_arrivals VALUES(?,?,?,?)", (identity, received, 0, identity))
    return conn


def test_flagged_late_conflict_is_known_only_after_real_receipt() -> None:
    with connection() as conn:
        data = load_dataset(conn, clock("2026-10-26T12:03:00Z"))
    sensor = data["EPWA"]["sensors"]["sensor"]
    assert len(sensor["readings"]) == 1
    assert sensor["readings"][0]["id"] == "first"
    assert sensor["readings"][0]["_received"] == clock("2026-10-26T12:00:10Z")
    assert sensor["conflicts"][clock("2026-10-26T12:00:00Z")] == clock("2026-10-26T12:01:00Z")
    assert latest(sensor, clock("2026-10-26T12:00:59Z"))["temperature_c"] == 10
    assert latest(sensor, clock("2026-10-26T12:01:00Z")) is None
    assert sensor["pairs"][0]["_pws_conflict_from"] == clock("2026-10-26T12:01:00Z")


def test_other_invalidity_cannot_supply_trusted_conflict_evidence() -> None:
    with connection(bad_second_unit=True) as conn:
        sensor = load_dataset(conn, clock("2026-10-26T12:03:00Z"))["EPWA"]["sensors"]["sensor"]
    assert sensor["conflicts"] == {}
    assert latest(sensor, clock("2026-10-26T12:01:00Z")) is not None


def test_historical_metadata_is_required_but_selection_is_annotation_only() -> None:
    with connection(bad_second_unit=True) as conn:
        sensor = load_dataset(conn, clock("2026-10-26T12:03:00Z"))["EPWA"]["sensors"]["sensor"]
    at = clock("2026-10-26T12:00:30Z")
    row = sensor["readings"][0]
    assert selection_at(sensor, at)["selected"] == 0
    assert asof_eligible(sensor, row, at)
    assert metadata_at(sensor, clock("2026-10-26T10:59:59Z")) is None
    sensor["metadata_times"] = [clock("2026-10-26T12:00:31Z")]
    assert not asof_eligible(sensor, row, at)
    sensor["metadata_times"] = [clock("2026-10-26T11:00:00Z")]
    sensor["metadata"][0]["exposure"] = "indoor"
    assert not asof_eligible(sensor, row, at)
