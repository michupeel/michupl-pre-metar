"""Synthetic clocks and stored-response-shaped records; never represent live results."""

import json
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from premetar.pws.daily_time import local_day_bounds
from premetar.pws.repository import SCHEMA
from premetar.pws.sensor_history import (
    compare,
    history_snapshot,
    split_series,
    summarize,
    write_report,
)


def connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    conn.executescript("""CREATE TABLE observations(id TEXT,identity TEXT,event_time TEXT,station_icao TEXT,product_type TEXT,temperature_c REAL,data_json TEXT,source TEXT,raw_text TEXT);
    CREATE TABLE report_receipts(observation_id TEXT,collector_receive_time TEXT);""")
    conn.execute(
        "INSERT INTO pws_stations VALUES(?,?,?,?,?,?)",
        (
            "opensensemap:box",
            "opensensemap",
            "box",
            "2026-10-25",
            "2026-10-25",
            json.dumps(dict(latitude=52.16, longitude=20.98, exposure="outdoor")),
        ),
    )
    conn.execute(
        "INSERT INTO pws_airports VALUES(?,?)",
        ("EPWA", json.dumps(dict(latitude=52.1657, longitude=20.9671))),
    )
    conn.execute("INSERT INTO pws_airport_stations VALUES(?,?,?)", ("opensensemap:box", "EPWA", 1))
    for sensor in ("one", "two"):
        conn.execute(
            "INSERT INTO pws_sensors VALUES(?,?,?,?)",
            (
                "opensensemap:box:" + sensor,
                "opensensemap:box",
                sensor,
                json.dumps(dict(phenomenon="temperature", sensor_type="synthetic thermometer")),
            ),
        )
    return conn


def insert(
    conn: sqlite3.Connection,
    ident: str,
    event: str,
    received: str,
    value: float,
    sensor: str = "one",
) -> None:
    data = dict(
        raw_temperature=str(value),
        raw_unit="C",
        source_precision=0.1,
        quality_flags=[],
        timestamp_provenance="SENSOR_MEASUREMENT_TIME",
        timestamp_semantics_verified=True,
    )
    conn.execute(
        "INSERT INTO pws_observations VALUES(?,?,?,?,?,?,?,?)",
        (
            ident,
            "opensensemap:box:" + sensor,
            event,
            None,
            value,
            received,
            "REALTIME_CAPTURED",
            json.dumps(data),
        ),
    )


def test_fallback_boundaries_and_fold_are_distinct() -> None:
    start, end = local_day_bounds(date(2026, 10, 25), "Europe/Warsaw")
    assert start == datetime(2026, 10, 24, 22, tzinfo=UTC)
    assert end == datetime(2026, 10, 25, 23, tzinfo=UTC)
    assert (end - start).total_seconds() == 25 * 3600
    with connection() as conn:
        insert(conn, "a", "2026-10-25T00:30:00+00:00", "2026-10-25T00:30:10+00:00", 10)
        insert(conn, "b", "2026-10-25T01:30:00+00:00", "2026-10-25T01:30:10+00:00", 11)
        result = history_snapshot(conn, "box", date(2026, 10, 25))
    events = result["observations"]
    assert len(events) == 2
    assert events[0]["measurement_time_local"].endswith("02:30:00+02:00")
    assert events[1]["measurement_time_local"].endswith("02:30:00+01:00")


def test_empty_export(tmp_path: Path) -> None:
    with connection() as conn:
        result = history_snapshot(conn, "box", date(2026, 10, 25))
    paths = write_report(result, tmp_path)
    assert result["observations"] == []
    assert Path(paths["csv"]).read_text(encoding="utf-8").startswith("measurement_time_utc")
    assert "Valid unique measurements: **0**" in Path(paths["markdown"]).read_text(encoding="utf-8")


def test_distinct_instruments_duplicate_and_conflicting_values() -> None:
    event = "2026-10-25T12:00:00+00:00"
    received = "2026-10-25T12:00:20+00:00"
    with connection() as conn:
        insert(conn, "a", event, received, 10)
        insert(conn, "duplicate", event, received, 10)
        insert(conn, "other", event, received, 12, "two")
        result = history_snapshot(conn, "box", date(2026, 10, 25))
        assert len(result["observations"]) == 2
        assert result["summaries"]["opensensemap:box:two"]["mean_c"] == 12
        insert(conn, "conflict", event, received, 11)
        result = history_snapshot(conn, "box", date(2026, 10, 25))
        assert len(result["observations"]) == 1
        assert len(result["excluded"]) == 3


def reading(event: str, received: str, value: float = 18.2) -> dict[str, Any]:
    return dict(
        observation_id="a",
        sensor_id="s",
        station_id="station",
        provider="opensensemap",
        raw_unit="C",
        measurement_time_utc=event,
        collector_first_receive_time=received,
        temperature_c=value,
        timestamp_provenance="SENSOR_MEASUREMENT_TIME",
        timestamp_semantics_verified=True,
        evidence_class="REALTIME_CAPTURED",
        observation_age_seconds=10,
    )


def test_quantized_agreement_and_delayed_availability() -> None:
    report = dict(
        observation_time_utc="2026-10-25T12:00:00+00:00",
        first_received_utc="2026-10-25T12:02:00+00:00",
        temperature_c=18,
        report_type="METAR",
        correction=False,
    )
    after = reading("2026-10-25T12:00:20+00:00", "2026-10-25T12:03:00+00:00")
    result = compare([after], [report])[0]
    assert result["interval_aware_error"] == 0
    assert result["before_receipt_input_id"] is None
    assert result["pre_observation_input_id"] is None
    before = reading("2026-10-25T11:59:20+00:00", "2026-10-25T11:59:30+00:00")
    result = compare([before, after], [report])[0]
    assert result["pre_observation_input_id"] == "a"
    assert result["availability_phase"] == "PRE_OBSERVATION"
    assert result["prospective_prediction_claim"] is False


def test_post_observation_is_separate() -> None:
    report = dict(
        observation_time_utc="2026-10-25T12:00:00+00:00",
        first_received_utc="2026-10-25T12:02:00+00:00",
        temperature_c=18,
        report_type="METAR",
        correction=False,
    )
    item = reading("2026-10-25T12:00:20+00:00", "2026-10-25T12:00:40+00:00")
    result = compare([item], [report])[0]
    assert result["availability_phase"] == "POST_OBSERVATION_PRE_RECEIPT"
    assert result["pre_observation_input_id"] is None


def test_metar_cycles_without_valid_sensor_data_remain_explicit() -> None:
    report = dict(
        observation_time_utc="2026-10-25T12:00:00+00:00",
        first_received_utc="2026-10-25T12:02:00+00:00",
        temperature_c=18,
        report_type="METAR",
        correction=False,
    )
    output = compare([], [report], {"empty-one", "empty-two"})
    assert len(output) == 2
    assert {r["sensor_id"] for r in output} == {"empty-one", "empty-two"}
    assert all(
        r["nearest_pws_temperature"] is None
        and r["interval_aware_error"] is None
        and r["before_receipt_input_id"] is None
        and r["availability_phase"] == "NO_ELIGIBLE_INPUT"
        for r in output
    )
    mixed = compare(
        [reading("2026-10-25T11:59:20+00:00", "2026-10-25T11:59:30+00:00")],
        [report],
        {"s", "empty"},
    )
    assert len(mixed) == 2
    assert (
        next(r for r in mixed if r["sensor_id"] == "empty")["nearest_pws_measurement_time"] is None
    )


def test_day_exclusive_end_and_stale_receipt_exclusion() -> None:
    with connection() as conn:
        insert(conn, "included", "2026-10-25T22:59:00+00:00", "2026-10-25T22:59:20+00:00", 10)
        insert(conn, "end", "2026-10-25T23:00:00+00:00", "2026-10-25T23:00:10+00:00", 11)
        insert(conn, "stale", "2026-10-25T12:00:00+00:00", "2026-10-25T12:10:00+00:00", 11)
        result = history_snapshot(conn, "box", date(2026, 10, 25))
    assert len(result["observations"]) == 1
    assert len(result["excluded"]) == 1


def test_chart_segments_do_not_bridge_long_gap() -> None:
    items = [
        reading("2026-10-25T12:00:00+00:00", "2026-10-25T12:00:10+00:00"),
        reading("2026-10-25T12:05:00+00:00", "2026-10-25T12:05:10+00:00"),
        reading("2026-10-25T13:00:00+00:00", "2026-10-25T13:00:10+00:00"),
    ]
    assert [len(s) for s in split_series(items)] == [2, 1]
    assert summarize(items)["largest_gap_seconds"] == 3300


def test_transition_first_signal_uses_earliest_receipt_not_oldest_measurement() -> None:
    with connection() as conn:
        insert(
            conn, "older-delayed", "2026-10-25T12:10:00+00:00", "2026-10-25T12:14:00+00:00", 18.2
        )
        insert(
            conn,
            "newer-first-received",
            "2026-10-25T12:11:00+00:00",
            "2026-10-25T12:11:10+00:00",
            18.2,
        )
        for ident, event, received, temperature in (
            ("previous", "2026-10-25T12:00:00+00:00", "2026-10-25T12:02:00+00:00", 17),
            ("target", "2026-10-25T12:30:00+00:00", "2026-10-25T12:32:00+00:00", 18),
        ):
            conn.execute(
                "INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?)",
                (ident, ident, event, "EPWA", "METAR", temperature, "{}", "synthetic", ident),
            )
            conn.execute("INSERT INTO report_receipts VALUES(?,?)", (ident, received))
        result = history_snapshot(conn, "box", date(2026, 10, 25))
    transition = next(t for t in result["transitions"] if t["sensor_id"] == "opensensemap:box:one")
    assert transition["matching_observation_id"] == "newer-first-received"
    assert transition["first_matching_measurement"] == "2026-10-25T12:11:00+00:00"
    assert transition["first_matching_receipt"] == "2026-10-25T12:11:10+00:00"
    assert transition["analysis"] == "RETROSPECTIVE_EXPLORATORY_NOT_LIVE_PREDICTION"


def test_unknown_station_does_not_fallback() -> None:
    with connection() as conn, pytest.raises(ValueError, match="Station not found"):
        history_snapshot(conn, "missing", date(2026, 10, 25))
