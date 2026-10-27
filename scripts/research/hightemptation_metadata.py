"""Research-only market identity and local-clock reference extraction.

Current captured descriptions identify a market retrospectively. They never
establish that weather, forecasts or those rules were available at an older BUY.
"""

import hashlib
import json
import re
import sqlite3
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

IANA_SOURCE = "https://www.iana.org/time-zones"
CITY_TIMEZONES = {
    "amsterdam": "Europe/Amsterdam",
    "ankara": "Europe/Istanbul",
    "atlanta": "America/New_York",
    "austin": "America/Chicago",
    "beijing": "Asia/Shanghai",
    "buenos-aires": "America/Argentina/Buenos_Aires",
    "busan": "Asia/Seoul",
    "cape-town": "Africa/Johannesburg",
    "chengdu": "Asia/Shanghai",
    "chicago": "America/Chicago",
    "chongqing": "Asia/Shanghai",
    "dallas": "America/Chicago",
    "denver": "America/Denver",
    "guangzhou": "Asia/Shanghai",
    "helsinki": "Europe/Helsinki",
    "houston": "America/Chicago",
    "istanbul": "Europe/Istanbul",
    "jeddah": "Asia/Riyadh",
    "jinan": "Asia/Shanghai",
    "karachi": "Asia/Karachi",
    "kuala-lumpur": "Asia/Kuala_Lumpur",
    "london": "Europe/London",
    "los-angeles": "America/Los_Angeles",
    "lucknow": "Asia/Kolkata",
    "madrid": "Europe/Madrid",
    "manila": "Asia/Manila",
    "mexico-city": "America/Mexico_City",
    "miami": "America/New_York",
    "milan": "Europe/Rome",
    "moscow": "Europe/Moscow",
    "munich": "Europe/Berlin",
    "nyc": "America/New_York",
    "panama-city": "America/Panama",
    "paris": "Europe/Paris",
    "qingdao": "Asia/Shanghai",
    "san-francisco": "America/Los_Angeles",
    "sao-paulo": "America/Sao_Paulo",
    "seattle": "America/Los_Angeles",
    "shanghai": "Asia/Shanghai",
    "shenzhen": "Asia/Shanghai",
    "singapore": "Asia/Singapore",
    "taipei": "Asia/Taipei",
    "tel-aviv": "Asia/Jerusalem",
    "tokyo": "Asia/Tokyo",
    "toronto": "America/Toronto",
    "warsaw": "Europe/Warsaw",
    "wellington": "Pacific/Auckland",
    "wuhan": "Asia/Shanghai",
    "zhengzhou": "Asia/Shanghai",
}

MONTHS = {
    name: index
    for index, name in enumerate(
        (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ),
        1,
    )
}


def market_identity(slug: str) -> tuple[str, str, date | None]:
    match = re.match(
        r"^(highest|lowest)-temperature-in-(.+?)-on-([a-z]+)-(\d{1,2})-(\d{4})(?:-|$)",
        slug,
    )
    if not match:
        return "OTHER", "UNKNOWN", None
    extremum, city, month, day, year = match.groups()
    try:
        target = date(int(year), MONTHS[month], int(day))
    except (KeyError, ValueError):
        target = None
    return "TMAX" if extremum == "highest" else "TMIN", city, target


def day_bounds(day: date, timezone: str) -> tuple[datetime, datetime]:
    """Adjacent local midnights, not UTC start plus24hours."""
    zone = ZoneInfo(timezone)
    return (
        datetime.combine(day, time.min, zone).astimezone(UTC),
        datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(UTC),
    )


def station_from_rules(market: dict[str, Any]) -> tuple[str | None, str]:
    """Only explicit original station codes; never substitute a city airport."""
    description = str(market.get("description") or "")
    source = str(market.get("resolutionSource") or "")
    candidates: set[str] = set()
    urls = re.findall(r"https?://[^\s\"<>]+", source + " " + description)
    for url in urls:
        parts = urlsplit(url.rstrip(".,)"))
        for key in ("site", "ids"):
            for item in parse_qs(parts.query).get(key, []):
                if re.fullmatch(r"[A-Za-z][A-Za-z0-9]{3}", item):
                    candidates.add(item.upper())
        if "wunderground.com" in (parts.hostname or "") and "/history/daily/" in parts.path:
            code = parts.path.rstrip("/").split("/")[-1]
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9]{3}", code):
                candidates.add(code.upper())
    candidates.update(re.findall(r"Airport\s*\(([A-Z][A-Z0-9]{3})\)", description))
    if len(candidates) == 1:
        return next(iter(candidates)), "EXPLICIT_CAPTURED_RULE_REFERENCE"
    return None, "CONFLICTING_RULE_REFERENCES" if candidates else "NO_EXPLICIT_STATION_CODE"


def _tokens(market: dict[str, Any]) -> list[str]:
    field = "positionIds" if market.get("version") == "v2" else "clobTokenIds"
    raw = market.get(field) or []
    try:
        values = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return []
    return [str(value) for value in values] if isinstance(values, list) else []


def _rule_fields(market: dict[str, Any]) -> dict[str, Any]:
    description = str(market.get("description") or "")
    lower = description.lower()
    station, station_status = station_from_rules(market)
    unit = "F" if "degrees fahrenheit" in lower else "C" if "degrees celsius" in lower else None
    precision = (
        "T_GROUP_TENTHS_BODY_FALLBACK"
        if "hourly temperature remark" in lower
        else "DECLARED_WHOLE_UNIT"
        if "whole degrees" in lower
        else "UNKNOWN"
    )
    return {
        "reference_station": station,
        "station_status": station_status,
        "resolution_source": market.get("resolutionSource"),
        "temperature_unit": unit,
        "precision_policy": precision,
        "speci_policy": "EXCLUDED" if "speci" in lower and "does not count" in lower else "UNKNOWN",
        "correction_policy": "DESCRIBED_IN_CAPTURED_RULES"
        if "correct" in lower or "revision" in lower
        else "UNKNOWN",
        "description_sha256": hashlib.sha256(description.encode()).hexdigest(),
        "local_day_explicit": "local time" in lower or "local date" in lower,
        "rounding_policy": "HALF_TOWARD_WARMER" if "warmer" in lower else "UNKNOWN",
    }


def load_market_metadata(snapshot: Path) -> dict[str, dict[str, Any]]:
    """One row per traded token; missing historical identity remains explicit.

    ``timezone`` is a geographic city reference, not proof of that old contract's
    settlement convention. Exact station/rules are populated only for a captured
    matching condition and token. Earliest captured version is used; its receipt
    determines whether it was available at an individual trade.
    """
    connection = sqlite3.connect(snapshot.resolve().as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    try:
        trades = [
            json.loads(row[0])
            for row in connection.execute(
                "SELECT payload FROM events WHERE kind='TRADE' ORDER BY id"
            )
        ]
        markets: dict[str, tuple[dict[str, Any], str]] = {}
        version_hashes: dict[str, set[str]] = {}
        for encoded, received in connection.execute(
            "SELECT payload,received_at FROM events WHERE kind='MARKET' ORDER BY id"
        ):
            market = json.loads(encoded)
            condition = str(market.get("conditionId") or "")
            if not condition:
                continue
            markets.setdefault(condition, (market, received))
            version_hashes.setdefault(condition, set()).add(
                _rule_fields(market)["description_sha256"]
            )
    finally:
        connection.close()
    output: dict[str, dict[str, Any]] = {}
    for trade in trades:
        token = str(trade["token_id"])
        if token in output:
            continue
        kind, city, target = market_identity(str(trade.get("slug") or ""))
        timezone = CITY_TIMEZONES.get(city)
        entry: dict[str, Any] = {
            "token_id": token,
            "condition_id": trade["condition_id"],
            "city": city,
            "market_kind": kind,
            "market_date": target.isoformat() if target else None,
            "date_source": "TRADE_SLUG" if target else "UNKNOWN",
            "timezone": timezone,
            "timezone_status": "CITY_REFERENCE_ONLY" if timezone else "UNKNOWN",
            "timezone_reference": IANA_SOURCE if timezone else None,
            "reference_station": None,
            "station_status": "UNKNOWN_UNCAPTURED_MARKET",
            "metadata_available_at": None,
            "metadata_semantics": "MISSING_EXACT_MARKET_RULES",
            "temperature_unit": None,
            "precision_policy": "UNKNOWN",
            "resolution_source": None,
            "settlement_day_start_utc": None,
            "settlement_day_end_utc": None,
            "city_calendar_day_start_utc": None,
            "city_calendar_day_end_utc": None,
            "settlement_day_status": "UNVERIFIED",
            "description_sha256": None,
            "description_version_count": 0,
            "speci_policy": "UNKNOWN",
            "rounding_policy": "UNKNOWN",
            "correction_policy": "UNKNOWN",
        }
        if target and timezone:
            start, end = day_bounds(target, timezone)
            entry.update(
                city_calendar_day_start_utc=start.isoformat(),
                city_calendar_day_end_utc=end.isoformat(),
            )
        captured = markets.get(str(trade["condition_id"]))
        if captured:
            market, received = captured
            if token in _tokens(market):
                entry.update(_rule_fields(market))
                entry.update(
                    metadata_available_at=received,
                    metadata_semantics="RETROSPECTIVE_IDENTITY_UNLESS_CAPTURE_PRECEDES_TRADE",
                    description_version_count=len(version_hashes[str(trade["condition_id"])]),
                )
                # Local-day bounds become settlement bounds only when rules say local.
                if entry["local_day_explicit"] and timezone and target:
                    entry.update(
                        settlement_day_start_utc=entry["city_calendar_day_start_utc"],
                        settlement_day_end_utc=entry["city_calendar_day_end_utc"],
                        settlement_day_status="EXPLICIT_LOCAL_RULE_WITH_CITY_TIMEZONE_REFERENCE",
                    )
            else:
                entry["station_status"] = "TOKEN_CONDITION_MAPPING_MISMATCH"
        output[token] = entry
    return output


def trade_local_context(trade: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    """Display local source time without inventing causal forecast or weather data."""
    source = datetime.fromisoformat(str(trade["source_trade_timestamp"]).replace("Z", "+00:00"))
    if source.tzinfo is None or source.utcoffset() is None:
        raise ValueError("Naive trade source time")
    zone = metadata.get("timezone")
    captured = metadata.get("metadata_available_at")
    local = source.astimezone(ZoneInfo(zone)) if zone else None
    return {
        **metadata,
        "trade_id": trade["trade_id"],
        "source_trade_timestamp": source.astimezone(UTC).isoformat(),
        "local_trade_time": local.isoformat() if local else None,
        "local_hour": local.hour if local else None,
        "within_14_16_local": 14 <= local.hour < 16 if local else None,
        "exact_rules_captured_by_source_time": datetime.fromisoformat(captured) <= source
        if captured
        else False,
        "forecast_tmax_time_available_at_trade": None,
        "observed_tmax_time_retrospective": None,
        "tmax_timing_status": "NO_CAUSAL_FORECAST_ARCHIVE",
    }
