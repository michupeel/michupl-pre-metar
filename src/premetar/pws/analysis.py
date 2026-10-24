"""Quantized-reference walk-forward analysis and immutable prospective predictions."""

import json
import math
import sqlite3
import statistics
import time
from datetime import datetime, timedelta
from statistics import mean, median
from typing import Any
from uuid import uuid4

from premetar.model import icao_round_temperature, utc_now
from premetar.pws.geometry import haversine_km
from premetar.pws.models import QCConfig, Station, utc
from premetar.pws.quality import effective_time, eligible
from premetar.pws.repository import inventory, readings, rows, selected

VERSION = "pws-estimator-1.1"


def precise_reference_comparison(
    connection: sqlite3.Connection, airport: str, station_id: str, config: QCConfig, at: datetime
) -> dict[str, Any]:
    """Separate conditional comparison to existing DWD 0.1C observations.

    This does not establish METAR sensor parity or treat 0.1C as exact truth.
    Calibration is evaluated chronologically, never used as METAR calibration.
    """
    references = rows(
        connection,
        """SELECT event_time,collector_receive_time,temperature_c,temperature_precision
        FROM observations WHERE station_icao=? AND product_type='DWD_10MIN'
        AND evidence_class='REALTIME_CAPTURED' AND temperature_c IS NOT NULL
        AND julianday(collector_receive_time)<=julianday(?)""",
        (airport, utc(at).isoformat()),
    )
    unique: dict[datetime, dict[str, Any]] = {}
    conflicted: set[datetime] = set()
    for ref in references:
        if not ref["collector_receive_time"] or datetime.fromisoformat(
            ref["collector_receive_time"]
        ) > utc(at):
            continue
        event = datetime.fromisoformat(ref["event_time"])
        if event in unique and ref["temperature_c"] != unique[event]["temperature_c"]:
            conflicted.add(event)
        if event not in unique or datetime.fromisoformat(
            ref["collector_receive_time"]
        ) < datetime.fromisoformat(unique[event]["collector_receive_time"]):
            unique[event] = ref
    pairs: list[dict[str, Any]] = []
    calibrated_errors: list[float] = []
    for event, ref in sorted(unique.items()):
        if event in conflicted:
            continue
        snapshot = station_at(connection, station_id, airport, event)
        if not snapshot:
            continue
        candidate = latest_station_reading(
            connection, Station.model_validate_json(snapshot["data_json"]), event, config
        )
        if not candidate or not candidate.get("observation_time"):
            continue
        offset = (event - datetime.fromisoformat(candidate["observation_time"])).total_seconds()
        if not 0 <= offset <= 300:
            continue
        error = candidate["temperature_c"] - ref["temperature_c"]
        prior = [p for p in pairs if p["available"] < event][-config.calibration_window :]
        if len(prior) >= config.calibration_minimum:
            bias = (median if config.calibration_method == "median" else mean)(
                p["error"] for p in prior
            )
            calibrated_errors.append(error - bias)
        pairs.append(
            {"error": error, "available": datetime.fromisoformat(ref["collector_receive_time"])}
        )
    enough = len(pairs) >= config.calibration_minimum
    return {
        "reference_kind": "DWD_10MIN_APPROXIMATE_0.1C",
        "sensor_parity": "UNVERIFIED",
        "sample_count": len(pairs),
        "max_observation_offset_seconds": 300,
        "raw_bias_estimate_c": mean(p["error"] for p in pairs) if enough else None,
        "raw_mae_c": mean(abs(p["error"]) for p in pairs) if enough else None,
        "calibrated_oos_sample_count": len(calibrated_errors),
        "calibrated_oos_mae_c": mean(abs(e) for e in calibrated_errors)
        if len(calibrated_errors) >= config.calibration_minimum
        else None,
        "conclusion": "CONDITIONAL_PRECISE_REFERENCE_COMPARISON" if enough else "INSUFFICIENT DATA",
    }


def interval_residual(value: float, metar_integer: int) -> float:
    """Signed distance to [integer-.5, integer+.5); infimum at open upper end.

    Zero distance at the upper endpoint does NOT mean an integer match.
    This is an interval-projection estimate, never an exact continuous bias.
    """
    if not math.isfinite(value):
        raise ValueError("Nonfinite input")
    return value - min(max(value, metar_integer - 0.5), metar_integer + 0.5)


def correction(pairs: list[dict[str, Any]], decision: datetime, config: QCConfig) -> float | None:
    prior = [
        p
        for p in pairs
        if datetime.fromisoformat(p["label_available_at"]) < decision
        and datetime.fromisoformat(p["target_time"]) < decision
    ]
    prior = sorted(prior, key=lambda p: p["target_time"])[-config.calibration_window :]
    if len(prior) < config.calibration_minimum:
        return None
    residuals = [interval_residual(p["temperature_c"], p["actual_integer"]) for p in prior]
    return float((median if config.calibration_method == "median" else mean)(residuals))


def walk_forward(pairs: list[dict[str, Any]], config: QCConfig) -> dict[str, Any]:
    evaluated = []
    for pair in sorted(pairs, key=lambda p: p["decision_time"]):
        decision = datetime.fromisoformat(pair["decision_time"])
        bias = correction(pairs, decision, config)
        if bias is None:
            continue
        actual, raw = pair["actual_integer"], pair["temperature_c"]
        calibrated = raw - bias
        evaluated.append(
            {
                **pair,
                "bias": bias,
                "calibrated": calibrated,
                "raw_match": icao_round_temperature(raw) == actual,
                "calibrated_match": icao_round_temperature(calibrated) == actual,
                "baseline_match": pair.get("baseline_integer") == actual
                if pair.get("baseline_integer") is not None
                else None,
                "interval_error": abs(interval_residual(calibrated, actual)),
            }
        )
    n = len(evaluated)
    comparable = [p for p in evaluated if p["baseline_match"] is not None]
    return {
        "sample_count": n,
        "evaluation_days": len({p["target_time"][:10] for p in evaluated}),
        "raw_integer_match_rate": mean(p["raw_match"] for p in evaluated) if n else None,
        "integer_metar_match_rate": mean(p["calibrated_match"] for p in evaluated) if n else None,
        "interval_aware_error": mean(p["interval_error"] for p in evaluated) if n else None,
        "baseline_match_rate": mean(p["baseline_match"] for p in comparable)
        if comparable
        else None,
        "incremental_match_rate": mean(
            int(p["calibrated_match"]) - int(p["baseline_match"]) for p in comparable
        )
        if comparable
        else None,
        "calibration_label": "QUANTIZED_INTERVAL_PROJECTION",
        "evaluation": "CHRONOLOGICAL_EXPLORATORY",
        "rows": evaluated,
    }


def station_at(
    connection: sqlite3.Connection, station_id: str, airport: str, at: datetime
) -> dict[str, Any] | None:
    found = rows(
        connection,
        """SELECT * FROM pws_discoveries WHERE station_id=? AND airport_icao=? AND at<=?
        ORDER BY at DESC,id DESC LIMIT 1""",
        (station_id, airport, at.isoformat()),
    )
    return found[0] if found else None


def latest_station_reading(
    connection: sqlite3.Connection, station: Station, at: datetime, config: QCConfig
) -> dict[str, Any] | None:
    if station.exposure == "indoor" or station.mobile or not station.sensors:
        return None
    data = readings(connection, station.station_id, at)
    # Stable sensor choice prevents choosing by proximity to the target outcome.
    sensor = min(s.provider_sensor_id for s in station.sensors)
    candidates = [r for r in data if r["provider_sensor_id"] == sensor and eligible(r, at, config)]
    if not candidates:
        return None
    latest = max(
        candidates,
        key=lambda r: (
            effective_time(r),
            r["first_receive_time"],
        ),
    )
    same_time = [r for r in candidates if effective_time(r) == effective_time(latest)]
    if len({r["temperature_c"] for r in same_time}) > 1:
        return None
    return latest


def make_pairs(
    connection: sqlite3.Connection,
    airport: str,
    station_id: str,
    config: QCConfig,
    at: datetime,
    lead_seconds: int = 600,
) -> list[dict[str, Any]]:
    # Reuse existing METAR observations/receipts, never collect another reference.
    references = rows(
        connection,
        """SELECT o.identity,o.event_time,o.temperature_c,o.data_json,
        rr.collector_receive_time available FROM observations o
        JOIN report_receipts rr ON rr.observation_id=o.id
        WHERE o.station_icao=? AND o.product_type='METAR' AND o.evidence_class='REALTIME_CAPTURED'
        AND o.startup_censored=0 AND o.coverage_gap=0 AND julianday(rr.collector_receive_time)<=julianday(?)""",
        (airport, at.isoformat()),
    )
    # Legacy METAR clocks serialize as Z; PWS clocks use +00:00. SQL narrows
    # candidates only; aware comparisons preserve UTC equivalence/microseconds.
    first_by_identity: dict[str, dict[str, Any]] = {}
    for ref in references:
        available = utc(datetime.fromisoformat(ref["available"]))
        if available > utc(at):
            continue
        previous_receipt = first_by_identity.get(ref["identity"])
        if previous_receipt is None or available < datetime.fromisoformat(
            previous_receipt["available"]
        ):
            first_by_identity[ref["identity"]] = {**ref, "available": available.isoformat()}
    references = sorted(
        first_by_identity.values(), key=lambda r: datetime.fromisoformat(r["event_time"])
    )
    # Any competing full report version at the same nominal time makes label ambiguous.
    grouped: dict[str, list[dict[str, Any]]] = {}
    for ref in references:
        grouped.setdefault(ref["event_time"], []).append(ref)
    result = []
    for event, versions in grouped.items():
        if len(versions) != 1 or versions[0]["temperature_c"] is None:
            continue
        ref = versions[0]
        if json.loads(ref["data_json"]).get("cor"):
            continue
        target = datetime.fromisoformat(event)
        decision = target - timedelta(seconds=lead_seconds)
        # A retrospective replay is never a persisted prospective prediction.
        if datetime.fromisoformat(ref["available"]) <= decision:
            continue
        metadata = station_at(connection, station_id, airport, decision)
        if not metadata:
            continue
        station = Station.model_validate_json(metadata["data_json"])
        candidate = latest_station_reading(connection, station, decision, config)
        if not candidate:
            continue
        previous = [
            r
            for r in references
            if r["event_time"] < event
            and datetime.fromisoformat(r["available"]) < decision
            and r["temperature_c"] is not None
        ]
        baseline = (
            max(
                previous,
                key=lambda p: (
                    datetime.fromisoformat(p["event_time"]),
                    datetime.fromisoformat(p["available"]),
                ),
            )
            if previous
            else None
        )
        result.append(
            {
                "target_time": target.isoformat(),
                "decision_time": decision.isoformat(),
                "label_available_at": ref["available"],
                "actual_integer": int(ref["temperature_c"]),
                "temperature_c": candidate["temperature_c"],
                "observation_id": candidate["id"],
                "baseline_integer": int(baseline["temperature_c"]) if baseline else None,
                "replay_class": "AVAILABILITY_FILTERED_REPLAY_NOT_REALTIME_PREDICTION",
            }
        )
    return result


def calibrate(
    connection: sqlite3.Connection,
    station_id: str,
    airport: str,
    pairs: list[dict[str, Any]],
    at: datetime,
    config: QCConfig,
) -> None:
    bias = correction(pairs, at, config)
    if bias is None:
        return
    prior = [
        p
        for p in pairs
        if datetime.fromisoformat(p["label_available_at"]) < at
        and datetime.fromisoformat(p["target_time"]) < at
    ]
    data = {
        "bias": bias,
        "label": "QUANTIZED_INTERVAL_PROJECTION",
        "config": config.model_dump(),
        "pair_count": len(prior),
        "algorithm_version": VERSION,
    }
    connection.execute(
        "INSERT INTO pws_calibrations VALUES(NULL,?,?,?,?,?)",
        (
            station_id,
            airport,
            at.isoformat(),
            max(datetime.fromisoformat(p["label_available_at"]) for p in prior).isoformat(),
            json.dumps(data),
        ),
    )


def predict(
    connection: sqlite3.Connection,
    airport: str,
    target: datetime,
    config: QCConfig,
    method: str = "equal_weights",
    created: datetime | None = None,
    run_id: str | None = None,
    checkpoint: str | None = None,
) -> dict[str, Any]:
    at, target = utc(created or utc_now()), utc(target)
    if target <= at:
        raise ValueError("Predictions must be created before target time")
    known = rows(
        connection,
        "SELECT event_time,collector_receive_time FROM observations WHERE station_icao=? AND product_type IN ('METAR','SPECI') AND julianday(event_time)>=julianday(?) AND julianday(collector_receive_time)<=julianday(?)",
        (airport, target.isoformat(), at.isoformat()),
    )
    if any(
        datetime.fromisoformat(r["event_time"]) >= target
        and datetime.fromisoformat(r["collector_receive_time"]) <= at
        for r in known
    ):
        raise ValueError("Target already received")
    if method not in {
        "equal_weights",
        "nearest",
        "median",
        "inverse_distance",
        "inverse_historical_error",
        "quality_weighted",
    }:
        raise ValueError("Unknown weighting method")
    contributions: list[dict[str, Any]] = []
    for item in sorted(
        inventory(connection, airport),
        key=lambda row: (row["distance_km"] if method == "nearest" else 0, row["station_id"]),
    ):
        station_id = item["station_id"]
        if not selected(connection, station_id, airport, at):
            continue
        snapshot = station_at(connection, station_id, airport, at)
        if not snapshot:
            continue
        station = Station.model_validate_json(snapshot["data_json"])
        candidate = latest_station_reading(connection, station, at, config)
        if not candidate:
            continue
        calibration = rows(
            connection,
            """SELECT * FROM pws_calibrations WHERE station_id=? AND airport_icao=?
            AND created_at<=? AND trained_through<? ORDER BY created_at DESC,id DESC LIMIT 1""",
            (station_id, airport, at.isoformat(), at.isoformat()),
        )
        bias = json.loads(calibration[0]["data_json"])["bias"] if calibration else 0
        quality = rows(
            connection,
            """SELECT * FROM pws_quality_results WHERE station_id=? AND airport_icao=?
            AND created_at<=? ORDER BY created_at DESC,id DESC LIMIT 1""",
            (station_id, airport, at.isoformat()),
        )
        q = json.loads(quality[0]["data_json"]) if quality else {}
        if "STUCK_SENSOR" in q.get("flags", []):
            continue
        weight = 1.0
        if method == "inverse_distance":
            weight = 1 / max(0.2, snapshot["distance_km"])
        elif method == "inverse_historical_error":
            error = q.get("predictive", {}).get("interval_aware_error")
            if (
                error is None
                or q.get("predictive", {}).get("sample_count", 0) < config.min_samples
                or q.get("predictive", {}).get("evaluation_days", 0) < config.min_evaluation_days
            ):
                continue
            weight = 1 / max(0.1, error)
        elif method == "quality_weighted":
            if q.get("score") is None or q["score"] <= 0:
                continue
            weight = q["score"] / 100
        # Prevent very close records from silently getting multiple physical votes.
        if any(
            haversine_km(station.latitude, station.longitude, c["latitude"], c["longitude"]) < 0.2
            for c in contributions
        ):
            continue
        contributions.append(
            {
                "station_id": station_id,
                "observation_id": candidate["id"],
                "temperature_c": candidate["temperature_c"],
                "correction_c": bias,
                "weight": weight,
                "first_receive_time": candidate["first_receive_time"],
                "calibration_id": calibration[0]["id"] if calibration else None,
                "quality_id": quality[0]["id"] if quality else None,
                "discovery_id": snapshot["id"],
                "latitude": station.latitude,
                "longitude": station.longitude,
                "distance_km": snapshot["distance_km"],
                "source_event_time": candidate.get("observation_time"),
                "provider_timestamp": candidate.get("provider_timestamp"),
                "provider_timestamp_kind": candidate.get("provider_timestamp_kind"),
                "quality_flags": candidate.get("quality_flags", []),
            }
        )
    if not contributions:
        raise ValueError(
            "INSUFFICIENT DATA: no eligible selected observations for weighting method"
        )
    if method == "nearest":
        contributions = [min(contributions, key=lambda c: (c["distance_km"], c["station_id"]))]
    estimate = sum(
        (c["temperature_c"] - c["correction_c"]) * c["weight"] for c in contributions
    ) / sum(c["weight"] for c in contributions)
    if method == "median":
        estimate = statistics.median(c["temperature_c"] - c["correction_c"] for c in contributions)
    completed = at if created is not None else utc_now()
    if target <= completed:
        raise ValueError("Target elapsed before prediction construction completed")
    result = {
        "id": uuid4().hex,
        "run_id": run_id,
        "airport_icao": airport,
        "created_at": completed.isoformat(),
        "creation_monotonic_ns": time.perf_counter_ns(),
        "decision_time": at.isoformat(),
        "target_time": target.isoformat(),
        "estimate_c": estimate,
        "integer_temperature": icao_round_temperature(estimate),
        "method": method,
        "checkpoint": checkpoint,
        "experiment_class": "PRE_OBSERVATION",
        "input_cutoff_time": at.isoformat(),
        "input_observation_ids": [c["observation_id"] for c in contributions],
        "contributions": contributions,
        "station_count": len(contributions),
        "quality_flags": sorted(
            {flag for c in contributions for flag in c.get("quality_flags", [])}
        ),
        "config": config.model_dump(),
        "algorithm_version": VERSION,
        "evidence_class": "REALTIME_CAPTURED",
        "clock_synchronization": "UNVERIFIED",
        "capture_coverage_verified": False,
    }
    connection.execute(
        "INSERT INTO pws_predictions VALUES(?,?,?,?,?,?,?)",
        (
            result["id"],
            airport,
            completed.isoformat(),
            at.isoformat(),
            target.isoformat(),
            VERSION,
            json.dumps(result),
        ),
    )
    return result


def evaluate_predictions(
    connection: sqlite3.Connection, airport: str, at: datetime
) -> list[dict[str, Any]]:
    """Score immutable forecasts; UTC differences alone never certify information lead."""
    output = []
    for item in rows(
        connection,
        "SELECT * FROM pws_predictions WHERE airport_icao=? AND created_at<=? ORDER BY created_at",
        (airport, utc(at).isoformat()),
    ):
        forecast = json.loads(item["data_json"])
        references = rows(
            connection,
            """SELECT o.identity,o.temperature_c,o.startup_censored,o.coverage_gap,
            o.data_json,o.event_time,rr.run_id,rr.receive_monotonic_ns,rr.collector_receive_time
            FROM observations o JOIN report_receipts rr ON rr.observation_id=o.id
            WHERE o.station_icao=? AND julianday(o.event_time)=julianday(?) AND o.product_type='METAR'
            AND o.evidence_class='REALTIME_CAPTURED' AND julianday(rr.collector_receive_time)<=julianday(?)""",
            (airport, item["target_time"], utc(at).isoformat()),
        )
        references = sorted(
            (
                r
                for r in references
                if datetime.fromisoformat(r["event_time"])
                == datetime.fromisoformat(item["target_time"])
                and datetime.fromisoformat(r["collector_receive_time"]) <= utc(at)
            ),
            key=lambda r: datetime.fromisoformat(r["collector_receive_time"]),
        )
        result: dict[str, Any] = {
            "prediction_id": item["id"],
            "status": "PENDING",
            "integer_match": None,
            "utc_receive_difference_seconds": None,
            "measured_information_lead_seconds": None,
        }
        if not references:
            output.append(result)
            continue
        if len({r["identity"] for r in references}) != 1 or any(
            json.loads(r["data_json"]).get("cor") for r in references
        ):
            result["status"] = "AMBIGUOUS_REFERENCE"
            output.append(result)
            continue
        first = references[0]
        if first["temperature_c"] is None:
            result["status"] = "MISSING_REFERENCE_TEMPERATURE"
            output.append(result)
            continue
        delta = (
            datetime.fromisoformat(first["collector_receive_time"])
            - datetime.fromisoformat(item["created_at"])
        ).total_seconds()
        result.update(
            status="OBSERVED_ACCURACY_ONLY",
            integer_match=forecast["integer_temperature"] == int(first["temperature_c"]),
            utc_receive_difference_seconds=delta,
        )
        if (
            forecast.get("capture_coverage_verified", False)
            and forecast.get("run_id") == first["run_id"]
            and forecast.get("creation_monotonic_ns") is not None
            and not first["startup_censored"]
            and not first["coverage_gap"]
            and delta > 0
        ):
            lead = (first["receive_monotonic_ns"] - forecast["creation_monotonic_ns"]) / 1e9
            if lead > 0:
                result.update(
                    status="WITHIN_RUN_RECEIVE_ORDER_LEAD", measured_information_lead_seconds=lead
                )
        output.append(result)
    return output
