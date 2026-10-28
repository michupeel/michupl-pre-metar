"""Causal display transformations. Original observations and receipt clocks stay distinct."""

import json
import math
import re
import threading
import time
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from premetar.model import icao_round_temperature
from premetar.pws.daily_time import local_day_bounds
from premetar.pws.timestamps import assess_time, parse_utc
from premetar.sources import STATIONS, next_report

ZONE = ZoneInfo("Europe/Warsaw")
CALIBRATION_REPORT = (
    Path(__file__).resolve().parents[3] / "data/research/epwa_calibration/latest.json"
)


def qualifying_temperature(report: dict[str, Any]) -> tuple[float | None, str]:
    """Current verified EPWA rule: routine precise T-group, else body integer."""
    raw = str(report.get("raw_text", "")).strip()
    if report.get("report_type") != "METAR" or raw.startswith("SPECI"):
        return None, "SPECI_EXCLUDED"
    match = re.search(r"(?:^|\s)T([01])(\d{3})[01]\d{3}(?=\s|=|$)", raw)
    if match:
        value = int(match[2]) / 10
        return (-value if match[1] == "1" else value), "PRECISE_HOURLY_T_REMARK"
    match = re.search(r"(?:^|\s)(M?\d{2})/(?:M?\d{2}|//)(?=\s|=|$)", raw)
    if match:
        text = match[1]
        return (-float(text[1:]) if text.startswith("M") else float(text)), "BODY_INTEGER_FALLBACK"
    return None, "NO_QUALIFYING_TEMPERATURE"


def forecast_calibration(raw: dict[str, Any], at: datetime) -> dict[str, Any]:
    report = raw.get("forecast_calibration") or {}
    available_at = report.get("published_at", report.get("created_at"))
    known = available(available_at, at)
    return dict(
        status="CALIBRATION_PENDING",
        version="EPWA-FC-CAL-v1",
        temperature_c=None,
        times=[],
        sample_count=0,
        daily_sample_count=0,
        validated_error=None,
        reason="Brak zweryfikowanej historii końcowego Tmax i poprawy poza próbą"
        if known
        else "Brak audytu kalibracji dostępnego w tej chwili",
        reason_code=report.get("final_target_reason") if known else "REPORT_NOT_AVAILABLE_ASOF",
        model_results=report.get("summary", []) if known else [],
        model_support=report.get("model_support", {}) if known else {},
        asof_available_at=available_at if known else None,
        report_created_at=report.get("created_at") if known else None,
        promotion="BLOCKED_NO_VERIFIED_FINAL_TMAX_OOS_EVIDENCE",
        hourly_and_tmax_calibration="SEPARATE_TARGETS",
    )


def clock(value: Any) -> datetime | None:
    try:
        return parse_utc(value)
    except (ValueError, TypeError, OverflowError):
        return None


def time_key(value: Any) -> datetime:
    return clock(value) or datetime.min.replace(tzinfo=UTC)


def finite(value: Any) -> float | None:
    return (
        float(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        else None
    )


def quote_number(value: Any) -> float | None:
    try:
        return finite(float(value)) if value is not None and not isinstance(value, bool) else None
    except (ValueError, TypeError, OverflowError):
        return None


def available(value: Any, at: datetime) -> bool:
    parsed = clock(value)
    return parsed is not None and parsed <= at


def hour_slots(day: date) -> list[dict[str, Any]]:
    start, end = local_day_bounds(day, "Europe/Warsaw")
    result = []
    while start < end:
        result.append(
            dict(
                start=start.isoformat(),
                end=(start + timedelta(hours=1)).isoformat(),
                label=start.astimezone(ZONE).strftime("%H:%M %z"),
            )
        )
        start += timedelta(hours=1)
    return result


def forecast_view(records: list[dict[str, Any]], day: date, at: datetime) -> dict[str, Any]:
    records = sorted(
        (r for r in records if available(r.get("first_received", r.get("received_at")), at)),
        key=lambda r: (
            clock(r.get("first_received", r.get("received_at"))) or datetime.min.replace(tzinfo=UTC)
        ),
    )
    current = records[-1] if records else {}
    start, end = local_day_bounds(day, "Europe/Warsaw")
    slots = hour_slots(day)

    def points(row: dict[str, Any]) -> list[dict[str, Any]]:
        result = []
        for point in row.get("points", []):
            valid = clock(point.get("valid_time"))
            temp = finite(point.get("temperature_c"))
            if valid and start <= valid < end and temp is not None:
                result.append(
                    dict(
                        valid_time=valid.isoformat(),
                        temperature_c=temp,
                        first_received=row.get("first_received", row.get("received_at")),
                    )
                )
        return sorted(result, key=lambda p: p["valid_time"])

    pts = points(current)
    complete = {p["valid_time"] for p in pts} == {s["start"] for s in slots}
    peak = max((p["temperature_c"] for p in pts), default=None) if complete else None
    previous_points = points(records[-2]) if len(records) > 1 else []
    previous_complete = {p["valid_time"] for p in previous_points} == {s["start"] for s in slots}
    previous_peak = (
        max((p["temperature_c"] for p in previous_points), default=None)
        if previous_complete
        else None
    )
    local_hour = at.replace(minute=0, second=0, microsecond=0)
    hour_point = next((p for p in pts if clock(p["valid_time"]) == local_hour), None)
    next_point = next(
        (p for p in pts if clock(p["valid_time"]) == local_hour + timedelta(hours=1)), None
    )
    return dict(
        model=current.get("model"),
        run_time=current.get("model_run"),
        publication_time=current.get("publication_time"),
        first_received=current.get("first_received", current.get("received_at")),
        points=pts,
        previous_points=previous_points,
        tmax=dict(
            temperature_c=peak,
            times=[p["valid_time"] for p in pts if p["temperature_c"] == peak],
            complete=complete,
            semantics="MAXIMUM_GODZINOWYCH_PROGNOZ_PUNKTOWYCH_NIE_MAKSIMUM_GODZINNE",
            expected_hours=len(slots),
            available_hours=len(pts),
        ),
        previous_tmax=previous_peak,
        delta_tmax=peak - previous_peak if peak is not None and previous_peak is not None else None,
        current_hour=hour_point["temperature_c"] if hour_point else None,
        temperature_c=hour_point["temperature_c"] if hour_point else None,
        trend_c=next_point["temperature_c"] - hour_point["temperature_c"]
        if next_point and hour_point
        else None,
        hourly_maximum=None,
        uncertainty=None,
        run_metadata=current.get("candidate_model_metadata"),
        run_binding=current.get("run_binding", "UNKNOWN"),
    )


def calibration_at(
    records: list[dict[str, Any]],
    station: str,
    at: datetime,
    sensor: str,
    instrument_count: int = 1,
) -> dict[str, Any] | None:
    candidates = []
    for row in records:
        if (
            row.get("station_id") != station
            or not available(row.get("created_at"), at)
            or not available(row.get("trained_through"), at)
        ):
            continue
        params = row.get("parameters", {})
        if not isinstance(params, dict):
            continue
        if params.get("sensor_id") not in (None, sensor):
            continue
        if instrument_count > 1 and params.get("sensor_id") != sensor:
            continue
        if finite(params.get("bias")) is None:
            continue
        if params.get("published_at") and not available(params["published_at"], at):
            continue
        if params.get("input_cutoff_time") and not available(params["input_cutoff_time"], at):
            continue
        candidates.append(row)
    return max(
        candidates,
        key=lambda r: clock(r["created_at"]) or datetime.min.replace(tzinfo=UTC),
        default=None,
    )


def quote_view(view: dict[str, Any], at: datetime, sample_time: Any) -> dict[str, Any]:
    receipt = clock(view.get("received_at"))
    sample = clock(sample_time)
    status = view.get("status", "UNAVAILABLE")
    if not receipt or not sample or sample > at or receipt > at:
        status = "UNAVAILABLE"
    elif (at - receipt).total_seconds() > 10:
        status = "STALE_BOOK"
    bid = quote_number(view.get("best_bid"))
    ask = quote_number(view.get("best_ask"))
    if (
        view.get("best_bid") is not None
        and bid is None
        or view.get("best_ask") is not None
        and ask is None
    ):
        status = "INVALID_BOOK"
    if (
        bid is not None
        and not 0 < bid < 1
        or ask is not None
        and not 0 < ask < 1
        or bid is not None
        and ask is not None
        and bid >= ask
    ):
        status = "INVALID_BOOK"
    return dict(
        bid=bid,
        ask=ask,
        bid_size=view.get("bid_size"),
        ask_size=view.get("ask_size"),
        spread=ask - bid if bid is not None and ask is not None else None,
        last_trade=view.get("last_trade_price"),
        received_at=view.get("received_at"),
        sample_time=sample_time,
        status=status,
        executable=(
            status == "VALID" and ask is not None and (quote_number(view.get("ask_size")) or 0) > 0
        ),
        execution_semantics="DISPLAYED_QUOTES_NOT_GUARANTEED_FILL",
        connection_id=view.get("connection_id"),
    )


def market_views(
    raw: dict[str, Any], day: date, at: datetime
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    metadata: dict[str, dict[str, Any]] = {}
    for item in raw.get("markets", []):
        if not available(item.get("received_at", item.get("original_received")), at):
            continue
        identity = item.get("identity") or {}
        market = item.get("metadata", {})
        if (
            identity.get("airport") != "EPWA"
            or identity.get("station") != "EPWA"
            or identity.get("local_date") != day.isoformat()
            or identity.get("station_match") is not True
        ):
            continue
        if identity.get("yes") == identity.get("no"):
            continue
        metadata[identity["condition_id"]] = {"identity": identity, "metadata": market}
    latest: dict[str, dict[str, Any]] = {}
    history = []
    for item in raw.get("book_samples", []):
        identity = item.get("identity") or {}
        condition = identity.get("condition_id")
        stamp = item.get("captured_at", item.get("received_at"))
        if condition not in metadata or not available(stamp, at):
            continue
        known = metadata[condition]["identity"]
        if any(
            identity.get(k) != known.get(k)
            for k in ("station", "yes", "no", "local_date", "condition_id")
        ):
            continue
        quotes = {
            side: quote_view(item.get("books", {}).get(side, {}), clock(stamp) or at, stamp)
            for side in ("yes", "no")
        }
        if all(
            item.get("books", {}).get(side, {}).get("token_id") == known.get(side)
            and item.get("books", {}).get(side, {}).get("market") == condition
            for side in ("yes", "no")
        ):
            history.append(
                dict(
                    condition_id=condition,
                    time=stamp,
                    **quotes,
                    status="VALID"
                    if all(q["status"] == "VALID" for q in quotes.values())
                    else "GAP",
                )
            )
        if condition not in latest or time_key(stamp) > time_key(
            latest[condition].get("captured_at", latest[condition].get("received_at"))
        ):
            latest[condition] = item
    result = []
    for condition, value in metadata.items():
        identity = value["identity"]
        market = value["metadata"]
        sample = latest.get(condition, {})
        quotes = {
            side: quote_view(
                sample.get("books", {}).get(side, {}),
                at,
                sample.get("captured_at", sample.get("received_at")),
            )
            for side in ("yes", "no")
        }
        for side in ("yes", "no"):
            view = sample.get("books", {}).get(side, {})
            if view.get("token_id") != identity[side] or view.get("market") != condition:
                quotes[side].update(
                    status="UNVERIFIED_MAPPING", executable=False, bid=None, ask=None
                )
            trades = [
                t
                for t in raw.get("trades", [])
                if t.get("token_id") == identity[side]
                and available(t.get("received_at"), at)
                and t.get("condition_id") in (None, condition)
            ]
            trade = max(trades, key=lambda t: time_key(t["received_at"]), default=None)
            quotes[side]["last_trade"] = quote_number(trade.get("price")) if trade else None
            quotes[side]["last_trade_received"] = trade.get("received_at") if trade else None
        slug = identity.get("slug", market.get("slug", ""))
        result.append(
            dict(
                condition_id=condition,
                title=market.get("question", slug),
                outcome_label=market.get("groupItemTitle") or slug.split("2026-")[-1],
                slug=slug,
                station="EPWA",
                status="CLOSED"
                if market.get("closed") is True
                else "OPEN"
                if market.get("active") is True and market.get("acceptingOrders") is True
                else "UNKNOWN",
                **quotes,
                book_time=sample.get("captured_at", sample.get("received_at")),
                market_url="https://polymarket.com/event/" + slug,
                rule_text=market.get("description", ""),
                resolution_source=market.get("resolutionSource"),
                semantics="CONTRACT_RULES_NOT_INTEGER_METAR_MAXIMUM",
                identity=identity,
            )
        )
    return sorted(result, key=lambda m: m["outcome_label"]), sorted(
        history, key=lambda h: h["time"]
    )


def build_view(
    raw: dict[str, Any], day: date, at: datetime, generated: datetime | None = None
) -> dict[str, Any]:
    if at.tzinfo is None:
        raise ValueError("Naive cutoff")
    generated = generated or datetime.now(UTC)
    if at > generated:
        at = generated
    start, end = local_day_bounds(day, "Europe/Warsaw")
    forecast = forecast_view(raw.get("forecasts", []), day, at)
    forecast["calibration"] = forecast_calibration(raw, at)
    metars = [
        r
        for r in raw.get("metars", [])
        if available(r.get("first_received_utc"), at)
        and available(r.get("observation_time_utc"), at)
        and finite(r.get("temperature_c")) is not None
    ]
    metars.sort(key=lambda r: (r["observation_time_utc"], r["first_received_utc"]))
    latest_metar = max(
        metars, key=lambda r: clock(r["observation_time_utc"]) or start, default=None
    )
    routine: dict[str, dict[str, Any]] = {}
    for row in sorted(metars, key=lambda r: r["first_received_utc"]):
        if row.get("report_type") == "METAR":
            routine[row["observation_time_utc"]] = row
    peak = max((r["temperature_c"] for r in routine.values()), default=None)
    observed = dict(
        latest=latest_metar,
        max_temperature_c=peak,
        max_reports=[r for r in routine.values() if r["temperature_c"] == peak],
        routine_count=len(routine),
        routine_identity_count=sum(r.get("report_type") == "METAR" for r in metars),
        speci_policy="SPECI_WIDOCZNE_NIE_WLICZANE_DO_MAKSIMUM",
        maximum_semantics="MAXIMUM_SKORYGOWANYCH_RUTYNOWYCH_METAR_CALODZIENNE_NIE_WYNIK_ROZLICZENIA",
    )
    selections: dict[str, dict[str, Any]] = {}
    for selection in sorted(raw.get("selections", []), key=lambda s: s["created_at"]):
        if available(selection["created_at"], at):
            selections[selection["station_id"]] = selection
    instrument_count: dict[str, int] = defaultdict(int)
    for item in raw.get("stations", []):
        instrument_count[item["station_id"]] += 1
    latest_readings: dict[str, dict[str, Any]] = {}
    series: dict[str, dict[str, Any]] = {}
    valid_readings = []
    for row in raw.get("inventory_last", []) + raw.get("pws", []):
        if not available(row.get("first_receive_time"), at):
            continue
        sid = row["sensor_id"]
        stamp = clock(row.get("observation_time"))
        if sid not in latest_readings or time_key(row["first_receive_time"]) > time_key(
            latest_readings[sid]["first_receive_time"]
        ):
            latest_readings[sid] = row
        check = assess_time(row)
        if not check.eligible or not stamp or stamp > at or not start <= stamp < end:
            continue
        cal = calibration_at(
            raw.get("calibrations", []),
            row["station_id"],
            clock(row["first_receive_time"]) or at,
            sid,
            instrument_count[row["station_id"]],
        )
        bias = cal["parameters"]["bias"] if cal else None
        point = dict(
            measurement_time=stamp.isoformat(),
            first_received=row["first_receive_time"],
            temperature_c=row["temperature_c"],
            calibrated_temperature_c=row["temperature_c"] - bias if bias is not None else None,
            calibration_id=cal["id"] if cal else None,
            qc_status=check.status,
            provenance=check.timestamp_provenance,
            sensor_id=sid,
        )
        point["name"] = row.get("station_name") or sid
        reference = max(
            (
                r
                for r in metars
                if available(r["first_received_utc"], clock(row["first_receive_time"]) or at)
                and time_key(r["observation_time_utc"]) <= time_key(row["first_receive_time"])
            ),
            key=lambda r: r["observation_time_utc"],
            default=None,
        )
        point["delta_metar_c"] = (
            row["temperature_c"] - reference["temperature_c"] if reference else None
        )
        point["metar_reference_time"] = reference["observation_time_utc"] if reference else None
        item = series.setdefault(
            sid,
            dict(
                sensor_id=sid,
                station_id=row["station_id"],
                name=row.get("station_name", sid),
                points=[],
            ),
        )
        item["points"].append(point)
        valid_readings.append(point)
    stations = []
    for info in raw.get("stations", []):
        row = latest_readings.get(info["sensor_id"])
        current_check = assess_time(row, at=at) if row else None
        selection = selections.get(info["station_id"])
        selected = bool(selection.get("selected")) if selection else False
        cal = calibration_at(
            raw.get("calibrations", []),
            info["station_id"],
            at,
            info["sensor_id"],
            instrument_count[info["station_id"]],
        )
        bias = cal["parameters"]["bias"] if cal else None
        value = finite(row.get("temperature_c")) if row else None
        corrected = (
            value - bias
            if value is not None and bias is not None and current_check and current_check.eligible
            else None
        )
        stations.append(
            dict(
                station_id=info["station_id"],
                sensor_id=info["sensor_id"],
                name=info.get("station_name") or info.get("name") or info["station_id"],
                distance_km=info.get("distance_km"),
                model=info.get("sensor_model"),
                selected=selected,
                raw_temperature_c=value,
                calibrated_temperature_c=corrected,
                bias_c=bias,
                predicted_integer=icao_round_temperature(corrected)
                if corrected is not None
                else None,
                measurement_time=row.get("observation_time") if row else None,
                first_received=row.get("first_receive_time") if row else None,
                age_seconds=current_check.age_at_receipt_seconds if current_check else None,
                qc_status=current_check.status if current_check else "NO_MEASUREMENT",
                provenance=current_check.timestamp_provenance if current_check else "UNKNOWN_TIME",
                status=current_check.status if current_check else "NO_MEASUREMENT",
                selection_reason=selection.get("reason") if selection else None,
                calibration_id=cal["id"] if cal else None,
                calibration_semantics="STORED_CAUSAL_QUANTIZED_REFERENCE_STATION_OFFSET"
                if cal
                else "UNAVAILABLE",
                metadata_status="CURRENT_REFERENCE_METADATA_NOT_HISTORICAL_PROOF",
            )
        )
    stations.sort(key=lambda s: (not s["selected"], s["distance_km"] or 0, s["name"]))
    for item in series.values():
        item["points"].sort(key=lambda p: p["measurement_time"])
    hours = []
    for slot in hour_slots(day):
        left, right = time_key(slot["start"]), time_key(slot["end"])
        hour_point = next((p for p in forecast["points"] if p["valid_time"] == slot["start"]), None)
        previous = next(
            (p for p in forecast["previous_points"] if p["valid_time"] == slot["start"]), None
        )
        hourly_reports = [r for r in metars if left <= time_key(r["observation_time_utc"]) < right]
        readings = [p for p in valid_readings if left <= time_key(p["measurement_time"]) < right]
        known = [
            r
            for r in metars
            if time_key(r["first_received_utc"]) < min(right, at)
            and time_key(r["observation_time_utc"]) < min(right, at)
        ]
        hours.append(
            dict(
                **slot,
                forecast_c=hour_point["temperature_c"] if hour_point else None,
                forecast_max_c=None,
                revision_c=hour_point["temperature_c"] - previous["temperature_c"]
                if hour_point and previous
                else None,
                metars=hourly_reports,
                pws=readings,
                last_metar=max(known, key=lambda r: r["observation_time_utc"], default=None),
                quality="Rzeczywiste odczyty" if readings or hourly_reports else "Brak pomiarów",
            )
        )
    markets, history = market_views(raw, day, at)
    verified_rules = any(
        "hourly temperature remark" in m["rule_text"]
        and "SPECI" in m["rule_text"]
        and "ids=EPWA" in (m.get("resolution_source") or "")
        for m in markets
    )
    qualified = []
    if verified_rules:
        for report in routine.values():
            temperature, semantics = qualifying_temperature(report)
            if temperature is not None:
                qualified.append(
                    {
                        **report,
                        "qualifying_temperature_c": temperature,
                        "temperature_semantics": semantics,
                    }
                )
    observed.update(
        official_maximum_c=max((r["qualifying_temperature_c"] for r in qualified), default=None),
        official_reference="AWC_EPWA_ROUTINE_T_REMARK_ELSE_BODY_CURRENT_RULES"
        if verified_rules
        else "UNVERIFIED_MARKET_RULES",
        official_maximum_semantics="MAXIMUM_QUALIFYING_REPORTS_RECEIVED_SO_FAR_NOT_FINAL_RESOLUTION",
        final_settlement_value=None,
        final_settlement_status="NOT_CERTIFIED",
    )
    signals = [
        s
        for s in raw.get("signals", [])
        if available(s.get("created_at", s.get("received_at")), at)
    ]

    def source_health(stamp: Any, threshold: int) -> dict[str, Any]:
        parsed = clock(stamp)
        age = (generated - parsed).total_seconds() if parsed else None
        return dict(
            status="LIVE"
            if age is not None and 0 <= age <= threshold
            else "STALE"
            if parsed
            else "UNAVAILABLE",
            last_received=stamp,
            age_seconds=age,
        )

    source = raw.get("health", {})
    weather = source.get("weather", {})
    heartbeat = weather.get("heartbeat", weather.get("received_at"))
    health = dict(
        weather={**source_health(heartbeat, 120), "heartbeat": heartbeat},
        forecast=source_health(forecast["first_received"], 5400),
        pws={
            **source_health(
                max((s["first_received"] for s in stations if s["first_received"]), default=None),
                300,
            ),
            "last_measurement": max(
                (s["measurement_time"] for s in stations if s["measurement_time"]), default=None
            ),
        },
        market=source_health(
            max((m["book_time"] for m in markets if m["book_time"]), default=None), 15
        ),
        clock_status="UNKNOWN",
        websocket=source.get("websocket", {}),
    )
    health["weather"]["collector_status"] = health["weather"]["status"]
    health["weather"]["last_received"] = (
        latest_metar["first_received_utc"] if latest_metar else None
    )
    valid_stations = [s for s in stations if s["status"] == "VALID"]
    health["pws"] = source_health(
        max((s["first_received"] for s in valid_stations if s["first_received"]), default=None), 300
    )
    health["pws"]["last_measurement"] = max(
        (s["measurement_time"] for s in valid_stations if s["measurement_time"]), default=None
    )
    if not any(m[side]["status"] == "VALID" for m in markets for side in ("yes", "no")):
        health["market"]["status"] = "STALE" if markets else "UNAVAILABLE"
    health["websocket"] = {
        key: source.get("websocket", {}).get(key)
        for key in ("state", "received_at", "connection_id")
    }
    warnings = [
        "METAR to temperatura całkowita; maksimum rutynowych raportów nie jest zweryfikowanym wynikiem rozliczenia rynku.",
        "Prognozowany Tmax jest maksimum próbek godzinowych, nie gwarantowanym maksimum temperatury.",
        "Niezweryfikowane przesunięcie zegara systemowego; brak gwarancji dokładności milisekundowej.",
    ]
    limits = raw.get("limits", {})
    if limits.get("errors"):
        warnings.append("Część źródeł jest niedostępna: " + str(limits["errors"]))
    if (
        any(limits.get("truncated", {}).values())
        if isinstance(limits.get("truncated"), dict)
        else limits.get("truncated")
    ):
        warnings.append("Osiągnięto limit odczytu. Widoczny zakres może być niepełny.")
    return dict(
        airport="EPWA",
        date=day.isoformat(),
        timezone="Europe/Warsaw",
        generated_at=generated.isoformat(),
        day_start=start.isoformat(),
        day_end=end.isoformat(),
        cutoff=at.isoformat(),
        health=health,
        forecast=forecast,
        observed=observed,
        metars=metars,
        pws_series=list(series.values()),
        stations=stations,
        hours=hours,
        markets=markets,
        market_history=history,
        signals=signals,
        warnings=warnings,
        limits=limits,
        weathercloud=[
            dict(
                name="Vevor / Ichipek",
                model="CCL Electronics P100",
                url="https://app.weathercloud.net/d1542158444#profile",
                verification="PROFILE_VERIFIED_READ_API_UNKNOWN",
            ),
            dict(
                name="Lawart.pl / MC_cichy",
                model="Bresser 7-in-1",
                url="https://app.weathercloud.net/d0865035381#profile",
                verification="PROFILE_VERIFIED_READ_API_UNKNOWN",
            ),
        ],
    )


class DashboardService:
    """Bounded four-day cache, shared across UI clients; no long read transactions."""

    def __init__(self, reader: Any, ttl: float = 15) -> None:
        self.reader = reader
        self.ttl = ttl
        self._lock = threading.Lock()
        self._cache: dict[date, tuple[float, dict[str, Any]]] = {}

    def raw(self, day: date) -> dict[str, Any]:
        with self._lock:
            cached = self._cache.get(day)
            if cached and time.monotonic() - cached[0] < self.ttl:
                return cached[1]
            raw: dict[str, Any] = self.reader.load_day(day)
            try:
                raw["forecast_calibration"] = (
                    json.loads(CALIBRATION_REPORT.read_text(encoding="utf-8"))
                    if CALIBRATION_REPORT.exists()
                    else None
                )
            except (OSError, ValueError):
                raw["forecast_calibration"] = None
            if len(self._cache) >= 4:
                self._cache.pop(next(iter(self._cache)))
            self._cache[day] = (time.monotonic(), raw)
            return raw

    def day(self, day: date, at: datetime | None = None) -> dict[str, Any]:
        generated = datetime.now(UTC)
        _, end = local_day_bounds(day, "Europe/Warsaw")
        cutoff = min(at or generated, end - timedelta(microseconds=1), generated)
        return build_view(self.raw(day), day, cutoff, generated)

    def asof(self, day: date, at: datetime, market: str | None = None) -> dict[str, Any]:
        data = self.day(day, at)
        pws = [s for s in data["stations"] if s["status"] == "VALID"]
        target = next_report(STATIONS["EPWA"], clock(data["cutoff"]) or at)
        return dict(
            at=data["cutoff"],
            metar=data["observed"]["latest"],
            pws=pws,
            forecast=data["forecast"],
            markets=[m for m in data["markets"] if not market or m["condition_id"] == market],
            next_nominal_metar=target.isoformat(),
            seconds_to_metar=(target - at).total_seconds(),
            warnings=data["warnings"],
            semantics="INFORMACJE_Z_PIERWSZYM_ODBIOREM_NIE_POZNIEJ_NIZ_T",
        )
