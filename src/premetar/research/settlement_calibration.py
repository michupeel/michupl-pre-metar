"""EXP0016.1 retrospective forecast/settlement joins, never production calibration.

One target day is an independent unit. Three checkpoints and related model runs
are repeated views, not extra meteorological events. Backfilled labels retain
their actual evidence receipt and cannot become historical information inputs.
"""

import csv
import hashlib
import json
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from statistics import mean, median
from typing import Any
from zoneinfo import ZoneInfo

from premetar.research.d1_forecasts import MODEL_SPECS, utc

ZONE = ZoneInfo("Europe/Warsaw")
VERSION = "EPWA-D1-SETTLEMENT-CALIBRATION-v1"
CHECKPOINTS = (6, 12, 18)
FULLY_VERIFIED = "VERIFIED_SOURCE_AND_MARKET"


def load_archived_runs(path: Path) -> list[dict[str, Any]]:
    """Read a bounded archive without creating/mutating the database."""
    if not path.is_file():
        return []
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.25) as conn:
        conn.execute("PRAGMA query_only=ON")
        rows = conn.execute(
            "SELECT id,received_at,payload,payload_hash FROM events "
            "WHERE kind='ARCHIVED_RUN' ORDER BY id LIMIT 5000"
        ).fetchall()
    runs = []
    for identity, received, encoded, digest in rows:
        raw = json.loads(encoded)
        runs.append(
            dict(
                raw,
                first_received=received,
                archive_event_id=identity,
                archive_payload_hash=digest,
                archive_path=str(path.resolve()),
            )
        )
    return runs


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def _first(raw: dict[str, Any], names: tuple[str, ...]) -> Any:
    return next((raw[k] for k in names if raw.get(k) is not None), None)


def _round_warmer(value: float) -> int:
    return int((Decimal(str(value)) + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR))


def _interval_error(value: float, integer: int) -> float:
    # Distance only: exact upper edge has zero infimum distance but maps warmer.
    return max(integer - 0.5 - value, 0.0, value - integer - 0.5)


def _normalize_run(raw: dict[str, Any]) -> dict[str, Any]:
    model = str(raw["model"])
    if model not in MODEL_SPECS:
        raise ValueError("UNSUPPORTED_MODEL")
    init = utc(raw["initialization_time"])
    receipt = utc(raw["first_received"])
    availability_class = raw.get("availability_class")
    publication = (
        utc(raw["publication_time"])
        if raw.get("publication_time") and raw.get("publication_verified") is True
        else None
    )
    if availability_class == "PROSPECTIVE_CAPTURED":
        available = receipt
        kind = "PROSPECTIVE_CAPTURED"
    elif (
        availability_class
        in {"VERIFIED_HISTORICAL_AVAILABILITY", "HISTORICAL_AVAILABILITY_VERIFIED"}
        and raw.get("availability_verified") is True
        and raw.get("availability_time")
    ):
        available = utc(raw["availability_time"])
        kind = "VERIFIED_HISTORICAL_AVAILABILITY"
    elif (
        availability_class == "APPROXIMATE_REPLAY"
        and raw.get("decision_assumption")
        == "INIT_PLUS_6H_SCENARIO_NOT_VERIFIED_ORIGINAL_AVAILABILITY"
    ):
        available = init + timedelta(hours=6)
        kind = "APPROXIMATE_REPLAY"
    else:
        raise ValueError("UNVERIFIED_OR_MISSING_FORECAST_AVAILABILITY")
    if receipt < init or available < init or publication and publication < init:
        raise ValueError("INVALID_RUN_CLOCKS")
    if publication and publication > available:
        raise ValueError("PUBLICATION_AFTER_CLAIMED_AVAILABILITY")
    points = {}
    for point in raw.get("points", []):
        stamp, temperature = utc(point["valid_time"]), _number(point.get("temperature_c"))
        if stamp in points:
            raise ValueError("DUPLICATE_FORECAST_VALID_TIME")
        if temperature is not None:
            if not -90 <= temperature <= 65:
                raise ValueError("IMPLAUSIBLE_FORECAST_TEMPERATURE")
            points[stamp] = temperature
    return dict(
        raw=raw,
        model=model,
        family=MODEL_SPECS[model]["family"],
        run_id=str(raw["run_id"]),
        init=init,
        receipt=receipt,
        publication=publication,
        available=available,
        availability_class=kind,
        points=points,
    )


def _target(raw: dict[str, Any], at: datetime) -> dict[str, Any]:
    day = date.fromisoformat(str(_first(raw, ("settlement_date", "day", "date"))))
    available = utc(
        _first(
            raw, ("target_available_at", "evidence_received_at", "first_received", "received_at")
        )
    )
    classification = str(_first(raw, ("classification", "status", "verification_status")))
    if classification not in {
        FULLY_VERIFIED,
        "VERIFIED_MARKET_ONLY",
        "SOURCE_RECONSTRUCTED",
        "CONFLICT",
        "INSUFFICIENT_EVIDENCE",
    }:
        raise ValueError("UNKNOWN_TARGET_CLASSIFICATION")
    if available > at:
        raise ValueError("TARGET_NOT_YET_AVAILABLE_TO_ANALYSIS")
    end = datetime.combine(day + timedelta(days=1), time.min, ZONE).astimezone(UTC)
    if end > at:
        raise ValueError("TARGET_DAY_NOT_FINISHED")
    maximum = _number(
        _first(raw, ("raw_maximum_c", "raw_max_c", "source_maximum_c", "qualifying_maximum_c"))
    )
    integer = _number(_first(raw, ("settlement_integer", "integer_outcome", "winning_integer")))
    if integer is not None and integer != int(integer):
        raise ValueError("NONINTEGER_SETTLEMENT_OUTCOME")
    if classification == FULLY_VERIFIED and (maximum is None or integer is None):
        raise ValueError("INCOMPLETE_FULLY_VERIFIED_TARGET")
    if classification == FULLY_VERIFIED and available < end:
        raise ValueError("FINAL_TARGET_CLAIMED_BEFORE_LOCAL_DAY_END")
    if (
        classification == FULLY_VERIFIED
        and maximum is not None
        and _round_warmer(maximum) != integer
    ):
        raise ValueError("CONFLICTING_FULLY_VERIFIED_TARGET")
    return dict(
        raw=raw,
        day=day,
        available=available,
        classification=classification,
        maximum=maximum,
        integer=int(integer) if integer is not None else None,
    )


def _forecast_day(run: dict[str, Any], day: date) -> dict[str, Any] | None:
    start = datetime.combine(day, time.min, ZONE).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, ZONE).astimezone(UTC)
    selected = {stamp: value for stamp, value in run["points"].items() if start <= stamp < end}
    # Exact local-day point coverage: includes both fallback02:00 observations.
    expected = {
        start + timedelta(hours=i) for i in range(int((end - start).total_seconds() / 3600))
    }
    complete = set(selected) == expected
    if not complete:
        return None
    maximum = max(selected.values())
    daily: dict[str, Any] = next(
        (d for d in run["raw"].get("days", []) if d.get("settlement_date") == day.isoformat()), {}
    )
    return dict(
        daily_api_tmax_c=_number(daily.get("daily_tmax_c")),
        hourly_point_max_c=maximum,
        forecast_tmax_times_utc=[
            stamp.isoformat() for stamp, value in sorted(selected.items()) if value == maximum
        ],
        forecast_valid_start=start.isoformat(),
        forecast_valid_end_exclusive=end.isoformat(),
        complete_hourly_day=True,
        expected_hourly_points=len(expected),
    )


def _disagreement(records: list[dict[str, Any]]) -> dict[str, Any]:
    """One predeclared checkpoint/day, grouped dependent families; descriptive only."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        if (
            row["checkpoint_local"] == "D-1 12:00 Europe/Warsaw"
            and row["target_classification"] == FULLY_VERIFIED
        ):
            groups[(row["availability_class"], row["settlement_date"])].append(row)
    days = []
    for (kind, day), group in sorted(groups.items()):
        families: dict[str, list[float]] = defaultdict(list)
        for row in group:
            families[row["family"]].append(row["hourly_point_max_c"])
        if len(families) < 2:
            continue
        values = [median(v) for v in families.values()]
        actual = group[0]["raw_qualifying_maximum_c"]
        days.append(
            dict(
                availability_class=kind,
                settlement_date=day,
                families=len(values),
                family_median_spread_c=max(values) - min(values),
                absolute_family_median_error_c=abs(median(values) - actual),
            )
        )
    summaries = []
    for kind in sorted({row["availability_class"] for row in days}):
        group = [r for r in days if r["availability_class"] == kind]
        high = [
            r["absolute_family_median_error_c"] for r in group if r["family_median_spread_c"] >= 2
        ]
        low = [
            r["absolute_family_median_error_c"] for r in group if r["family_median_spread_c"] < 2
        ]
        enough = len(group) >= 20 and len(high) >= 5 and len(low) >= 5
        summaries.append(
            dict(
                availability_class=kind,
                independent_days=len(group),
                status="DESCRIPTIVE_ONLY_NOT_CAUSAL"
                if enough
                else "INSUFFICIENT_MATCHED_INDEPENDENT_DAYS",
                frozen_split_spread_c=2.0,
                high_spread_days=len(high),
                low_spread_days=len(low),
                high_spread_MAE_c=mean(high) if enough else None,
                low_spread_MAE_c=mean(low) if enough else None,
            )
        )
    return dict(
        status="DESCRIPTIVE_ONLY_NOT_CAUSAL"
        if any(r["status"] == "DESCRIPTIVE_ONLY_NOT_CAUSAL" for r in summaries)
        else "INSUFFICIENT_MATCHED_INDEPENDENT_DAYS",
        checkpoint="D-1 12:00 Europe/Warsaw",
        unit="ONE_SETTLEMENT_DAY_PER_AVAILABILITY_CLASS_WITH_RELATED_FAMILIES_MEDIAN_GROUPED",
        days=days,
        summary=summaries,
    )


def evaluate(
    runs: list[dict[str, Any]], targets: list[dict[str, Any]], *, at: datetime
) -> dict[str, Any]:
    """Frozen D-1 06/12/18 local replay; no invented original public availability."""
    cutoff = utc(at)
    excluded: Counter[str] = Counter()
    normalized = []
    identities = set()
    for raw in runs:
        try:
            run = _normalize_run(raw)
            key = (run["model"], run["run_id"])
            if key in identities:
                excluded["DUPLICATE_RUN_ID"] += 1
                continue
            if run["receipt"] > cutoff:
                excluded["RUN_NOT_YET_CAPTURED_TO_ANALYSIS"] += 1
                continue
            identities.add(key)
            normalized.append(run)
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            excluded[str(error) if isinstance(error, ValueError) else "MALFORMED_RUN"] += 1
    normalized_targets: dict[date, dict[str, Any]] = {}
    conflicting_days = set()
    for raw in targets:
        try:
            target = _target(raw, cutoff)
            old = normalized_targets.get(target["day"])
            if old and (old["integer"], old["maximum"], old["classification"]) != (
                target["integer"],
                target["maximum"],
                target["classification"],
            ):
                conflicting_days.add(target["day"])
            elif old is None or target["available"] < old["available"]:
                normalized_targets[target["day"]] = target
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            excluded[str(error) if isinstance(error, ValueError) else "MALFORMED_TARGET"] += 1
    records = []
    for day, target in sorted(normalized_targets.items()):
        if day in conflicting_days or target["classification"] in {
            "CONFLICT",
            "INSUFFICIENT_EVIDENCE",
        }:
            excluded["CONFLICT_OR_INSUFFICIENT_TARGET_DAY"] += 1
            continue
        for checkpoint in CHECKPOINTS:
            decision = datetime.combine(day - timedelta(days=1), time(checkpoint), ZONE).astimezone(
                UTC
            )
            groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
            for run in normalized:
                if run["init"] <= decision and run["available"] <= decision:
                    groups[(run["model"], run["availability_class"])].append(run)
            for (model, availability_class), group in sorted(groups.items()):
                eligible = [(run, _forecast_day(run, day)) for run in group]
                eligible = [(run, forecast) for run, forecast in eligible if forecast is not None]
                if not eligible:
                    excluded["NO_COMPLETE_FORECAST_DAY_AT_CHECKPOINT"] += 1
                    continue
                run, forecast = max(
                    eligible,
                    key=lambda pair: (
                        pair[0]["init"],
                        pair[0]["available"],
                        (pair[1] or {}).get("daily_api_tmax_c") is not None,
                        pair[0]["run_id"],
                    ),
                )
                assert forecast is not None
                actual = target["maximum"]
                integer = target["integer"]
                peak = forecast["hourly_point_max_c"]
                daily = forecast["daily_api_tmax_c"]
                source_verified = target["classification"] == FULLY_VERIFIED
                strict = source_verified and availability_class != "APPROXIMATE_REPLAY"
                provenance = target["raw"].get("source_provenance", target["raw"].get("source_url"))
                record = dict(
                    version=VERSION,
                    analysis_kind="RETROSPECTIVE_AS_OF_RECONSTRUCTION",
                    model=model,
                    family=run["family"],
                    settlement_date=day.isoformat(),
                    checkpoint_local=f"D-1 {checkpoint:02}:00 Europe/Warsaw",
                    decision_time=decision.isoformat(),
                    run_id=run["run_id"],
                    initialization_time=run["init"].isoformat(),
                    original_publication_time=run["publication"].isoformat()
                    if run["publication"]
                    else None,
                    original_availability_time=run["available"].isoformat()
                    if availability_class != "APPROXIMATE_REPLAY"
                    else None,
                    assumed_availability_time=run["available"].isoformat()
                    if availability_class == "APPROXIMATE_REPLAY"
                    else None,
                    collector_first_received=run["receipt"].isoformat(),
                    availability_class=availability_class,
                    historical_availability_uncertainty=availability_class == "APPROXIMATE_REPLAY",
                    forecast_lead_to_day_start_hours=(
                        utc(forecast["forecast_valid_start"]) - run["init"]
                    ).total_seconds()
                    / 3600,
                    decision_lead_to_day_start_hours=(
                        utc(forecast["forecast_valid_start"]) - decision
                    ).total_seconds()
                    / 3600,
                    raw_qualifying_maximum_c=actual,
                    integer_outcome=integer,
                    target_classification=target["classification"],
                    target_available_at=target["available"].isoformat(),
                    target_known_at_historical_decision=target["available"] <= decision,
                    source_provenance=provenance,
                    market_event_id=target["raw"].get(
                        "market_event_id", target["raw"].get("event_id")
                    ),
                    forecast_raw_payload_hash=run["raw"].get(
                        "raw_payload_hash", run["raw"].get("archive_payload_hash")
                    ),
                    strict_calibration_pair=strict,
                    **forecast,
                    hourly_point_error_c=peak - actual if actual is not None else None,
                    daily_api_error_c=daily - actual
                    if daily is not None and actual is not None
                    else None,
                    source_error_scope="VERIFIED_FINAL_SOURCE"
                    if source_verified
                    else "EXPLORATORY_RECONSTRUCTED_SOURCE_NOT_FINAL",
                    hourly_point_integer_prediction=_round_warmer(peak),
                    hourly_point_integer_match=_round_warmer(peak) == integer
                    if integer is not None
                    else None,
                    daily_api_integer_prediction=_round_warmer(daily)
                    if daily is not None
                    else None,
                    daily_api_integer_match=_round_warmer(daily) == integer
                    if daily is not None and integer is not None
                    else None,
                    hourly_point_interval_error_c=_interval_error(peak, integer)
                    if integer is not None
                    else None,
                )
                records.append(record)
    summaries = []
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        grouped[
            (
                row["model"],
                row["availability_class"],
                row["target_classification"],
                row["checkpoint_local"],
            )
        ].append(row)
    for (model, kind, classification, checkpoint_label), group in sorted(grouped.items()):
        errors = [r["hourly_point_error_c"] for r in group if r["hourly_point_error_c"] is not None]
        daily_errors = [r["daily_api_error_c"] for r in group if r["daily_api_error_c"] is not None]
        matches = [
            r["hourly_point_integer_match"]
            for r in group
            if r["hourly_point_integer_match"] is not None
        ]
        summaries.append(
            dict(
                model=model,
                availability_class=kind,
                target_classification=classification,
                checkpoint_local=checkpoint_label,
                independent_days=len({r["settlement_date"] for r in group}),
                hourly_point_MAE_c=mean(abs(e) for e in errors) if errors else None,
                hourly_point_bias_c=mean(errors) if errors else None,
                hourly_point_median_error_c=median(errors) if errors else None,
                daily_api_MAE_c=mean(abs(e) for e in daily_errors) if daily_errors else None,
                daily_api_bias_c=mean(daily_errors) if daily_errors else None,
                hourly_point_integer_accuracy=mean(matches) if matches else None,
            )
        )
    verified_days = {
        d.isoformat()
        for d, t in normalized_targets.items()
        if t["classification"] == FULLY_VERIFIED and d not in conflicting_days
    }
    strict_days = {r["settlement_date"] for r in records if r["strict_calibration_pair"]}
    independent_pairs = {
        (r["model"], r["settlement_date"]) for r in records if r["strict_calibration_pair"]
    }
    return dict(
        version=VERSION,
        analysis_cutoff=cutoff.isoformat(),
        records=records,
        summary=summaries,
        exclusions=dict(sorted(excluded.items())),
        archived_unique_runs=len({(r["model"], r["init"]) for r in normalized}),
        archived_run_captures=len(normalized),
        approximate_verified_model_day_pairs=len(
            {
                (r["model"], r["settlement_date"])
                for r in records
                if r["availability_class"] == "APPROXIMATE_REPLAY"
                and r["target_classification"] == FULLY_VERIFIED
            }
        ),
        target_days=len(normalized_targets),
        verified_target_days=len(verified_days),
        verified_dates=sorted(verified_days),
        strict_pair_days=len(strict_days),
        strict_independent_model_day_pairs=len(independent_pairs),
        approximate_replay_model_day_pairs=len(
            {
                (r["model"], r["settlement_date"])
                for r in records
                if r["availability_class"] == "APPROXIMATE_REPLAY"
            }
        ),
        progress=dict(
            verified_days=len(verified_days),
            required_training_days=30,
            required_independent_validation_days=20,
            status="CALIBRATION_PENDING",
            probability=None,
            promotion=False,
        ),
        model_disagreement=_disagreement(records),
        limitations=[
            "Daily API maximum is NULL when archive supplies only hourly point forecasts; no silent substitution.",
            "Approximate original availability is never prospective evidence. Backfilled labels are retrospective outcomes only.",
            "Multiple checkpoints and correlated models do not multiply independent settlement-day sample size.",
            "No probability estimate or strategy promotion from this join.",
        ],
    )


def export(result: dict[str, Any], directory: Path) -> dict[str, str]:
    """Stable JSON/CSV serialization; no wall clock or live requests."""
    directory.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name in ("records", "summary"):
        path = directory / f"forecast_settlement_{name}.csv"
        rows = result[name]
        fields = sorted({k for r in rows for k in r}) or ["status"]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        k: json.dumps(v, sort_keys=True) if isinstance(v, (list, dict)) else v
                        for k, v in row.items()
                    }
                )
        paths[name] = str(path)
    path = directory / "forecast_settlement_calibration.json"
    path.write_text(
        json.dumps(result, sort_keys=True, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    paths["json"] = str(path)
    paths["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return paths
