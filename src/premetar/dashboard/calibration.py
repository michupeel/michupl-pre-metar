"""Pure forward-only forecast calibration research, never a production model.

Hourly integer METAR agreement and final settlement Tmax calibration are separate
experiments. Retrospective approximate replay cannot certify historical access or
promote a calibrated dashboard Tmax. Rules are fixed, not outcome-optimized.
"""

import math
import random
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from statistics import mean, median
from typing import Any
from zoneinfo import ZoneInfo

from premetar.model import icao_round_temperature
from premetar.pws.analysis import interval_residual
from premetar.pws.daily_time import local_day_bounds

VERSION = "EPWA-FC-CAL-v1"
ZONE = ZoneInfo("Europe/Warsaw")
METHODS = ("RAW", "GLOBAL_MEDIAN", "HOUR_HORIZON_MEDIAN", "CAUSAL_NOWCAST")
CLASSES = {"APPROXIMATE_REPLAY", "PROSPECTIVE_CAPTURED"}


def _clock(value: Any) -> datetime:
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("TIMEZONE_UNKNOWN")
    return parsed.astimezone(UTC)


def _temperature(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError("NON_NUMERIC_TEMPERATURE")
    result = float(value)
    if not math.isfinite(result) or not -95 <= result <= 65:
        raise ValueError("IMPLAUSIBLE_TEMPERATURE")
    return result


def horizon_bin(hours: float) -> str:
    if hours < 0 or not math.isfinite(hours):
        raise ValueError("INVALID_HORIZON")
    return "0-6" if hours < 6 else "6-24" if hours < 24 else "24-48" if hours <= 48 else ">48"


def _runs(runs: list[dict[str, Any]], excluded: Counter[str]) -> list[dict[str, Any]]:
    result = []
    seen: set[str] = set()
    for raw in runs:
        try:
            model, identity = str(raw["model"]), str(raw["run_id"])
            init, received, decision = (
                _clock(raw[key])
                for key in ("initialization_time", "first_received", "decision_time")
            )
            availability = (
                _clock(raw["availability_time"]) if raw.get("availability_time") else None
            )
            kind = raw["availability_class"]
            if (
                not model
                or not identity
                or kind not in CLASSES
                or decision < init
                or (availability and decision < availability)
            ):
                raise ValueError("RUN_IDENTITY_OR_AVAILABILITY_INVALID")
            if kind == "PROSPECTIVE_CAPTURED" and decision < received:
                raise ValueError("FORECAST_NOT_YET_RECEIVED")
            if identity in seen:
                excluded["DUPLICATE_RUN_ID"] += 1
                continue
            points: dict[datetime, float] = {}
            for point in raw["points"]:
                event = _clock(point["valid_time"])
                if event in points:
                    raise ValueError("DUPLICATE_FORECAST_VALID_TIME")
                points[event] = _temperature(point["temperature_c"])
            seen.add(identity)
            result.append(
                dict(
                    model=model,
                    run_id=identity,
                    initialization=init,
                    received=received,
                    decision=decision,
                    availability=availability,
                    availability_class=kind,
                    points=points,
                    quality_flags=(
                        ["APPROXIMATE_AVAILABILITY_NOT_PROSPECTIVE"]
                        if kind == "APPROXIMATE_REPLAY"
                        else []
                    )
                    + (["PUBLICATION_TIME_UNKNOWN"] if availability is None else []),
                )
            )
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            excluded[str(error) if isinstance(error, ValueError) else "MALFORMED_RUN"] += 1
    return sorted(result, key=lambda row: (row["decision"], row["model"], row["run_id"]))


def _references(
    references: list[dict[str, Any]], excluded: Counter[str]
) -> dict[datetime, list[dict[str, Any]]]:
    groups: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, datetime]] = set()
    for raw in references:
        try:
            if raw.get("report_type") != "METAR" or raw.get("quantized") is not True:
                excluded["NON_ROUTINE_OR_NONQUANTIZED_REFERENCE"] += 1
                continue
            event, received = _clock(raw["observation_time_utc"]), _clock(raw["first_received_utc"])
            temperature = _temperature(raw["temperature_c"])
            if not temperature.is_integer():
                raise ValueError("NON_INTEGER_METAR_REFERENCE")
            identity = str(raw["report_identity"])
            key = (identity, received)
            if key in seen:
                continue
            seen.add(key)
            groups[event].append(
                dict(
                    event=event,
                    received=received,
                    temperature=int(temperature),
                    identity=identity,
                    correction=bool(raw.get("correction")),
                )
            )
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            excluded[str(error) if isinstance(error, ValueError) else "MALFORMED_REFERENCE"] += 1
    return {
        event: sorted(group, key=lambda r: (r["received"], r["correction"], r["identity"]))
        for event, group in groups.items()
    }


def _initial(group: list[dict[str, Any]]) -> dict[str, Any] | None:
    initial = [r for r in group if not r["correction"]]
    if not initial or len({r["temperature"] for r in initial}) != 1:
        return None
    return initial[0]


def _known(group: list[dict[str, Any]], at: datetime) -> dict[str, Any] | None:
    known = [r for r in group if r["event"] < at and r["received"] < at]
    if not known:
        return None
    initial = [r for r in known if not r["correction"]]
    corrections = [r for r in known if r["correction"]]
    if corrections:
        return max(corrections, key=lambda r: (r["received"], r["identity"]))
    return initial[-1] if initial and len({r["temperature"] for r in initial}) == 1 else None


def _training(
    run: dict[str, Any], prior: list[dict[str, Any]], refs: dict[datetime, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    # One latest prior forecast per independent nominal target. Multiple runs or
    # provider receipts cannot multiply the minimum calibration sample count.
    candidates: dict[datetime, dict[str, Any]] = {}
    for prediction in prior:
        if (
            prediction["model"] != run["model"]
            or prediction["availability_class"] != run["availability_class"]
            or prediction["decision"] >= run["decision"]
        ):
            continue
        target = prediction["target"]
        ref = _known(refs.get(target, []), run["decision"])
        if ref is None:
            continue
        old = candidates.get(target)
        if old is None or (
            prediction["decision"],
            -abs((prediction["valid"] - target).total_seconds()),
        ) > (old["decision"], -abs((old["valid"] - target).total_seconds())):
            candidates[target] = {
                **prediction,
                "reference": ref,
                "residual": prediction["raw"] - ref["temperature"],
            }
    return list(candidates.values())


def _correction(
    method: str,
    run: dict[str, Any],
    event: datetime,
    training: list[dict[str, Any]],
    refs: dict[datetime, list[dict[str, Any]]],
) -> dict[str, Any]:
    hours = (event - run["decision"]).total_seconds() / 3600
    selected = training
    minimum = 24
    if method == "HOUR_HORIZON_MEDIAN":
        selected = [
            p
            for p in training
            if p["valid"].astimezone(ZONE).hour == event.astimezone(ZONE).hour
            and horizon_bin((p["valid"] - p["decision"]).total_seconds() / 3600)
            == horizon_bin(hours)
        ]
        minimum = 12
    days = {p["target"].astimezone(ZONE).date() for p in selected}
    base: dict[str, Any] = dict(
        correction_c=0.0,
        fit_n=len(selected),
        fit_days=len(days),
        reference_ids=[p["reference"]["identity"] for p in selected],
        history_available_by=max((p["reference"]["received"] for p in selected), default=None),
        fallback_raw=False,
        reason="RAW",
        semantics="QUANTIZED_REFERENCE_MIDPOINT_ESTIMATE",
        reference_interval_ambiguity_c=[-0.5, 0.5],
    )
    if method == "RAW":
        return {
            **base,
            "fit_n": 0,
            "fit_days": 0,
            "reference_ids": [],
            "history_available_by": None,
        }
    if method == "CAUSAL_NOWCAST":
        known = [
            r
            for group in refs.values()
            if (r := _known(group, run["decision"])) is not None
            and 0 <= (run["decision"] - r["event"]).total_seconds() <= 7200
        ]
        ref = max(known, key=lambda r: r["event"], default=None)
        points = [
            (time, value)
            for time, value in run["points"].items()
            if ref is not None
            and time <= ref["event"]
            and (ref["event"] - time).total_seconds() <= 1800
        ]
        if ref is None or not points:
            return {
                **base,
                "fit_n": 0,
                "fit_days": 0,
                "reference_ids": [],
                "history_available_by": None,
                "fallback_raw": True,
                "reason": "NO_ALREADY_RECEIVED_NOWCAST_REFERENCE_OR_FORECAST_POINT",
            }
        time, value = max(points, key=lambda p: p[0])
        return {
            **base,
            "correction_c": 0.5 * (value - ref["temperature"]) * math.exp(-hours / 6),
            "fit_n": 1,
            "fit_days": 1,
            "reference_ids": [ref["identity"]],
            "history_available_by": ref["received"],
            "reason": "HALF_MIDPOINT_RESIDUAL_EXPONENTIAL_6H_DECAY",
            "nowcast_reference_event": ref["event"].isoformat(),
            "nowcast_forecast_valid": time.isoformat(),
        }
    if len(selected) < minimum or len(days) < 3:
        return {
            **base,
            "fallback_raw": True,
            "reason": f"INSUFFICIENT_HISTORY_MIN_{minimum}_TARGETS_3_DAYS",
        }
    return {
        **base,
        "correction_c": float(median(p["residual"] for p in selected)),
        "reason": "PAST_ONLY_QUANTIZED_MIDPOINT_MEDIAN",
    }


def _interval(values: list[tuple[str, float]]) -> dict[str, Any]:
    blocks: dict[str, list[float]] = defaultdict(list)
    for day, value in values:
        blocks[day].append(value)
    base: dict[str, Any] = dict(
        days=len(blocks), lower=None, upper=None, status="INSUFFICIENT_20_INDEPENDENT_DAYS"
    )
    if len(blocks) < 20:
        return base
    groups = list(blocks.values())
    rng = random.Random(20261028)
    samples = []
    for _ in range(2000):
        chosen = rng.choices(groups, k=len(groups))
        samples.append(sum(sum(group) for group in chosen) / sum(len(group) for group in chosen))
    samples.sort()
    return {
        **base,
        "lower": samples[49],
        "upper": samples[1949],
        "status": "DESCRIPTIVE_WARSAW_DAY_BLOCK_2000_SEED20261028",
    }


def _metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return dict(
            N=0,
            independent_targets=0,
            days=0,
            interval_mae=None,
            midpoint_mae=None,
            midpoint_bias=None,
            exact_integer_accuracy=None,
            raw_interval_mae_same_pairs=None,
            mean_interval_improvement=None,
            improvement_interval=_interval([]),
        )
    differences = [
        (r["local_day"], abs(r["raw_interval_residual_c"]) - abs(r["interval_residual_c"]))
        for r in records
    ]
    return dict(
        N=len(records),
        independent_targets=len({r["reference_nominal"] for r in records}),
        days=len({r["local_day"] for r in records}),
        interval_mae=mean(abs(r["interval_residual_c"]) for r in records),
        midpoint_mae=mean(abs(r["midpoint_error_c"]) for r in records),
        midpoint_bias=mean(r["midpoint_error_c"] for r in records),
        exact_integer_accuracy=mean(r["exact_integer_match"] for r in records),
        raw_interval_mae_same_pairs=mean(abs(r["raw_interval_residual_c"]) for r in records),
        raw_integer_accuracy_same_pairs=mean(r["raw_integer_match"] for r in records),
        incremental_correct=sum(
            r["exact_integer_match"] and not r["raw_integer_match"] for r in records
        ),
        incremental_harm=sum(
            r["raw_integer_match"] and not r["exact_integer_match"] for r in records
        ),
        mean_interval_improvement=mean(value for _, value in differences),
        improvement_interval=_interval(differences),
        fallback_raw_count=sum(r["fallback_raw"] for r in records),
        continuous_error_semantics="METAR_INTEGER_MIDPOINT_DIFFERENCE_NOT_EXACT_THERMOMETER_ERROR",
    )


def _serial(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return [_serial(v) for v in value]
    if isinstance(value, dict):
        return {k: _serial(v) for k, v in value.items()}
    return value


def _daily(
    runs: list[dict[str, Any]], targets: list[dict[str, Any]], excluded: Counter[str]
) -> dict[str, Any]:
    references: dict[date, dict[str, Any]] = {}
    for raw in targets:
        try:
            status = raw.get("status", raw.get("reference_status", raw.get("reference_kind")))
            if status != "VERIFIED_SETTLEMENT_REFERENCE_FINAL":
                excluded["DAILY_REFERENCE_NOT_VERIFIED_FINAL"] += 1
                continue
            day = date.fromisoformat(str(raw["day"]))
            available = _clock(raw["available_at"])
            if available < local_day_bounds(day, "Europe/Warsaw")[1]:
                raise ValueError("FINAL_DAILY_REFERENCE_BEFORE_DAY_END")
            temperature = _temperature(raw["temperature_c"])
            rounded = raw["rounded_integer"]
            if isinstance(rounded, bool) or not isinstance(rounded, int):
                raise ValueError("DAILY_ROUNDING_REFERENCE_UNKNOWN")
            peak = _clock(raw["peak_time"]) if raw.get("peak_time") else None
            start, end = local_day_bounds(day, "Europe/Warsaw")
            if peak is not None and not start <= peak < end:
                raise ValueError("DAILY_PEAK_OUTSIDE_LOCAL_DAY")
            # Multiple final versions with different values cannot silently overwrite.
            if day in references and references[day]["temperature"] != temperature:
                excluded["CONFLICTING_FINAL_DAILY_REFERENCE"] += 1
                references[day]["conflict"] = True
            elif day not in references:
                references[day] = dict(
                    temperature=temperature,
                    rounded=rounded,
                    available=available,
                    peak=peak,
                    conflict=False,
                )
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            excluded[
                str(error) if isinstance(error, ValueError) else "MALFORMED_DAILY_REFERENCE"
            ] += 1
    references = {day: row for day, row in references.items() if not row["conflict"]}
    prior: list[dict[str, Any]] = []
    records = []
    previews = []
    for run in runs:
        groups: dict[date, list[tuple[datetime, float]]] = defaultdict(list)
        for valid, temp in run["points"].items():
            groups[valid.astimezone(ZONE).date()].append((valid, temp))
        for day, points in sorted(groups.items()):
            start, end = local_day_bounds(day, "Europe/Warsaw")
            expected = {
                start + timedelta(hours=h) for h in range(int((end - start).total_seconds() / 3600))
            }
            if start < run["decision"] or {time for time, _ in points} != expected:
                continue
            rawmax = max(value for _, value in points)
            known: dict[date, dict[str, Any]] = {}
            for old in prior:
                ref = references.get(old["day"])
                if (
                    old["model"] != run["model"]
                    or old["availability_class"] != run["availability_class"]
                    or old["decision"] >= run["decision"]
                    or ref is None
                    or ref["available"] >= run["decision"]
                    or old["day"] >= day
                ):
                    continue
                if old["day"] not in known or old["decision"] > known[old["day"]]["decision"]:
                    known[old["day"]] = old
            n = len(known)
            correction = (
                float(
                    median(
                        old["raw_max"] - references[d]["temperature"] for d, old in known.items()
                    )
                )
                if n >= 14
                else 0.0
            )
            corrected = rawmax - correction
            preview = dict(
                model=run["model"],
                run_id=run["run_id"],
                availability_class=run["availability_class"],
                day=day.isoformat(),
                decision_time=run["decision"].isoformat(),
                raw_sampled_hourly_max=rawmax,
                forecast_peak_times=[time.isoformat() for time, value in points if value == rawmax],
                training_days=n,
                correction_c=correction,
                experimental_corrected_tmax=corrected if n >= 14 else None,
                semantics="SAMPLED_HOURLY_POINT_MAX_CALIBRATED_AGAINST_SEPARATE_FINAL_DAILY_REFERENCE",
            )
            previews.append(preview)
            ref = references.get(day)
            if ref and ref["available"] > run["decision"]:
                records.append(
                    {
                        **preview,
                        "observed_final_tmax": ref["temperature"],
                        "reference_available_at": ref["available"].isoformat(),
                        "raw_error_c": rawmax - ref["temperature"],
                        "corrected_error_c": corrected - ref["temperature"] if n >= 14 else None,
                        "out_of_sample": n >= 14,
                        "rounded_reference_integer": ref["rounded"],
                        "observed_peak_time": ref["peak"].isoformat() if ref["peak"] else None,
                        "raw_integer_match": icao_round_temperature(rawmax) == ref["rounded"],
                        "calibrated_integer_match": icao_round_temperature(corrected)
                        == ref["rounded"]
                        if n >= 14
                        else None,
                        "peak_timing_error_minutes": min(
                            abs((time - ref["peak"]).total_seconds()) / 60
                            for time, value in points
                            if value == rawmax
                        )
                        if ref["peak"]
                        else None,
                    }
                )
            prior.append(
                dict(
                    model=run["model"],
                    availability_class=run["availability_class"],
                    day=day,
                    decision=run["decision"],
                    raw_max=rawmax,
                )
            )
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        if row["out_of_sample"]:
            grouped[(row["model"], row["availability_class"])].append(row)
    summaries = []
    promoted: dict[str, datetime] = {}
    for (model, kind), group in sorted(grouped.items()):
        # One evaluation per day: latest fixed pre-day forecast, never lowest error.
        byday = {}
        for row in sorted(group, key=lambda r: r["decision_time"]):
            byday[row["day"]] = row
        values = list(byday.values())
        improvement = mean(abs(r["raw_error_c"]) - abs(r["corrected_error_c"]) for r in values)
        eligible = kind == "PROSPECTIVE_CAPTURED" and len(values) >= 7 and improvement > 0
        summaries.append(
            dict(
                model=model,
                availability_class=kind,
                out_of_sample_days=len(values),
                raw_mae=mean(abs(r["raw_error_c"]) for r in values),
                calibrated_mae=mean(abs(r["corrected_error_c"]) for r in values),
                paired_mae_improvement=improvement,
                improvement_interval=_interval(
                    [
                        (r["day"], abs(r["raw_error_c"]) - abs(r["corrected_error_c"]))
                        for r in values
                    ]
                ),
                promotion_eligible=eligible,
                bias_c=mean(r["corrected_error_c"] for r in values),
                raw_integer_accuracy=mean(r["raw_integer_match"] for r in values),
                calibrated_integer_accuracy=mean(r["calibrated_integer_match"] for r in values),
                forecast_tmax_timing_mae_minutes=mean(
                    r["peak_timing_error_minutes"]
                    for r in values
                    if r["peak_timing_error_minutes"] is not None
                )
                if any(r["peak_timing_error_minutes"] is not None for r in values)
                else None,
                validation_available_at=max(r["reference_available_at"] for r in values),
            )
        )
        if eligible:
            promoted[model] = max(_clock(r["reference_available_at"]) for r in values)
    latest = max(
        (
            r
            for r in previews
            if r["model"] in promoted
            and _clock(r["decision_time"]) > promoted[r["model"]]
            and r["availability_class"] == "PROSPECTIVE_CAPTURED"
            and r["training_days"] >= 14
        ),
        key=lambda r: r["decision_time"],
        default=None,
    )
    return dict(
        status="EXPERIMENTAL_PROSPECTIVE_CALIBRATION" if latest else "CALIBRATION_PENDING",
        calibrated_tmax=latest["experimental_corrected_tmax"] if latest else None,
        selected_model=latest["model"] if latest else None,
        verified_reference_days=len(references),
        records=records,
        previews=previews[-100:],
        summary=summaries,
        minimum_training_days=14,
        minimum_out_of_sample_days=7,
        minimum_uncertainty_days=20,
        reason="PROSPECTIVE_PAIRED_IMPROVEMENT_WITH_FINAL_DAILY_REFERENCES"
        if latest
        else "REQUIRES_VERIFIED_FINAL_DAILY_HISTORY_14_TRAINING_AND_7_PROSPECTIVE_OOS_DAYS_WITH_PAIRED_IMPROVEMENT",
        hourly_metar_max_used_as_daily_truth=False,
        approximate_replay_can_promote=False,
        uncertainty_note="No confidence interval before20independent local days; descriptive blocks do not establish significance or guaranteed Tmax.",
    )


def evaluate(
    runs: list[dict[str, Any]],
    references: list[dict[str, Any]],
    daily_targets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evaluate fixed causal methods on matched hourly targets; never train on target.

    PROSPECTIVE_CAPTURED requires actual first receipt <= decision. Archive replay
    can use a declared approximate decision clock, but stays a separate cohort.
    Temperatures are strict finite numeric Celsius; unknown clocks stay unknown.
    Midpoint-median was frozen BEFORE archive evaluation: interval-projection
    offsets land on excluded upper rounding boundaries under constant positive
    bias. No hidden epsilon or outcome-tuned rounding adjustment is introduced.
    Midpoint errors remain quantized-reference estimates, never exact truth.
    """
    excluded: Counter[str] = Counter()
    normalized = _runs(runs, excluded)
    refs = _references(references, excluded)
    initial = {event: row for event, group in refs.items() if (row := _initial(group)) is not None}
    excluded["AMBIGUOUS_OR_CORRECTION_ONLY_TARGETS"] += len(refs) - len(initial)
    first_observed: dict[datetime, dict[str, Any]] = {}
    for event, group in refs.items():
        first = next((r for r in group if not r["correction"]), None)
        if first is not None:
            first_observed[event] = first
    prior: list[dict[str, Any]] = []
    records = []
    for run in normalized:
        training = _training(run, prior, refs)
        current = []
        for event, raw in sorted(run["points"].items()):
            if event < run["decision"]:
                continue
            candidates = [
                ref
                for nominal, ref in first_observed.items()
                if abs((nominal - event).total_seconds()) <= 1200
                and nominal >= run["decision"]
                and ref["received"] > run["decision"]
            ]
            ref = min(
                candidates,
                key=lambda r: (abs((r["event"] - event).total_seconds()), -r["event"].timestamp()),
                default=None,
            )
            if ref is None:
                continue
            current.append(
                dict(
                    model=run["model"],
                    availability_class=run["availability_class"],
                    decision=run["decision"],
                    valid=event,
                    target=ref["event"],
                    raw=raw,
                )
            )
            # Future contradictions cannot retroactively remove a sample from
            # a prior decision's training; _known enforces contradiction timing.
            # Conflicted targets remain excluded from evaluation aggregates.
            if ref["event"] not in initial:
                continue
            for method in METHODS:
                parameters = _correction(method, run, event, training, refs)
                corrected = raw - parameters["correction_c"]
                horizon = (event - run["decision"]).total_seconds() / 3600
                records.append(
                    dict(
                        model=run["model"],
                        run_id=run["run_id"],
                        availability_class=run["availability_class"],
                        method=method,
                        initialization_time=run["initialization"].isoformat(),
                        first_received=run["received"].isoformat(),
                        decision_time=run["decision"].isoformat(),
                        availability_time=run["availability"].isoformat()
                        if run["availability"]
                        else None,
                        quality_flags=run["quality_flags"],
                        valid_time=event.isoformat(),
                        reference_nominal=ref["event"].isoformat(),
                        reference_first_received=ref["received"].isoformat(),
                        reference_id=ref["identity"],
                        actual_metar_integer=ref["temperature"],
                        reference_quantized=True,
                        local_day=ref["event"].astimezone(ZONE).date().isoformat(),
                        local_hour=event.astimezone(ZONE).hour,
                        horizon_hours=horizon,
                        horizon_bin=horizon_bin(horizon),
                        raw_temperature_c=raw,
                        calibrated_temperature_c=corrected,
                        predicted_metar_integer=icao_round_temperature(corrected),
                        exact_integer_match=icao_round_temperature(corrected) == ref["temperature"],
                        raw_integer_match=icao_round_temperature(raw) == ref["temperature"],
                        raw_interval_residual_c=interval_residual(raw, ref["temperature"]),
                        interval_residual_c=interval_residual(corrected, ref["temperature"]),
                        midpoint_error_c=corrected - ref["temperature"],
                        fallback_raw=parameters["fallback_raw"],
                        parameters=_serial(parameters),
                        target_semantics="INITIAL_ROUTINE_INTEGER_METAR_NOT_DAILY_TMAX",
                    )
                )
        # Prevent a later valid hour in the SAME run from training an earlier one.
        prior.extend(current)
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    daily_errors: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        groups[(row["model"], row["availability_class"], row["method"])].append(row)
        daily_errors[
            (row["model"], row["availability_class"], row["method"], row["local_day"])
        ].append(row)
    summaries = [
        dict(model=model, availability_class=kind, method=method, **_metrics(group))
        for (model, kind, method), group in sorted(groups.items())
    ]
    cross = []
    for kind in sorted(CLASSES):
        models = sorted({r["model"] for r in records if r["availability_class"] == kind})
        for method in METHODS:
            modelrows = {
                model: {
                    (r["decision_time"], r["valid_time"], r["reference_id"]): r
                    for r in records
                    if r["model"] == model
                    and r["availability_class"] == kind
                    and r["method"] == method
                }
                for model in models
            }
            common = (
                set.intersection(*(set(rows) for rows in modelrows.values()))
                if modelrows
                else set()
            )
            cross.append(
                dict(
                    availability_class=kind,
                    method=method,
                    models=models,
                    matched_target_decision_pairs=len(common),
                    model_metrics={
                        model: _metrics([rows[key] for key in sorted(common)])
                        for model, rows in modelrows.items()
                    },
                    semantics="EXACT_SAME_DECISION_VALID_TIME_AND_REFERENCE_PAIRS_NOT_DIFFERENT_HORIZONS",
                )
            )
    daily = _daily(normalized, daily_targets or [], excluded)
    return dict(
        version=VERSION,
        status=daily["status"],
        calibrated_tmax=daily["calibrated_tmax"],
        records=records,
        summary=summaries,
        daily=daily,
        daily_errors=[
            dict(
                model=model,
                availability_class=kind,
                method=method,
                local_day=day,
                **_metrics(group),
            )
            for (model, kind, method, day), group in sorted(daily_errors.items())
        ],
        matched_models=cross,
        exclusions=dict(excluded),
        run_count=len(normalized),
        independent_hourly_targets=len(initial),
        evaluated_independent_targets=len({row["reference_nominal"] for row in records}),
        hourly_record_count=len(records),
        methodology=dict(
            evaluation_reference="INITIAL_NON_COR_ROUTINE_INTEGER",
            training_reference="LATEST_UNAMBIGUOUS_OR_CORRECTION_ALREADY_RECEIVED_BEFORE_DECISION",
            forecast_reference_alignment_max_seconds=1200,
            global_minimum_targets=24,
            hour_horizon_minimum_targets=12,
            minimum_training_days=3,
            nowcast_reference_max_age_seconds=7200,
            nowcast_point_max_offset_seconds=1800,
            nowcast_shrinkage=0.5,
            nowcast_decay_hours=6,
            calibration_offset="QUANTIZED_REFERENCE_MIDPOINT_ESTIMATE_WITH_PLUS_MINUS_0.5_REFERENCE_AMBIGUITY",
            archive_replay_is_not_prospective=True,
            hourly_agreement_is_not_daily_tmax_validation=True,
        ),
    )
