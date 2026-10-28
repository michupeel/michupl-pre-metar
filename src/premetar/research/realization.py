"""EXP0014 pure, causal qualitative realization rules; no trading probabilities.

An integer METAR is an interval reference. Published forecast revisions and
corrections may only enter the state after their recorded receipt. No API calls,
database writes, model promotion or production QC changes occur in this module.
"""

import math
import re
from datetime import datetime, timedelta
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from astral import Observer
from astral.sun import elevation

from premetar.pws.analysis import interval_residual
from premetar.pws.daily_time import local_day_bounds
from premetar.pws.timestamps import assess_time, parse_utc

VERSION = "EPWA-REALIZATION-v1.1"
ZONE = ZoneInfo("Europe/Warsaw")
HOURLY_VARIABLES = (
    "temperature_2m",
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "relative_humidity_2m",
    "dew_point_2m",
    "wind_speed_10m",
    "wind_direction_10m",
    "precipitation",
    "shortwave_radiation",
)


def _clock(value: Any) -> datetime | None:
    try:
        return parse_utc(value)
    except (ValueError, TypeError, OverflowError):
        return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _temperature(group: str) -> float | None:
    if not re.fullmatch(r"M?\d{2}", group):
        return None
    return -float(group[1:]) if group.startswith("M") else float(group)


def parse_metar_conditions(text: str) -> dict[str, Any]:
    """Conservative body parsing; categories remain categories, not cloud percent.

    Cloud information applies below the METAR reporting envelope. NSC/CAVOK/NCD
    never certify the complete absence of cloud, including higher cloud.
    """
    if not isinstance(text, str):
        text = ""
    body = re.split(r"\s(?:TEMPO|BECMG|RMK)\b", text.upper().strip(), maxsplit=1)[0]
    tokens = body.split()
    station = re.search(r"(?:^|\s)([A-Z]{4})\s+\d{6}Z(?:\s|$)", body)
    therm = re.search(r"(?:^|\s)(M?\d{2}|//)/(M?\d{2}|//)(?=\s|=|$)", body)
    wind = re.search(r"(?:^|\s)(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?(KT|MPS)(?=\s|$)", body)
    layers = []
    malformed = []
    oktas = {"FEW": [1, 2], "SCT": [3, 4], "BKN": [5, 7], "OVC": [8, 8]}
    for token in tokens:
        layer = re.fullmatch(r"(FEW|SCT|BKN|OVC)(\d{3}|///)(CB|TCU)?", token)
        if layer:
            base = int(layer[2]) * 100 if layer[2].isdigit() else None
            layers.append(
                dict(
                    amount=layer[1], base_ft=base, amount_okta_range=oktas[layer[1]], kind=layer[3]
                )
            )
        elif token.startswith(("FEW", "SCT", "BKN", "OVC", "VV")):
            if re.fullmatch(r"VV(?:\d{3}|///)", token):
                layers.append(
                    dict(
                        amount="VV",
                        base_ft=int(token[2:]) * 100 if token[2:].isdigit() else None,
                        amount_okta_range=None,
                        kind=None,
                    )
                )
            else:
                malformed.append(token)
    clear = [token for token in ("NSC", "NCD", "CAVOK", "SKC", "CLR") if token in tokens]
    weather = [
        token
        for token in tokens
        if re.fullmatch(
            r"(?:\+|-|VC)?(?:MI|PR|BC|DR|BL|SH|TS|FZ)?(?:DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PO|SQ|FC|SS|DS){1,3}",
            token,
        )
    ]
    visibility: dict[str, Any] | None = None
    if "CAVOK" in tokens:
        visibility = dict(value=10000, unit="m", qualifier="AT_LEAST", source="CAVOK")
    else:
        match = re.search(r"(?:^|\s)(\d{4})(?:NDV)?(?=\s|$)", body)
        if match:
            visibility = dict(
                value=int(match[1]) if match[1] != "9999" else 10000,
                unit="m",
                qualifier="AT_LEAST" if match[1] == "9999" else "REPORTED",
                source="BODY",
            )
        else:
            match = re.search(r"(?:^|\s)(P?\d+(?:/\d+)?SM)(?=\s|$)", body)
            if match:
                visibility = dict(raw=match[1], unit="statute_miles", qualifier="UNCONVERTED")
    return dict(
        station=station[1] if station else None,
        temperature_c=_temperature(therm[1]) if therm else None,
        dew_point_c=_temperature(therm[2]) if therm else None,
        wind=dict(
            direction_degrees=int(wind[1]) if wind[1] != "VRB" else None,
            variable=wind[1] == "VRB",
            speed=int(wind[2]),
            gust=int(wind[3]) if wind[3] else None,
            unit=wind[4],
        )
        if wind
        else None,
        visibility=visibility,
        cloud_layers=layers,
        cloud_clear_codes=clear,
        cloud_status="MALFORMED_OR_AMBIGUOUS"
        if malformed or clear and layers
        else "REPORTED"
        if clear or layers
        else "MISSING",
        cloud_uncertainty="CATEGORY_AND_BASE_ONLY_NO_EXACT_AREA_FRACTION_OR_CLOUD_TOP; CAVOK_NSC_NCD_NOT_CLOUDLESS",
        malformed_cloud_tokens=malformed,
        significant_weather=weather,
        precipitation_indicated=any(
            re.search(r"DZ|RA|SN|SG|IC|PL|GR|GS|UP", token) for token in weather
        ),
        raw_text=text,
    )


def _point_time(point: dict[str, Any]) -> datetime | None:
    return _clock(point.get("valid_time"))


def _aligned(forecast: dict[str, Any], when: datetime) -> dict[str, Any] | None:
    """Exact hourly point or interpolation across at most one60-minute interval."""
    points: dict[datetime, dict[str, Any]] = {}
    for point in forecast.get("points", []):
        if not isinstance(point, dict):
            continue
        time = _point_time(point)
        value = _number(point.get("temperature_c", point.get("temperature_2m")))
        if time and value is not None and -95 <= value <= 65:
            if time in points:
                return None  # Conflicting or duplicate point identity is not assumed safe.
            points[time] = {**point, "temperature_c": value}
    if when in points:
        return {**points[when], "alignment": "DIRECT_HOURLY_POINT", "aligned_at": when.isoformat()}
    lower = max((time for time in points if time < when), default=None)
    upper = min((time for time in points if time > when), default=None)
    if not lower or not upper or upper - lower > timedelta(hours=1):
        return None
    weight = (when - lower).total_seconds() / (upper - lower).total_seconds()
    result: dict[str, Any] = dict(
        alignment="LINEAR_INTERPOLATION_NOT_DIRECT_MODEL_OUTPUT",
        aligned_at=when.isoformat(),
        source_valid_times=[lower.isoformat(), upper.isoformat()],
    )
    # Direction is circular and accumulated precipitation/radiation are not points.
    for key in (
        "temperature_c",
        "cloud_cover",
        "cloud_cover_low",
        "cloud_cover_mid",
        "cloud_cover_high",
        "relative_humidity_2m",
        "dew_point_2m",
        "wind_speed_10m",
    ):
        a, b = _number(points[lower].get(key)), _number(points[upper].get(key))
        result[key] = a + weight * (b - a) if a is not None and b is not None else None
    return result


def _cloud(conditions: dict[str, Any], point: dict[str, Any]) -> dict[str, Any]:
    expected = _number(point.get("cloud_cover_low"))
    base = dict(
        status="INSUFFICIENT DATA",
        forecast_low_cloud_percent=expected,
        observed_categories=conditions["cloud_layers"],
        no_exact_observed_percent=True,
        low_layer_rule="REPORTED_BASE_AT_OR_BELOW6500FT_NOT_EQUIVALENT_TO_MODEL_VOLUME",
        caveat=conditions["cloud_uncertainty"],
    )
    if expected is None or not 0 <= expected <= 100 or conditions["cloud_status"] != "REPORTED":
        return base
    low = [
        layer["amount"]
        for layer in conditions["cloud_layers"]
        if layer["base_ft"] is not None and layer["base_ft"] <= 6500
    ]
    clear = bool(conditions["cloud_clear_codes"])
    if "OVC" in low and expected < 30:
        status = "UNEXPECTED OVERCAST"
    elif any(amount in low for amount in ("BKN", "OVC", "VV")) and expected < 30:
        status = "MORE LOW CLOUD THAN EXPECTED"
    elif expected >= 70 and clear:
        status = "FORECAST LOW CLOUD NOT OBSERVED"
    elif expected >= 70 and low and all(amount in {"FEW", "SCT"} for amount in low):
        status = "LESS LOW CLOUD THAN EXPECTED"
    elif low or clear:
        status = "BROADLY CONSISTENT"
    else:
        status = "INSUFFICIENT DATA"
    return {**base, "status": status}


def _deviation(value: float, previous: str | None) -> str:
    magnitude = abs(value)
    levels = ["ON TRACK", "SLIGHTLY", "", "SIGNIFICANTLY"]
    index = 0 if magnitude <= 0.25 else 1 if magnitude <= 0.75 else 2 if magnitude <= 1.75 else 3
    status = (
        "ON TRACK"
        if index == 0
        else (levels[index] + " " + ("COLDER" if value < 0 else "HOTTER")).strip()
    )
    # Small deadband only retains a neighboring state on the same side.
    names = ["ON TRACK"] + [
        (levels[i] + " " + ("COLDER" if value < 0 else "HOTTER")).strip() for i in range(1, 4)
    ]
    if previous in names:
        old_index = names.index(previous)
        boundary = (
            [0.25, 0.75, 1.75][min(index, old_index)] if abs(index - old_index) == 1 else None
        )
        if boundary is not None and abs(magnitude - boundary) <= 0.15:
            return previous
    return status


def _forecast_peak(forecast: dict[str, Any] | None, at: datetime) -> dict[str, Any]:
    base: dict[str, Any] = dict(
        temperature_c=None,
        time=None,
        complete=False,
        semantics="MAX_OF_HOURLY_POINT_FORECASTS_NOT_DAILY_OR_HOURLY_MAXIMUM",
    )
    if forecast is None:
        return base
    start, end = local_day_bounds(at.astimezone(ZONE).date(), "Europe/Warsaw")
    points = {}
    for point in forecast.get("points", []):
        time = _point_time(point)
        value = _number(point.get("temperature_c", point.get("temperature_2m")))
        if time and value is not None and start <= time < end:
            if time in points:
                return base
            points[time] = value
    expected = {
        start + timedelta(hours=h) for h in range(int((end - start).total_seconds() / 3600))
    }
    if points.keys() != expected:
        return base
    peak = max(points.values())
    times = [time for time, value in sorted(points.items()) if value == peak]
    return {
        **base,
        "temperature_c": peak,
        "time": times[0].isoformat(),
        "times": [t.isoformat() for t in times],
        "complete": True,
        "hours": len(points),
    }


def evaluate_realization(
    metars: list[dict[str, Any]],
    forecasts: list[dict[str, Any]],
    pws: list[dict[str, Any]],
    at: datetime,
    previous_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return only state reproducible from observations received no later than at."""
    parsed_at = _clock(at)
    if parsed_at is None:
        raise ValueError("Timezone-aware decision time required")
    at = parsed_at
    prior_at = _clock((previous_state or {}).get("created_at"))
    previous = (
        previous_state
        if prior_at is not None
        and prior_at <= at
        and (previous_state or {}).get("rule_version") == VERSION
        else None
    )
    known_forecasts = []
    for f in forecasts:
        received = _clock(f.get("first_received"))
        if (
            received
            and received <= at
            and f.get("model", "icon_global") == "icon_global"
            and f.get("airport", "EPWA") == "EPWA"
        ):
            known_forecasts.append((received, f))
    known_forecasts.sort(key=lambda item: item[0])
    versions: dict[datetime, tuple[datetime, dict[str, Any]]] = {}
    rejected: dict[str, int] = {}
    for report in metars:
        event = _clock(report.get("observation_time_utc"))
        received = _clock(report.get("first_received_utc"))
        value = _number(report.get("temperature_c"))
        conditions = parse_metar_conditions(report.get("raw_text", ""))
        if report.get("report_type") != "METAR" or conditions["station"] not in {None, "EPWA"}:
            continue
        if report.get("startup_censored") or report.get("coverage_gap"):
            rejected["CENSORED_REFERENCE"] = rejected.get("CENSORED_REFERENCE", 0) + 1
            continue
        if (
            event is None
            or received is None
            or event > at
            or received > at
            or value is None
            or value != int(value)
            or not -95 <= value <= 65
        ):
            rejected["INVALID_FUTURE_OR_UNAVAILABLE_REFERENCE"] = (
                rejected.get("INVALID_FUTURE_OR_UNAVAILABLE_REFERENCE", 0) + 1
            )
            continue
        # Latest available correction for a nominal cycle, never another sample.
        if event not in versions or received > versions[event][0]:
            versions[event] = received, report
    history = []
    selected_forecast = None
    for event, (received, report) in sorted(versions.items()):
        eligible = [
            (receipt, forecast)
            for receipt, forecast in known_forecasts
            if receipt < event and (event - receipt).total_seconds() <= 10800
        ]
        if not eligible:
            continue
        forecast_receipt, forecast = eligible[-1]
        point = _aligned(forecast, event)
        if point is None:
            continue
        actual = float(report["temperature_c"])
        predicted = point["temperature_c"]
        conditions = parse_metar_conditions(report.get("raw_text", ""))
        history.append(
            dict(
                metar_id=report.get("report_identity"),
                nominal_time=event.isoformat(),
                first_received=received.isoformat(),
                temperature_c=actual,
                forecast_temperature_c=predicted,
                signed_interval_residual_c=-interval_residual(predicted, int(actual)),
                midpoint_error_c=actual - predicted,
                metar_interval_c=[actual - 0.5, actual + 0.5],
                upper_interval_open=True,
                forecast_snapshot_id=forecast.get(
                    "snapshot_id",
                    forecast.get(
                        "id", forecast.get("raw_payload_hash", forecast_receipt.isoformat())
                    ),
                ),
                forecast_first_received=forecast_receipt.isoformat(),
                alignment=point["alignment"],
                conditions=conditions,
                cloud=_cloud(conditions, point),
            )
        )
        selected_forecast = forecast
    latest = history[-1] if history else None
    latest_known_nominal = max(versions, default=None)
    missing_latest_alignment = bool(
        latest_known_nominal
        and (latest is None or _clock(latest["nominal_time"]) != latest_known_nominal)
    )
    observed_values = [
        float(report["temperature_c"])
        for nominal, (_, report) in versions.items()
        if nominal.astimezone(ZONE).date() == at.astimezone(ZONE).date()
    ]
    observed_maximum = max(observed_values) if observed_values else None
    recent = history[-3:]
    # Old observations cannot produce persistent evidence across missing cycles/days.
    enough = len(recent) == 3 and (_clock(recent[-1]["nominal_time"]) or at) - (
        _clock(recent[0]["nominal_time"]) or at
    ) <= timedelta(hours=2)
    latest_age = (at - (_clock(latest["nominal_time"]) or at)).total_seconds() if latest else None
    forecast_age = (
        (at - (_clock(latest["forecast_first_received"]) or at)).total_seconds() if latest else None
    )
    stale = bool(latest and ((latest_age or 0) > 4500 or (forecast_age or 0) > 10800))
    residual = latest["signed_interval_residual_c"] if latest else None
    state = (
        "INSUFFICIENT DATA"
        if latest is None or missing_latest_alignment
        else "STALE DATA"
        if stale
        else _deviation(float(residual or 0), (previous or {}).get("state"))
    )
    values = [row["signed_interval_residual_c"] for row in recent]
    persistent = float(median(values)) if enough else None
    peak = _forecast_peak(selected_forecast, at)
    hours_to_peak = (
        ((_clock(peak["time"]) or at) - at).total_seconds() / 3600 if peak["complete"] else None
    )
    current_point = _aligned(selected_forecast, at) if selected_forecast else None
    future_temperatures = [
        float(p["temperature_c"])
        for p in (selected_forecast or {}).get("points", [])
        if (_point_time(p) or at) > at
        and (_point_time(p) or at).astimezone(ZONE).date() == at.astimezone(ZONE).date()
        and _number(p.get("temperature_c")) is not None
    ]
    remaining_warming = (
        max(
            0.0,
            max(future_temperatures, default=current_point["temperature_c"])
            - current_point["temperature_c"],
        )
        if current_point and peak["complete"]
        else None
    )
    trend = "TREND UNCERTAIN"
    rates: dict[str, Any] = dict(
        actual_c_per_hour=None,
        forecast_c_per_hour=None,
        mismatch_c_per_hour=None,
        quantization_uncertainty_c_per_hour=None,
        error_trend_c_per_hour=None,
        forecasts_may_differ=False,
    )
    if enough:
        first, last = recent[0], recent[-1]
        elapsed = (
            (_clock(last["nominal_time"]) or at) - (_clock(first["nominal_time"]) or at)
        ).total_seconds() / 3600
        if 0.5 <= elapsed <= 2:
            observed_rate = (last["temperature_c"] - first["temperature_c"]) / elapsed
            # One trajectory frozen before the first event: forecast revision
            # jumps must not masquerade as meteorological temperature tendency.
            frozen = next(
                (
                    forecast
                    for receipt, forecast in reversed(known_forecasts)
                    if receipt < (_clock(first["nominal_time"]) or at)
                ),
                None,
            )
            left = _aligned(frozen, _clock(first["nominal_time"]) or at) if frozen else None
            right = _aligned(frozen, _clock(last["nominal_time"]) or at) if frozen else None
            forecast_rate = (
                ((right["temperature_c"] - left["temperature_c"]) / elapsed)
                if left and right
                else None
            )
            if forecast_rate is None:
                forecast_rate = float("nan")
            mismatch = observed_rate - forecast_rate
            uncertainty = 1.0 / elapsed
            rates = dict(
                actual_c_per_hour=observed_rate,
                forecast_c_per_hour=forecast_rate if math.isfinite(forecast_rate) else None,
                mismatch_c_per_hour=mismatch if math.isfinite(mismatch) else None,
                quantization_uncertainty_c_per_hour=uncertainty,
                error_trend_c_per_hour=(values[-1] - values[0]) / elapsed,
                elapsed_hours=elapsed,
                forecasts_may_differ=len({row["forecast_snapshot_id"] for row in recent}) > 1,
                trajectory_forecast_received=frozen.get("first_received") if frozen else None,
                trajectory_policy="SINGLE_SNAPSHOT_RECEIVED_BEFORE_FIRST_OBSERVATION",
            )
            threshold = max(0.5, uncertainty)
            if forecast_rate >= 0.25:
                trend = (
                    "WARMING SLOWER"
                    if mismatch < -threshold
                    else "WARMING FASTER"
                    if mismatch > threshold
                    else "WARMING AS EXPECTED"
                )
            elif forecast_rate <= -0.25:
                trend = (
                    "COOLING SLOWER"
                    if mismatch > threshold
                    else "COOLING FASTER"
                    if mismatch < -threshold
                    else "COOLING AS EXPECTED"
                )
    cloud = latest["cloud"] if latest else dict(status="INSUFFICIENT DATA")
    solar_elevation = elevation(Observer(52.163, 20.961), at)
    confidence = "INSUFFICIENT DATA"
    colder_persistent = bool(enough and all(value <= -0.75 for value in values))
    hotter_persistent = bool(enough and all(value >= 0.75 for value in values))
    low_cloud = cloud["status"] in {"MORE LOW CLOUD THAN EXPECTED", "UNEXPECTED OVERCAST"}
    risk_window = hours_to_peak is not None and -1 <= hours_to_peak <= 3
    if enough and not stale and not missing_latest_alignment:
        confidence = "ON TRACK" if abs(persistent or 0) <= 0.25 else "MINOR DEVIATION"
        if risk_window and (
            colder_persistent
            and (trend == "WARMING SLOWER" or low_cloud and solar_elevation > 0)
            or hotter_persistent
        ):
            confidence = "FORECAST AT RISK"
            if abs(persistent or 0) >= 1.75 and hours_to_peak is not None and hours_to_peak <= 1.5:
                confidence = "FORECAST HIGH RISK"
        if (
            (previous or {}).get("confidence") in {"FORECAST AT RISK", "FORECAST HIGH RISK"}
            and abs(persistent or 0) <= 0.75
            and abs(values[-1]) < abs(values[0])
        ):
            confidence = "FORECAST RECOVERING"
    adaptive: dict[str, Any] = dict(
        status="EXPERIMENTAL / INSUFFICIENT DATA",
        temperature_c=None,
        time=None,
        validated=False,
        method="DAMPED_PERSISTENT_INTERVAL_RESIDUAL_WITH_REMAINING_WARMING_v1",
    )
    if (
        enough
        and not stale
        and not missing_latest_alignment
        and peak["complete"]
        and remaining_warming is not None
        and hours_to_peak is not None
        and hours_to_peak >= 0
    ):
        # Damping bounds influence from a few quantized cycles; no cloud causal coefficient.
        damping = 0.25 if rates["forecasts_may_differ"] else 0.5
        offset = max(-1.5, min(1.5, damping * (persistent or 0)))
        corrected = peak["temperature_c"] + offset * math.exp(-max(0.0, hours_to_peak) / 6)
        adaptive = dict(
            status="EXPERIMENTAL_NOT_VALIDATED",
            temperature_c=max(observed_maximum - 0.5, corrected)
            if observed_maximum is not None
            else corrected,
            time=peak["time"],
            created_at=at.isoformat(),
            validated=False,
            damping=damping,
            offset_c=offset,
            remaining_warming_c=remaining_warming,
            method=adaptive["method"],
            target_semantics="MAX_OF_FUTURE_HOURLY_POINTS_WITH_DAMPED_MEDIAN_RESIDUAL_NOT_VERIFIED_SETTLEMENT_TMAX",
        )
    eligible_pws = []
    for reading in pws:
        try:
            assessment = assess_time(reading, at)
            if assessment.eligible:
                eligible_pws.append(reading.get("id", reading.get("observation_id")))
        except (ValueError, TypeError, KeyError):
            continue
    explanation = "Brak trzech odrębnych, dostępnych cykli METAR z wcześniejszą prognozą ICON."
    if latest:
        explanation = f"METAR {latest['temperature_c']:.0f}°C; ICON {latest['forecast_temperature_c']:.2f}°C ({latest['alignment']}); reszta względem przedziału METAR {residual:+.2f}°C."
        if enough:
            explanation += (
                f" Mediana ostatnich trzech reszt: {persistent:+.2f}°C; {trend}; {cloud['status']}."
            )
        if stale:
            explanation += " Dane nieświeże: klasyfikacja ryzyka wstrzymana."
    if missing_latest_alignment:
        explanation += " Najnowszy dostępny METAR nie ma wcześniejszej kwalifikującej prognozy; bieżąca klasyfikacja wstrzymana."
    return dict(
        rule_version=VERSION,
        created_at=at.isoformat(),
        state=state,
        confidence=confidence,
        trend=trend,
        cloud=cloud,
        adaptive_tmax=adaptive,
        forecast_tmax=peak,
        forecast_at_metar=latest["forecast_temperature_c"] if latest else None,
        residual_c=residual,
        midpoint_error_c=latest["midpoint_error_c"] if latest else None,
        latest_metar=latest,
        history=history,
        explanation=explanation,
        supporting_metar_ids=[row["metar_id"] for row in recent],
        eligible_pws_ids=eligible_pws,
        forecast_snapshot_id=latest["forecast_snapshot_id"] if latest else None,
        observed_metar_maximum_c=observed_maximum,
        observed_maximum_semantics="AVAILABLE_ROUTINE_INTEGER_REPORTS_NOT_FINAL_SETTLEMENT_TMAX",
        evidence=dict(
            persistent_residual_c=persistent,
            latest_residual_c=residual,
            rates=rates,
            remaining_warming_c=remaining_warming,
            hours_to_tmax=hours_to_peak,
            solar_elevation_degrees=solar_elevation,
            cloud_effect="UNTESTED_ASSOCIATION_NOT_CAUSAL",
            independent_recent_cycles=len(recent),
            required_cycles=3,
            latest_measurement_age_seconds=latest_age,
            forecast_age_seconds=forecast_age,
            rejected=rejected,
            latest_reference_alignment_missing=missing_latest_alignment,
        ),
        weather_gate=bool(
            not stale
            and not missing_latest_alignment
            and colder_persistent
            and low_cloud
            and confidence in {"FORECAST AT RISK", "FORECAST HIGH RISK"}
        ),
        validated_probability=None,
        empirical_predictive_confidence="NOT_VALIDATED",
        trading_instruction=False,
        quality="INSUFFICIENT DATA"
        if missing_latest_alignment
        else "STALE DATA"
        if stale
        else "AVAILABLE"
        if latest
        else "INSUFFICIENT DATA",
        temporal_policy="LATEST_FORECAST_RECEIVED_STRICTLY_BEFORE_EACH_METAR_NOMINAL_TIME; BOTH_EVENT_AND_RECEIPT_LE_DECISION; NO_FUTURE_CORRECTION",
    )
