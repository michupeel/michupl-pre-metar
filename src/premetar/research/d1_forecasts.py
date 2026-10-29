"""EXP0016 pure forecast normalization and guarded empirical calibration.

HTTP bytes must be durable before calling this module. The live forecast API
does not identify original run/publication clocks; generationtime_ms is neither.
"""

import hashlib
import json
import math
from datetime import UTC, date, datetime, time, timedelta
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Europe/Warsaw")
VERSION = "EXP0016-EMPIRICAL-v1"
MODEL_SPECS: dict[str, dict[str, str]] = {
    "icon_global": {"label": "ICON Global", "family": "DWD_ICON"},
    "icon_eu": {"label": "ICON Europe", "family": "DWD_ICON"},
    "ecmwf_ifs": {"label": "ECMWF IFS", "family": "ECMWF"},
    "ecmwf_aifs025_single": {"label": "ECMWF AIFS", "family": "ECMWF"},
    "gfs_global": {"label": "GFS Global", "family": "NOAA_GFS"},
}


def utc(value: datetime | str) -> datetime:
    result = (
        datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    )
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Timezone-aware timestamp required")
    return result.astimezone(UTC)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and -90 <= value <= 65 else None


def _epoch(value: Any) -> datetime:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Expected epoch seconds")
    try:
        return datetime.fromtimestamp(value, UTC)
    except (OverflowError, OSError) as error:
        raise ValueError("Invalid epoch seconds") from error


def _array(block: dict[str, Any], variable: str, model: str) -> list[Any]:
    value = block.get(f"{variable}_{model}", block.get(variable))
    if not isinstance(value, list):
        raise ValueError(f"Missing {variable} array for {model}")
    return value


def normalize_model(payload: dict[str, Any], model: str, received: datetime) -> dict[str, Any]:
    """Normalize a selected model, keeping API daily and hourly-point maxima separate."""
    stamp = utc(received)
    if model not in MODEL_SPECS:
        raise ValueError("Unsupported model")
    if payload.get("timezone") != ZONE.key:
        raise ValueError("Expected Europe/Warsaw daily aggregation")
    hourly, daily = payload.get("hourly"), payload.get("daily")
    hu, du = payload.get("hourly_units"), payload.get("daily_units")
    if not all(isinstance(item, dict) for item in (hourly, daily, hu, du)):
        raise ValueError("Missing hourly/daily blocks or units")
    assert isinstance(hourly, dict) and isinstance(daily, dict)
    assert isinstance(hu, dict) and isinstance(du, dict)
    if hu.get("time") != "unixtime" or du.get("time") != "unixtime":
        raise ValueError("Expected unambiguous epoch timestamps")
    for units, variable in ((hu, "temperature_2m"), (du, "temperature_2m_max")):
        if units.get(f"{variable}_{model}", units.get(variable)) != "°C":
            raise ValueError("Expected Celsius")
    ht, dt = hourly.get("time"), daily.get("time")
    hv, dv = _array(hourly, "temperature_2m", model), _array(daily, "temperature_2m_max", model)
    if (
        not isinstance(ht, list)
        or not isinstance(dt, list)
        or len(ht) != len(hv)
        or len(dt) != len(dv)
    ):
        raise ValueError("Mismatched forecast arrays")
    points: list[dict[str, Any]] = []
    previous = None
    for raw_time, raw_temperature in zip(ht, hv, strict=True):
        valid = _epoch(raw_time)
        if previous is not None and valid <= previous:
            raise ValueError("Duplicate or unordered forecast timestamp")
        if valid.minute or valid.second or valid.microsecond:
            raise ValueError("Expected hourly instant")
        previous = valid
        temperature = _number(raw_temperature)
        if raw_temperature is not None and temperature is None:
            raise ValueError("Invalid forecast temperature")
        if temperature is not None:
            points.append({"valid_time": valid.isoformat(), "temperature_c": temperature})
    days = []
    seen_days = set()
    for raw_time, raw_temperature in zip(dt, dv, strict=True):
        local = _epoch(raw_time).astimezone(ZONE)
        if local.time() != time(0):
            raise ValueError("Daily timestamp is not Warsaw midnight")
        day = local.date()
        if day in seen_days:
            raise ValueError("Duplicate daily timestamp")
        seen_days.add(day)
        start = datetime.combine(day, time(0), ZONE).astimezone(UTC)
        end = datetime.combine(day + timedelta(days=1), time(0), ZONE).astimezone(UTC)
        selected = [p for p in points if start <= utc(p["valid_time"]) < end]
        expected = int((end - start).total_seconds() / 3600)
        maximum = max((p["temperature_c"] for p in selected), default=None)
        daily_temperature = _number(raw_temperature)
        if raw_temperature is not None and daily_temperature is None:
            raise ValueError("Invalid daily maximum")
        days.append(
            {
                "settlement_date": day.isoformat(),
                "daily_tmax_c": daily_temperature,
                "daily_tmax_semantics": "OPEN_METEO_DAILY_TEMPERATURE_2M_MAX_NOT_OFFICIAL_SETTLEMENT",
                "hourly_point_max_c": maximum,
                "hourly_maximum_c": None,
                "peak_times_utc": [
                    p["valid_time"] for p in selected if p["temperature_c"] == maximum
                ],
                "expected_hours": expected,
                "available_hours": len(selected),
                "complete": len(selected) == expected,
                "start_utc": start.isoformat(),
                "end_utc": end.isoformat(),
            }
        )
    return {
        "model": model,
        **MODEL_SPECS[model],
        "first_received": stamp.isoformat(),
        "initialization_time": None,
        "publication_time": None,
        "run_provenance": "LIVE_API_RUN_UNIDENTIFIED",
        "availability_provenance": "FIRST_COLLECTOR_RECEIPT",
        "timezone": ZONE.key,
        "points": points,
        "days": days,
    }


def horizon_bucket(at: datetime, target_date: str) -> str:
    local = utc(at).astimezone(ZONE)
    difference = (date.fromisoformat(target_date) - local.date()).days
    if difference == 1:
        return (
            "D1_MORNING" if local.hour < 12 else "D1_AFTERNOON" if local.hour < 18 else "D1_EVENING"
        )
    if difference == 0:
        return "D0_MORNING" if local.hour < 12 else "D0_INTRADAY"
    return "UNSUPPORTED_HORIZON"


def consensus(forecasts: list[dict[str, Any]], target_date: str, at: datetime) -> dict[str, Any]:
    """Latest known snapshot/model; family medians are descriptive, never votes/probabilities."""
    cutoff = utc(at)
    latest: dict[str, dict[str, Any]] = {}
    for forecast in forecasts:
        model = forecast.get("model")
        if model not in MODEL_SPECS or utc(forecast["first_received"]) > cutoff:
            continue
        if model not in latest or utc(forecast["first_received"]) > utc(
            latest[model]["first_received"]
        ):
            latest[model] = forecast
    rows = []
    for model, forecast in sorted(latest.items()):
        day = next(
            (d for d in forecast.get("days", []) if d["settlement_date"] == target_date), None
        )
        if day is not None:
            previous = max(
                (
                    f
                    for f in forecasts
                    if f.get("model") == model
                    and utc(f["first_received"]) < utc(forecast["first_received"])
                    and any(d["settlement_date"] == target_date for d in f.get("days", []))
                ),
                key=lambda f: utc(f["first_received"]),
                default=None,
            )
            previous_day = next(
                (
                    d
                    for d in (previous or {}).get("days", [])
                    if d["settlement_date"] == target_date
                ),
                None,
            )
            delta = (
                day["daily_tmax_c"] - previous_day["daily_tmax_c"]
                if previous_day
                and day["daily_tmax_c"] is not None
                and previous_day["daily_tmax_c"] is not None
                else None
            )
            rows.append(
                {
                    **day,
                    "model": model,
                    **MODEL_SPECS[model],
                    "first_received": forecast["first_received"],
                    "initialization_time": forecast.get("initialization_time"),
                    "publication_time": forecast.get("publication_time"),
                    "age_seconds": (cutoff - utc(forecast["first_received"])).total_seconds(),
                    "revision_daily_tmax_c": delta,
                    "previous_first_received": previous.get("first_received") if previous else None,
                    "revision_semantics": "PREVIOUS_CAPTURED_SNAPSHOT_NOT_VERIFIED_MODEL_RUN_CHANGE",
                }
            )
    values = [r["daily_tmax_c"] for r in rows if r["daily_tmax_c"] is not None]
    families = {spec["family"] for spec in MODEL_SPECS.values()}
    family_medians = {
        family: median(
            [
                r["daily_tmax_c"]
                for r in rows
                if r["family"] == family and r["daily_tmax_c"] is not None
            ]
        )
        for family in families
        if any(r["family"] == family and r["daily_tmax_c"] is not None for r in rows)
    }
    return {
        "settlement_date": target_date,
        "asof": cutoff.isoformat(),
        "models": rows,
        "range_min_c": min(values) if values else None,
        "range_max_c": max(values) if values else None,
        "spread_c": max(values) - min(values) if values else None,
        "family_medians": family_medians,
        "family_count": len(family_medians),
        "missing_models": sorted(set(MODEL_SPECS) - {r["model"] for r in rows}),
        "status": "UNCALIBRATED" if values else "INSUFFICIENT_DATA",
        "probability": None,
    }


def _validated_artifact(
    validation: dict[str, Any] | None,
    selected: dict[str, dict[str, Any]],
    forecast: dict[str, Any],
    horizon: str,
    cutoff: datetime,
    target: date,
) -> bool:
    """Check frozen artifact identity and explicit disjoint chronological evidence.

    Hashes establish the frozen artifact/input identity, not independent truth of
    the caller's official-reference verification. Audit must retain those inputs.
    """
    if not validation:
        return False
    try:
        expected_hash = hashlib.sha256(
            json.dumps(
                {key: value for key, value in validation.items() if key != "artifact_hash"},
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()
        dates = validation["validation_dates"]
        if not isinstance(dates, list) or len(dates) != len(set(dates)) or len(dates) < 20:
            return False
        evaluation_days = sorted(date.fromisoformat(day) for day in dates)
        training_days = sorted(date.fromisoformat(day) for day in selected)
        evidence = validation["evaluation_evidence"]
        if not isinstance(evidence, dict) or set(evidence) != set(dates):
            return False
        if not (
            validation.get("passed") is True
            and validation.get("method") == "CHRONOLOGICAL_WALK_FORWARD"
            and validation.get("model") == forecast.get("model")
            and validation.get("horizon") == horizon
            and validation.get("reference_id") == forecast.get("reference_id")
            and isinstance(validation.get("audit_id"), str)
            and bool(validation["audit_id"].strip())
            and validation.get("artifact_hash") == expected_hash
            and validation.get("independent_evaluation_days") == len(dates)
            and sorted(validation["training_dates"]) == sorted(selected)
            and date.fromisoformat(validation["training_end_date"]) == training_days[-1]
            and training_days[-1] < evaluation_days[0]
            and date.fromisoformat(validation["evaluation_end_date"]) == evaluation_days[-1]
            and evaluation_days[-1] < target
            and utc(validation["available_at"]) < cutoff
        ):
            return False
        training_available = max(utc(row["settlement_received"]) for row in selected.values())
        last_receipt = None
        for day, row in evidence.items():
            forecast_receipt = utc(row["forecast_first_received"])
            settlement_receipt = utc(row["settlement_first_received"])
            day_end = datetime.combine(
                date.fromisoformat(day) + timedelta(days=1), time(0), ZONE
            ).astimezone(UTC)
            if not (
                row.get("official_settlement_verified") is True
                and row.get("reference_id") == forecast.get("reference_id")
                and horizon_bucket(forecast_receipt, day) == horizon
                and training_available < forecast_receipt < settlement_receipt
                and day_end <= settlement_receipt <= utc(validation["available_at"])
                and date.fromisoformat(row["fold_training_end_date"]) == training_days[-1]
                and all(
                    isinstance(row.get(key), str)
                    and len(row[key]) == 64
                    and all(c in "0123456789abcdef" for c in row[key])
                    for key in ("forecast_hash", "settlement_hash")
                )
            ):
                return False
            last_receipt = (
                max(last_receipt, settlement_receipt) if last_receipt else settlement_receipt
            )
        return bool(last_receipt and utc(validation["last_outcome_received"]) == last_receipt)
    except (KeyError, ValueError, TypeError, OverflowError):
        return False


def empirical_probability(
    history: list[dict[str, Any]],
    forecast: dict[str, Any],
    outcome: dict[str, Any],
    at: datetime,
    *,
    validation: dict[str, Any] | None = None,
    minimum_days: int = 30,
) -> dict[str, Any]:
    """Empirical daily residual distribution, guarded by causal independent validation.

    History schema is documented in EXP0016_FORECAST_SOURCES. Daily API maximum
    is the only forecast target accepted here; no routine METAR maximum fallback.
    Validation is a separate frozen walk-forward artifact, not a training score.
    """
    cutoff = utc(at)
    target = date.fromisoformat(forecast["settlement_date"])
    horizon = horizon_bucket(cutoff, target.isoformat())
    result: dict[str, Any] = {
        "version": VERSION,
        "status": "INSUFFICIENT_HISTORY",
        "sample_days": 0,
        "yes_probability": None,
        "no_probability": None,
        "uncertainty_interval": None,
        "horizon": horizon,
        "training_dates": [],
    }
    if utc(forecast["first_received"]) > cutoff or horizon == "UNSUPPORTED_HORIZON":
        result["status"] = "INVALID_FORECAST_AVAILABILITY"
        return result
    if outcome.get("rounding") != "NEAREST_TIES_WARMER" or outcome.get("kind") not in {
        "EXACT",
        "AT_MOST",
        "AT_LEAST",
    }:
        result["status"] = "UNVERIFIED_OUTCOME_SEMANTICS"
        return result
    value = _number(outcome.get("value_c"))
    predicted = _number(forecast.get("daily_tmax_c"))
    if value is None or value != int(value) or predicted is None:
        result["status"] = "INVALID_TEMPERATURE"
        return result
    selected: dict[str, dict[str, Any]] = {}
    for row in history:
        try:
            day = date.fromisoformat(row["settlement_date"])
            receipt = utc(row["forecast_first_received"])
            if not (
                day < target
                and utc(row["settlement_received"]) < cutoff
                and receipt < cutoff
                and row.get("official_settlement_verified") is True
                and row.get("reference_id")
                and row.get("reference_id") == forecast.get("reference_id")
                and row.get("model") == forecast.get("model")
                and row.get("target_semantics") == "DAILY_API_MAX"
                and row.get("availability_provenance") == "FIRST_COLLECTOR_RECEIPT"
                and row.get("run_provenance") in {"ORIGINAL_ARCHIVED_RUN", "PROSPECTIVE_CAPTURE"}
                and horizon_bucket(receipt, day.isoformat()) == horizon
                and _number(row.get("forecast_tmax_c")) is not None
                and _number(row.get("settlement_tmax_c")) is not None
            ):
                continue
            if row.get("run_provenance") == "ORIGINAL_ARCHIVED_RUN" and (
                not row.get("initialization_time") or utc(row["initialization_time"]) > receipt
            ):
                continue
            if str(day) not in selected or receipt > utc(
                selected[str(day)]["forecast_first_received"]
            ):
                selected[str(day)] = row
        except (KeyError, ValueError, TypeError):
            continue
    result.update(sample_days=len(selected), training_dates=sorted(selected))
    if len(selected) < max(30, minimum_days):
        return result
    validated = _validated_artifact(validation, selected, forecast, horizon, cutoff, target)
    if not validated:
        result["status"] = "VALIDATION_PENDING"
        return result
    residuals = [
        float(row["settlement_tmax_c"]) - float(row["forecast_tmax_c"]) for row in selected.values()
    ]
    reconstructed = [math.floor(predicted + residual + 0.5) for residual in residuals]
    hits = sum(
        (
            sample == value
            if outcome["kind"] == "EXACT"
            else sample <= value
            if outcome["kind"] == "AT_MOST"
            else sample >= value
        )
        for sample in reconstructed
    )
    probability = hits / len(reconstructed)
    result.update(
        status="CALIBRATED_EMPIRICAL",
        yes_probability=probability,
        no_probability=1 - probability,
        median_error_c=median(residuals),
        uncertainty_status="NOT_ESTIMATED_DAY_DEPENDENCE_REQUIRES_BLOCK_VALIDATION",
    )
    return result
