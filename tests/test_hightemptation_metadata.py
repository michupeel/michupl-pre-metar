"""Synthetic market identities; no live queries or historical weather inventions."""

import json
import sqlite3
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.research.hightemptation_metadata import (  # noqa: E402
    CITY_TIMEZONES,
    day_bounds,
    load_market_metadata,
    market_identity,
    station_from_rules,
    trade_local_context,
)


def test_warsaw_fallback_day_has_25_hours_and_exclusive_boundary() -> None:
    start, end = day_bounds(date(2026, 10, 25), "Europe/Warsaw")
    assert start == datetime(2026, 10, 24, 22, tzinfo=UTC)
    assert end == datetime(2026, 10, 25, 23, tzinfo=UTC)
    assert (end - start).total_seconds() == 25 * 3600


def test_warsaw_spring_day_has_23_hours() -> None:
    start, end = day_bounds(date(2026, 3, 29), "Europe/Warsaw")
    assert (end - start).total_seconds() == 23 * 3600


def test_repeated_local_hour_keeps_offsets_distinct() -> None:
    zone = ZoneInfo("Europe/Warsaw")
    first = datetime(2026, 10, 25, 0, 30, tzinfo=UTC).astimezone(zone)
    second = datetime(2026, 10, 25, 1, 30, tzinfo=UTC).astimezone(zone)
    assert first.hour == second.hour == 2
    assert first.isoformat() != second.isoformat()


@pytest.mark.parametrize("zone", sorted(set(CITY_TIMEZONES.values())))
def test_explicit_geographic_reference_is_valid_iana_zone(zone: str) -> None:
    assert ZoneInfo(zone).key == zone


def test_market_kind_city_and_target_date_are_independent_from_receipt() -> None:
    assert market_identity("highest-temperature-in-mexico-city-on-october-27-2026-20c") == (
        "TMAX",
        "mexico-city",
        date(2026, 10, 27),
    )
    assert market_identity("lowest-temperature-in-london-on-october-25-2026-8c") == (
        "TMIN",
        "london",
        date(2026, 10, 25),
    )
    assert market_identity("highest-temperature-in-london-on-february-31-2026") == (
        "TMAX",
        "london",
        None,
    )
    assert market_identity("btc-updown") == ("OTHER", "UNKNOWN", None)


@pytest.mark.parametrize(
    "source,expected",
    [
        ("https://www.weather.gov/wrh/timeseries?site=eglc", "EGLC"),
        ("https://aviationweather.gov/api/data/metar?ids=LTAC&format=raw", "LTAC"),
        ("https://www.wunderground.com/history/daily/tw/taipei/RCSS", "RCSS"),
    ],
)
def test_station_comes_from_actual_reference_url(source: str, expected: str) -> None:
    assert station_from_rules({"resolutionSource": source}) == (
        expected,
        "EXPLICIT_CAPTURED_RULE_REFERENCE",
    )


def test_station_ambiguity_remains_unknown() -> None:
    result = station_from_rules(
        {
            "resolutionSource": "https://www.weather.gov/?site=eglc",
            "description": "https://www.weather.gov/?site=egll",
        }
    )
    assert result == (None, "CONFLICTING_RULE_REFERENCES")
    assert station_from_rules({"description": "London weather"})[0] is None


def test_captured_current_rules_do_not_backfill_asof_or_guess_heathrow(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE events(id INTEGER PRIMARY KEY,kind TEXT,received_at TEXT,payload TEXT)"
    )
    trade = {
        "trade_id": "buy",
        "token_id": "123",
        "condition_id": "condition",
        "slug": "highest-temperature-in-london-on-october-25-2026-10c",
        "source_trade_timestamp": "2026-10-25T11:00:00+00:00",
    }
    other = {**trade, "trade_id": "other", "token_id": "456", "condition_id": "uncaptured"}
    market = {
        "conditionId": "condition",
        "clobTokenIds": '["123"]',
        "description": "Highest temperature in degrees Celsius. Whole degrees Celsius. https://www.weather.gov/?site=eglc",
        "resolutionSource": "https://www.weather.gov/?site=eglc",
    }
    for kind, payload in (("TRADE", trade), ("TRADE", other), ("MARKET", market)):
        conn.execute(
            "INSERT INTO events(kind,received_at,payload) VALUES(?,?,?)",
            (kind, "2026-10-27T09:00:00+00:00", json.dumps(payload)),
        )
    conn.commit()
    conn.close()
    before = path.read_bytes()
    rows = load_market_metadata(path)
    assert rows["123"]["reference_station"] == "EGLC"
    assert rows["123"]["timezone"] == "Europe/London"
    assert rows["123"]["settlement_day_start_utc"] is None
    assert rows["456"]["reference_station"] is None
    assert rows["456"]["timezone_status"] == "CITY_REFERENCE_ONLY"
    context = trade_local_context(trade, rows["123"])
    assert context["local_hour"] == 11
    assert context["exact_rules_captured_by_source_time"] is False
    assert context["forecast_tmax_time_available_at_trade"] is None
    assert context["observed_tmax_time_retrospective"] is None
    assert path.read_bytes() == before


def test_explicit_local_rules_allow_calendar_bounds_but_not_forecast_claim(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE events(id INTEGER PRIMARY KEY,kind TEXT,received_at TEXT,payload TEXT)"
    )
    trade = {
        "trade_id": "x",
        "token_id": "1",
        "condition_id": "c",
        "slug": "highest-temperature-in-warsaw-on-october-25-2026-10c",
    }
    market = {
        "conditionId": "c",
        "clobTokenIds": ["1"],
        "description": "Highest temperature on the local date in degrees Celsius (EPWA).",
    }
    for kind, value in (("TRADE", trade), ("MARKET", market)):
        conn.execute(
            "INSERT INTO events(kind,received_at,payload) VALUES(?,?,?)",
            (kind, "2026-10-24T09:00:00+00:00", json.dumps(value)),
        )
    conn.commit()
    conn.close()
    row = load_market_metadata(path)["1"]
    assert row["settlement_day_start_utc"] == "2026-10-24T22:00:00+00:00"
    assert row["settlement_day_end_utc"] == "2026-10-25T23:00:00+00:00"
