"""EXP0013 offline as-of weather context from immutable read-only snapshots.

Full-history loading is deliberately an analysis operation, never a call from the
live weather writer. Current selection is not applied retrospectively. Historical
evaluation is an explicitly retrospective T-1minute reconstruction, not a live
forecast. Integer METAR maxima and offsets are quantized references, not precise
airport thermometer truth or the market's daily settlement maximum.
"""

import sqlite3
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from premetar.model import distance_to_boundary, icao_round_temperature
from premetar.pws.daily_time import local_day_bounds
from premetar.sources import STATIONS, next_report
from scripts.research.early_metar_data import (
    AIRPORTS,
    calibration,
    clock,
    latest,
    load_dataset,
    previous_reference,
)


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timezone-aware decision required")
    return value.astimezone(UTC)


def load_snapshot(snapshot: Path, cutoff: datetime) -> dict[str, Any]:
    """No migrations or transactions against the live database; mode=ro only."""
    at = aware(cutoff)
    conn = sqlite3.connect(snapshot.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        return load_dataset(conn, at)
    finally:
        conn.close()


def serial(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, dict):
        return {key: serial(item) for key, item in value.items()}
    if isinstance(value, list):
        return [serial(item) for item in value]
    return value


def _reports_before(data: dict[str, Any], at: datetime) -> list[dict[str, Any]]:
    return sorted(
        (
            report
            for report in data["reports"]
            if clock(report["first_received_utc"]) <= at
            and clock(report["observation_time_utc"]) <= at
        ),
        key=lambda r: (clock(r["observation_time_utc"]), clock(r["first_received_utc"])),
    )


def _day_reports(reports: list[dict[str, Any]], airport: str, at: datetime) -> list[dict[str, Any]]:
    zone = STATIONS[airport].timezone
    day = at.astimezone(ZoneInfo(zone)).date()
    start, end = local_day_bounds(day, zone)
    return [report for report in reports if start <= clock(report["observation_time_utc"]) < end]


def context_from_dataset(dataset: dict[str, Any], at: datetime) -> dict[str, Any]:
    """Every input must already be received; sensor selection stays per-instrument."""
    at = aware(at)
    result: dict[str, Any] = {}
    for airport in AIRPORTS:
        data = dataset[airport]
        reports = _reports_before(data, at)
        daily = _day_reports(reports, airport, at)
        eligible_daily = [
            r
            for r in daily
            if r.get("temperature_c") is not None
            and not r.get("startup_censored", True)
            and not r.get("coverage_gap", True)
        ]
        current = reports[-1] if reports else None
        previous = next(
            (
                r
                for r in reversed(reports[:-1])
                if current and r["observation_time_utc"] != current["observation_time_utc"]
            ),
            None,
        )
        last_increase, last_decrease = None, None
        previous_temperature: float | None = None
        for report in eligible_daily:
            temperature = float(report["temperature_c"])
            if previous_temperature is not None:
                if temperature > previous_temperature:
                    last_increase = report["observation_time_utc"]
                elif temperature < previous_temperature:
                    last_decrease = report["observation_time_utc"]
            previous_temperature = temperature
        target = next_report(STATIONS[airport], at)
        target_closed = any(
            r["_event"] == target and r["_closure"] <= at for r in data["references"]
        )
        baseline = previous_reference(data["references"], target, at)
        pws = []
        for sensor_id, sensor in sorted(data["sensors"].items()):
            reading = latest(sensor, at)
            if reading is None:
                continue
            params = calibration(sensor, "CAL-2", target, at)
            calibrated = float(reading["temperature_c"]) - params["offset_c"] if params else None
            predicted = icao_round_temperature(calibrated) if calibrated is not None else None
            baseline_integer = baseline["temperature_c"] if baseline else None
            pws.append(
                dict(
                    observation_id=reading["id"],
                    sensor_id=sensor_id,
                    station_id=sensor["station_id"],
                    provider=sensor.get("provider"),
                    measurement_time=reading["_event"],
                    first_receive=reading["_received"],
                    raw_temperature_c=reading["temperature_c"],
                    distance_km=sensor["distance_km"],
                    offset_c=params["offset_c"] if params else None,
                    calibrated_temperature_c=calibrated,
                    predicted_metar_integer=predicted,
                    previous_metar_integer=baseline_integer,
                    expected_change=(
                        predicted - baseline_integer
                        if predicted is not None and baseline_integer is not None
                        else None
                    ),
                    distance_to_integer_boundary=(
                        float(distance_to_boundary(calibrated)) if calibrated is not None else None
                    ),
                    calibration_n=params["calibration_n"] if params else 0,
                    calibration_kind=params.get("calibration_kind") if params else None,
                    calibration_history_available_by=(
                        params["history_available_by"] if params else None
                    ),
                    timestamp_provenance=reading["timestamp_provenance"],
                    qc_status=reading["qc_status"],
                    age_at_receipt_seconds=reading["age_seconds"],
                    prediction_eligible=params is not None and not target_closed,
                    status=(
                        "TARGET_ALREADY_RECEIVED"
                        if target_closed
                        else "CALIBRATED_RESEARCH_CANDIDATE"
                        if params
                        else "INSUFFICIENT_CALIBRATION_HISTORY"
                    ),
                )
            )
        result[airport] = dict(
            asof=at,
            latest_metar=current,
            previous_metar=previous,
            received_daily_metar_max=max(
                (r["temperature_c"] for r in eligible_daily), default=None
            ),
            maximum_semantics="RECEIVED_INTEGER_METAR_SPECI_SUBSET_NOT_SETTLEMENT_TMAX",
            last_increase=last_increase,
            last_decrease=last_decrease,
            next_nominal_metar=target,
            next_target_already_received=target_closed,
            pws=pws,
            diagnostics=dict(
                all_report_count=len(reports),
                local_day_report_count=len(daily),
                uncensored_daily_report_count=len(eligible_daily),
                known_temperature_sensors=len(data["sensors"]),
                fresh_eligible_sensors=len(pws),
                reference_exclusions=data["reference_exclusions"],
            ),
        )
    return serial(result)  # type: ignore[no-any-return]


def build_context(snapshot: Path, at: datetime) -> dict[str, Any]:
    return context_from_dataset(load_snapshot(snapshot, at), at)


def history_from_dataset(dataset: dict[str, Any], cutoff: datetime) -> dict[str, Any]:
    """Today's complete available timeline plus predeclared matched T-1m probes."""
    at = aware(cutoff)
    result: dict[str, Any] = {}
    for airport in AIRPORTS:
        data = dataset[airport]
        reports = _day_reports(_reports_before(data, at), airport, at)
        zone = STATIONS[airport].timezone
        start, end = local_day_bounds(at.astimezone(ZoneInfo(zone)).date(), zone)
        references = [
            r
            for r in data["references"]
            if start <= r["_event"] < end
            and r["_received"] <= at
            and not r.get("startup_censored", True)
            and not r.get("coverage_gap", True)
            and not r.get("_closure_censored", True)
            and r.get("_ambiguous_from") is None
        ]
        examples, rankings = [], []
        for sensor_id, sensor in sorted(data["sensors"].items()):
            counts: Counter[str] = Counter()
            for reference in references:
                target = reference["_event"]
                decision = target - timedelta(minutes=1)
                if decision >= reference["_closure"]:
                    counts["EARLY_REFERENCE_CLOSED_WINDOW"] += 1
                    continue
                reading = latest(sensor, decision)
                if reading is None:
                    counts["NO_ELIGIBLE_OBSERVATION"] += 1
                    continue
                params = calibration(sensor, "CAL-2", target, decision)
                if params is None:
                    counts["INSUFFICIENT_CALIBRATION_HISTORY"] += 1
                    continue
                previous = previous_reference(data["references"], target, decision)
                if previous is None:
                    counts["NO_AVAILABLE_BASELINE"] += 1
                    continue
                actual, baseline = reference["temperature_c"], previous["temperature_c"]
                calibrated = float(reading["temperature_c"]) - params["offset_c"]
                prediction = icao_round_temperature(calibrated)
                raw_prediction = icao_round_temperature(reading["temperature_c"])
                correct, persistence = prediction == actual, baseline == actual
                counts["eligible_cycles"] += 1
                counts["calibrated_correct"] += correct
                counts["raw_correct_same_cycles"] += raw_prediction == actual
                counts["persistence_correct_same_cycles"] += persistence
                counts["incremental_correct"] += correct and not persistence
                counts["incremental_harm"] += persistence and not correct
                counts["correct_changes"] += correct and actual != baseline
                counts["false_changes"] += prediction != baseline and actual == baseline
                examples.append(
                    dict(
                        airport=airport,
                        sensor_id=sensor_id,
                        station_id=sensor["station_id"],
                        target_time=target,
                        target_first_received=reference["_closure"],
                        decision=decision,
                        pws_measurement_time=reading["_event"],
                        pws_first_received=reading["_received"],
                        raw_temperature_c=reading["temperature_c"],
                        offset_c=params["offset_c"],
                        calibration_n=params["calibration_n"],
                        calibration_history_available_by=params["history_available_by"],
                        calibrated_temperature_c=calibrated,
                        predicted_metar_integer=prediction,
                        actual_metar_integer=actual,
                        previous_metar_integer=baseline,
                        correct=correct,
                        persistence_correct=persistence,
                        lead_seconds=(reference["_closure"] - decision).total_seconds(),
                        evidence_class="RETROSPECTIVE_AS_OF_RECONSTRUCTION",
                        checkpoint="T-1m",
                    )
                )
            rankings.append(
                dict(
                    sensor_id=sensor_id,
                    station_id=sensor["station_id"],
                    distance_km=sensor["distance_km"],
                    method="CAL-2_ROLLING_12H_MIN12",
                    checkpoint="T-1m",
                    counts=dict(counts),
                    net_improvement=counts["incremental_correct"] - counts["incremental_harm"],
                    evidence_class="RETROSPECTIVE_AS_OF_RECONSTRUCTION_NOT_LIVE_PREDICTIONS",
                )
            )
        result[airport] = dict(
            local_date=at.astimezone(ZoneInfo(zone)).date().isoformat(),
            day_start=start,
            day_end_exclusive=end,
            reports=reports,
            independent_routine_cycles=len(references),
            sensor_ranking=rankings,
            matched_examples=examples,
            interpretation="EXPLORATORY_MULTIPLE_SENSOR_SEARCH_NO_SELECTED_PROSPECTIVE_RULE",
        )
    return serial(result)  # type: ignore[no-any-return]


def history(snapshot: Path, cutoff: datetime) -> dict[str, Any]:
    return history_from_dataset(load_snapshot(snapshot, cutoff), cutoff)
