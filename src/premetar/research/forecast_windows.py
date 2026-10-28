"""Pure, causal Open-Meteo forecast normalization and frozen research windows.

The caller durably records HTTP bytes before parsing. See official API docs:
https://open-meteo.com/en/docs . Request timezone=UTC, timeformat=unixtime,
temperature_unit=celsius and hourly=temperature_2m. Response generationtime_ms
is a computation duration, never a model run, issue or publication timestamp.
"""

import hashlib
import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

TIMEZONES = {
    "EDDM": "Europe/Berlin",
    "EHAM": "Europe/Amsterdam",
    "EPWA": "Europe/Warsaw",
    "EGLL": "Europe/London",
}
VERSION = "EXP0013-WINDOWS-v1"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("Expected timezone-aware UTC")
    return value.astimezone(UTC)


def _clock(value: str) -> datetime:
    return _utc(datetime.fromisoformat(value))


def metar_integer(value: float) -> int:
    """ICAO nearest integer with exact halves toward warmer, including negatives."""
    if not math.isfinite(value):
        raise ValueError("Non-finite temperature")
    return math.floor(value + 0.5)


def parse_forecast(payload: dict[str, Any], airport: str, received: datetime) -> dict[str, Any]:
    """Normalize only documented epoch-second temperatures; retain unknown clocks."""
    _utc(received)
    if airport not in TIMEZONES:
        raise ValueError("Unsupported airport")
    if payload.get("timezone") not in {"UTC", "GMT"} or payload.get("utc_offset_seconds") != 0:
        raise ValueError("Response must explicitly use UTC")
    units = payload.get("hourly_units")
    if (
        not isinstance(units, dict)
        or units.get("time") != "unixtime"
        or units.get("temperature_2m") != "°C"
    ):
        raise ValueError("Expected documented UTC epoch seconds and Celsius")
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        raise ValueError("Missing hourly forecast")
    times, temperatures = hourly.get("time"), hourly.get("temperature_2m")
    if (
        not isinstance(times, list)
        or not isinstance(temperatures, list)
        or not times
        or len(times) != len(temperatures)
    ):
        raise ValueError("Missing or mismatched forecast arrays")
    points: list[dict[str, Any]] = []
    missing: list[str] = []
    previous: datetime | None = None
    for stamp, temperature in zip(times, temperatures, strict=True):
        if (
            isinstance(stamp, bool)
            or not isinstance(stamp, (int, float))
            or not math.isfinite(stamp)
            or int(stamp) != stamp
        ):
            raise ValueError("Invalid epoch timestamp")
        try:
            valid = datetime.fromtimestamp(stamp, UTC)
        except (ValueError, OverflowError, OSError) as error:
            raise ValueError("Invalid epoch timestamp") from error
        if valid.minute or valid.second or valid.microsecond:
            raise ValueError("Forecast timestamp is not an hourly instant")
        if previous is not None and valid <= previous:
            raise ValueError("Forecast timestamps must be unique and increasing")
        previous = valid
        if temperature is None:
            missing.append(valid.isoformat())
            continue
        if (
            isinstance(temperature, bool)
            or not isinstance(temperature, (float, int))
            or not math.isfinite(temperature)
            or not -90 <= temperature <= 65
        ):
            raise ValueError("Invalid forecast temperature")
        points.append({"valid_time": valid.isoformat(), "temperature_c": float(temperature)})
    if not points:
        raise ValueError("No usable forecast temperatures")
    zone = ZoneInfo(TIMEZONES[airport])
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for point in points:
        local = _clock(point["valid_time"]).astimezone(zone)
        by_day[local.date().isoformat()].append(point)
    maxima: list[dict[str, Any]] = []
    for day, group in sorted(by_day.items()):
        local_start = datetime.fromisoformat(day).replace(tzinfo=zone)
        local_end = local_start + timedelta(days=1)
        start, end = local_start.astimezone(UTC), local_end.astimezone(UTC)
        expected = {
            (start + timedelta(hours=hour)).isoformat()
            for hour in range(int((end - start).total_seconds() // 3600))
        }
        actual = {point["valid_time"] for point in group}
        peak = max(point["temperature_c"] for point in group)
        complete = actual == expected
        maxima.append(
            {
                "local_date": day,
                "timezone": zone.key,
                "start_utc": start.isoformat(),
                "end_utc": end.isoformat(),
                "expected_hours": len(expected),
                "available_hours": len(actual),
                "complete": complete,
                "status": "COMPLETE_HOURLY_DAY" if complete else "INCOMPLETE_DAY",
                "temperature_c": peak,
                "valid_times": [
                    point["valid_time"] for point in group if point["temperature_c"] == peak
                ],
            }
        )
    return {
        "airport": airport,
        "provider": "open_meteo",
        "first_received": received.isoformat(),
        "issue_time": None,
        "publication_time": None,
        "model_run": None,
        "timestamp_status": "RECEIPT_KNOWN_PUBLICATION_AND_RUN_UNKNOWN",
        "points": points,
        "daily_maxima": maxima,
        "missing_valid_times": missing,
        "quality_flags": ["MISSING_FORECAST_TEMPERATURES"] if missing else [],
    }


def windows(forecast: dict[str, Any], created: datetime) -> list[dict[str, Any]]:
    """Freeze future windows only; retrospective windows never become prospective."""
    created = _utc(created)
    received = _clock(forecast["first_received"])
    if received > created:
        raise ValueError("Forecast unavailable at window creation")
    candidates: list[dict[str, Any]] = []
    points = forecast["points"]
    for before, after in zip(points, points[1:], strict=False):
        event = _clock(after["valid_time"])
        if event - _clock(before["valid_time"]) != timedelta(hours=1):
            continue
        old_integer = metar_integer(before["temperature_c"])
        new_integer = metar_integer(after["temperature_c"])
        if old_integer != new_integer:
            candidates.append(
                {
                    "kind": "FORECAST_TRANSITION",
                    "start": event - timedelta(minutes=10),
                    "end": event + timedelta(minutes=10),
                    "previous_integer": old_integer,
                    "target_integer": new_integer,
                    "event_time": event.isoformat(),
                }
            )
    for peak in forecast["daily_maxima"]:
        # A partial day maximum is not an adequate forecast of the daily Tmax.
        if not peak["complete"]:
            continue
        for value in peak["valid_times"]:
            event = _clock(value)
            candidates.append(
                {
                    "kind": "FORECAST_TMAX",
                    "start": event - timedelta(hours=1),
                    "end": event + timedelta(hours=1),
                    "temperature_c": peak["temperature_c"],
                    "event_time": value,
                    "local_date": peak["local_date"],
                }
            )
    result = []
    for candidate in candidates:
        if candidate["start"] <= received or candidate["start"] <= created:
            continue
        normalized = {
            **candidate,
            "start": candidate["start"].isoformat(),
            "end": candidate["end"].isoformat(),
            "forecast_received": received.isoformat(),
            "created_at": created.isoformat(),
            "airport": forecast["airport"],
            "version": VERSION,
        }
        key = "|".join(
            str(normalized[item])
            for item in ("airport", "kind", "start", "end", "forecast_received")
        )
        normalized["window_id"] = hashlib.sha256(key.encode()).hexdigest()
        result.append(normalized)
    return sorted(result, key=lambda item: (item["start"], item["kind"], item["window_id"]))
