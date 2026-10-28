"""Synthetic documented epoch schemas; no network or production DB mutations."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from premetar.research.forecast_windows import metar_integer, parse_forecast, windows


def payload(start: datetime, hours: int = 24) -> dict[str, Any]:
    return {
        "timezone": "GMT",
        "utc_offset_seconds": 0,
        "generationtime_ms": 7.2,
        "hourly_units": {"time": "unixtime", "temperature_2m": "°C"},
        "hourly": {
            "time": [int((start + timedelta(hours=i)).timestamp()) for i in range(hours)],
            "temperature_2m": [10.0] * hours,
        },
    }


@pytest.mark.parametrize(
    ("value", "expected"), [(-2.5, -2), (-1.5, -1), (-0.5, 0), (0.5, 1), (1.49, 1)]
)
def test_rounding_ties_warmer(value: float, expected: int) -> None:
    assert metar_integer(value) == expected


def test_publication_and_run_unknown_not_generation_duration() -> None:
    start = datetime(2026, 10, 28, tzinfo=UTC)
    result = parse_forecast(payload(start), "EPWA", start)
    assert result["publication_time"] is result["issue_time"] is result["model_run"] is None
    assert result["points"][0] == {"valid_time": start.isoformat(), "temperature_c": 10.0}
    assert not result["daily_maxima"][0]["complete"]


@pytest.mark.parametrize(
    ("start", "hours"),
    [
        (datetime(2026, 10, 24, 22, tzinfo=UTC), 25),
        (datetime(2026, 3, 28, 23, tzinfo=UTC), 23),
    ],
)
def test_warsaw_real_dst_calendar_day_and_all_tied_maxima(start: datetime, hours: int) -> None:
    result = parse_forecast(payload(start, hours), "EPWA", start - timedelta(days=1))
    maxima = result["daily_maxima"]
    assert len(maxima) == 1
    assert maxima[0]["complete"]
    assert maxima[0]["expected_hours"] == hours
    assert len(maxima[0]["valid_times"]) == hours
    assert result["points"][1]["valid_time"] != result["points"][2]["valid_time"]


@pytest.mark.parametrize("change", ["missing", "duplicate", "unordered", "fraction", "bool"])
def test_invalid_times_rejected(change: str) -> None:
    start = datetime(2026, 10, 28, tzinfo=UTC)
    source = payload(start)
    if change == "missing":
        del source["hourly"]["time"]
    elif change == "duplicate":
        source["hourly"]["time"][1] = source["hourly"]["time"][0]
    elif change == "unordered":
        source["hourly"]["time"].reverse()
    elif change == "fraction":
        source["hourly"]["time"][0] += 0.5
    else:
        source["hourly"]["time"][0] = True
    with pytest.raises(ValueError):
        parse_forecast(source, "EPWA", start)


@pytest.mark.parametrize("temperature", [float("nan"), float("inf"), -91, 66, "10", True])
def test_invalid_temperature_rejected(temperature: Any) -> None:
    start = datetime(2026, 10, 28, tzinfo=UTC)
    source = payload(start)
    source["hourly"]["temperature_2m"][0] = temperature
    with pytest.raises(ValueError):
        parse_forecast(source, "EPWA", start)


@pytest.mark.parametrize("field", ["timezone", "utc_offset_seconds", "units"])
def test_ambiguous_timezone_or_unit_rejected(field: str) -> None:
    start = datetime(2026, 10, 28, tzinfo=UTC)
    source = payload(start)
    if field == "timezone":
        source["timezone"] = "Europe/Warsaw"
    elif field == "units":
        source["hourly_units"]["time"] = "iso8601"
    else:
        del source[field]
    with pytest.raises(ValueError):
        parse_forecast(source, "EPWA", start)


def test_null_temperature_skipped_and_not_a_complete_day_or_transition() -> None:
    start = datetime(2026, 10, 27, 23, tzinfo=UTC)
    source = payload(start)
    source["hourly"]["temperature_2m"][1] = None
    source["hourly"]["temperature_2m"][2] = 12
    result = parse_forecast(source, "EPWA", start - timedelta(days=1))
    assert len(result["points"]) == 23
    assert result["quality_flags"] == ["MISSING_FORECAST_TEMPERATURES"]
    assert not result["daily_maxima"][0]["complete"]
    found = windows(result, start - timedelta(hours=2))
    assert all(row["kind"] != "FORECAST_TMAX" for row in found)
    assert not any(row["event_time"] == (start + timedelta(hours=2)).isoformat() for row in found)


def test_windows_frozen_only_before_start_no_backdating() -> None:
    start = datetime(2026, 10, 28, tzinfo=UTC)
    source = payload(start)
    source["hourly"]["temperature_2m"][1:3] = [11, 12]
    result = parse_forecast(source, "EPWA", start)
    found = windows(result, start + timedelta(minutes=51))
    assert all(
        datetime.fromisoformat(row["start"]) > start + timedelta(minutes=51) for row in found
    )
    assert not any(row["event_time"] == (start + timedelta(hours=1)).isoformat() for row in found)
    assert any(row["event_time"] == (start + timedelta(hours=2)).isoformat() for row in found)
    assert found == windows(deepcopy(result), start + timedelta(minutes=51))
    with pytest.raises(ValueError, match="unavailable"):
        windows(result, start - timedelta(seconds=1))


def test_naive_receipt_rejected() -> None:
    start = datetime(2026, 10, 28, tzinfo=UTC)
    with pytest.raises(ValueError, match="UTC"):
        parse_forecast(payload(start), "EPWA", datetime(2026, 10, 28))
