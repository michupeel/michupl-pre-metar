"""Offline, read-only EPWA research. Never writes forecasts or collector state.

Run from repository root: uv run python -m scripts.research.epwa_comparison
"""

import argparse
import hashlib
import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import mean, median
from typing import Any
from zoneinfo import ZoneInfo

from premetar.model import icao_round_temperature
from premetar.pws.analysis import interval_residual
from premetar.pws.daily import export, local, metars
from premetar.pws.integrity import prediction_issues
from premetar.pws.repository import rows
from premetar.pws.timestamps import assess_time, parse_utc
from scripts.research.epwa_plot import plot_comparison

STATIONS = (
    "61c1f4ff80a739001cda08bb",
    "5c6e9151154515001982e4da",
    "6941429cfdfe0700083492f4",
    "5d6145ec953683001a6b7fdb",
)
VERSION = "epwa-research-1.0"
ZONE = ZoneInfo("Europe/Warsaw")


def clock(value: str) -> datetime:
    parsed = parse_utc(value)
    if parsed is None:
        raise ValueError("Missing clock")
    return parsed


def metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """One record per target/method. Bias is predicted minus reported integer."""
    n = len(records)
    changed = [r for r in records if r["actual_integer"] != r["previous_integer"]]
    same = [r for r in records if r["actual_integer"] == r["previous_integer"]]
    errors = [r["predicted_integer"] - r["actual_integer"] for r in records]

    def sign(value: float) -> int:
        return (value > 0) - (value < 0)

    return dict(
        n=n,
        distinct_targets=len({r["target_time"] for r in records}),
        exact_count=sum(e == 0 for e in errors),
        exact_accuracy=mean(e == 0 for e in errors) if n else None,
        within_1c_accuracy=mean(abs(e) <= 1 for e in errors) if n else None,
        integer_mae=mean(abs(e) for e in errors) if n else None,
        integer_rmse=math.sqrt(mean(e * e for e in errors)) if n else None,
        integer_bias=mean(errors) if n else None,
        mean_interval_error=mean(r["interval_error"] for r in records) if n else None,
        persistence_exact_accuracy=mean(
            r["previous_integer"] == r["actual_integer"] for r in records
        )
        if n
        else None,
        changed_cycles=len(changed),
        unchanged_cycles=len(same),
        changed_exact_count=sum(r["predicted_integer"] == r["actual_integer"] for r in changed),
        change_direction_accuracy=mean(
            sign(r["predicted_integer"] - r["previous_integer"])
            == sign(r["actual_integer"] - r["previous_integer"])
            for r in changed
        )
        if changed
        else None,
        false_alarm_count=sum(r["predicted_integer"] != r["previous_integer"] for r in same),
        missed_change_count=sum(r["predicted_integer"] == r["previous_integer"] for r in changed),
        uncertainty="INSUFFICIENT DATA: fewer than five independent local-day blocks",
    )


def latest(
    history: list[dict[str, Any]], decision: datetime, *, around: datetime | None = None
) -> dict[str, Any] | None:
    """Final eligibility is evaluated at the real decision, never event-time alone."""
    valid = [
        r
        for r in history
        if assess_time(r, decision).eligible
        and not r.get("startup_censored")
        and not r.get("coverage_gap")
        and (around is None or abs((clock(r["observation_time"]) - around).total_seconds()) <= 300)
    ]
    return max(valid, key=lambda r: (clock(r["observation_time"]), r["id"]), default=None)


def correction(
    history: list[dict[str, Any]], decision: datetime, minimum: int = 12
) -> tuple[float | None, int]:
    """Residuals from quantized reference intervals, frozen past decision inputs."""
    prior = [
        r
        for r in history
        if clock(r["first_received_utc"]) < decision
        and decision - timedelta(hours=48) <= clock(r["target_time"]) < decision
    ]
    return (median(r["residual"] for r in prior) if len(prior) >= minimum else None, len(prior))


def initial_routine(official: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in official:
        if r["report_type"] == "METAR" and not r["correction"] and r["temperature_c"] is not None:
            groups[clock(r["observation_time_utc"]).isoformat()].append(r)
    accepted, ambiguous = [], []
    for key, group in sorted(groups.items()):
        if len({r["temperature_c"] for r in group}) > 1:
            ambiguous.append(key)
        else:
            accepted.append(min(group, key=lambda r: clock(r["first_received_utc"])))
    return accepted, ambiguous


def selected_at(events: list[dict[str, Any]], at: datetime) -> dict[str, Any] | None:
    past = [r for r in events if clock(r["created_at"]) <= at]
    last = max(past, key=lambda r: (clock(r["created_at"]), r["id"]), default=None)
    return last if last and last["selected"] else None


def load_data(conn: sqlite3.Connection, as_of: datetime) -> dict[str, Any]:
    stations, readings, excluded = [], [], []
    selection: dict[str, list[dict[str, Any]]] = {}
    for ident in STATIONS:
        station = rows(conn, "SELECT * FROM pws_stations WHERE provider_station_id=?", (ident,))[0]
        metadata = json.loads(station["data_json"])
        sid = station["station_id"]
        selection[sid] = rows(
            conn,
            "SELECT * FROM pws_selections WHERE station_id=? AND airport_icao='EPWA' ORDER BY id",
            (sid,),
        )
        instruments = rows(conn, "SELECT * FROM pws_sensors WHERE station_id=?", (sid,))
        association = rows(
            conn,
            "SELECT * FROM pws_airport_stations WHERE station_id=? AND airport_icao='EPWA'",
            (sid,),
        )[0]
        latest_check = rows(
            conn,
            "SELECT sensor_id,status,outcome,checked_at FROM pws_sensor_checks WHERE station_id=? AND airport_icao='EPWA' ORDER BY id DESC LIMIT 1",
            (sid,),
        )
        stations.append(
            dict(
                station_id=sid,
                **{
                    k: metadata.get(k)
                    for k in (
                        "station_name",
                        "latitude",
                        "longitude",
                        "exposure",
                        "elevation_m",
                        "manufacturer",
                    )
                },
                distance_km=association["distance_km"],
                selected_at_snapshot=bool(selected_at(selection[sid], as_of)),
                instruments=[{**r, "metadata": json.loads(r["data_json"])} for r in instruments],
                latest_check=latest_check,
                selection_history=selection[sid],
                hardware_verification="Provider declaration; installed chip/model/shielding NOT independently verified",
            )
        )
        for raw in rows(
            conn,
            "SELECT o.*,s.provider_sensor_id FROM pws_observations o JOIN pws_sensors s USING(sensor_id) WHERE s.station_id=?",
            (sid,),
        ):
            # Database first receipt is authoritative; JSON fields cannot replace it.
            r = {
                **json.loads(raw["data_json"]),
                **raw,
                "provider": "opensensemap",
                "station_id": sid,
            }
            r.update(exposure=metadata.get("exposure"), mobile=metadata.get("mobile"))
            check = assess_time(r)
            if not check.eligible or not check.measurement_time or not check.collector_receive_time:
                excluded.append(
                    dict(
                        station_id=sid,
                        sensor_id=r["sensor_id"],
                        id=r["id"],
                        reasons=list(check.reasons),
                    )
                )
                continue
            first_arrivals = rows(
                conn,
                "SELECT startup_censored,r.run_id FROM pws_arrivals a JOIN raw_payloads r ON r.id=a.raw_id WHERE a.observation_id=? ORDER BY a.received_at LIMIT 1",
                (r["id"],),
            )
            r["startup_censored"] = (
                bool(first_arrivals[0]["startup_censored"]) if first_arrivals else True
            )
            r["measurement_time_utc"] = check.measurement_time.isoformat()
            r["measurement_time_local"] = local(check.measurement_time, ZONE)
            r["collector_first_receive_time"] = check.collector_receive_time.isoformat()
            r["observation_age_seconds"] = check.age_at_receipt_seconds
            r["qc_status"] = check.status
            readings.append(r)
    groups: dict[tuple[str, datetime], list[dict[str, Any]]] = defaultdict(list)
    for r in readings:
        groups[(r["sensor_id"], clock(r["observation_time"]))].append(r)
    unique = []
    for group in groups.values():
        if len({r["temperature_c"] for r in group}) > 1:
            excluded.extend(
                dict(
                    station_id=r["station_id"],
                    sensor_id=r["sensor_id"],
                    id=r["id"],
                    reasons=["CONFLICTING_DUPLICATE"],
                )
                for r in group
            )
        else:
            unique.append(min(group, key=lambda r: clock(r["first_receive_time"])))
    unique.sort(key=lambda r: (clock(r["observation_time"]), r["sensor_id"]))
    earliest = conn.execute(
        "SELECT min(event_time) FROM observations WHERE station_icao='EPWA'"
    ).fetchone()[0]
    official = metars(
        conn, "EPWA", clock(earliest) - timedelta(days=1), as_of + timedelta(days=1), ZONE
    )
    # Reports received in censored startup/gap snapshots cannot support measured lead.
    for m in official:
        evidence = rows(
            conn,
            "SELECT startup_censored,coverage_gap FROM observations o JOIN report_receipts r ON r.observation_id=o.id WHERE o.identity=? ORDER BY r.collector_receive_time LIMIT 1",
            (m["report_identity"],),
        )
        m["startup_censored"] = bool(evidence[0]["startup_censored"]) if evidence else True
        m["coverage_gap"] = bool(evidence[0]["coverage_gap"]) if evidence else True
    return dict(
        stations=stations,
        observations=unique,
        excluded=excluded,
        metars=official,
        selections=selection,
    )


def replay(data: dict[str, Any], phase: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Retrospective as-of walk-forward, no live forecasts are inserted."""
    routine, ambiguous = initial_routine(data["metars"])
    histories: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in data["observations"]:
        histories[r["station_id"]].append(r)
    training: dict[str, list[dict[str, Any]]] = defaultdict(list)
    output, availability = [], []
    first_event = min(clock(r["observation_time"]) for r in data["observations"])
    for target in routine:
        event = clock(target["observation_time_utc"])
        if event < first_event or target["startup_censored"] or target["coverage_gap"]:
            continue
        decision = event + timedelta(seconds=-60 if phase == "PRE_OBSERVATION" else 60)
        # First receipt includes every routine variant/correction, not just chosen initial outcome.
        first = min(
            clock(m["first_received_utc"])
            for m in data["metars"]
            if m["report_type"] == "METAR" and clock(m["observation_time_utc"]) == event
        )
        if decision >= first:
            continue
        previous_reports = [
            m
            for m in routine
            if clock(m["observation_time_utc"]) < event
            and clock(m["observation_time_utc"]) <= decision
            and clock(m["first_received_utc"]) <= decision
        ]
        if not previous_reports:
            continue
        prev = previous_reports[-1]
        actual, previous = int(target["temperature_c"]), int(prev["temperature_c"])
        base = dict(
            target_time=event.isoformat(),
            decision_time=decision.isoformat(),
            first_received_utc=first.isoformat(),
            previous_target=prev["observation_time_utc"],
            previous_integer=previous,
            actual_integer=actual,
            phase=phase,
            evidence="RETROSPECTIVE_ASOF_REPLAY_NOT_LIVE_PREDICTION",
        )

        def emit(
            station: str,
            method: str,
            value: float,
            *,
            base: dict[str, Any] = base,
            actual: int = actual,
            **extra: Any,
        ) -> None:
            output.append(
                dict(
                    **base,
                    station_id=station,
                    method=method,
                    predicted_temperature_c=value,
                    predicted_integer=icao_round_temperature(value),
                    interval_error=abs(interval_residual(value, actual)),
                    **extra,
                )
            )

        emit("BASELINE", "previous_metar", previous)
        if len(previous_reports) >= 2:
            earlier = previous_reports[-2]
            elapsed = (
                clock(prev["observation_time_utc"]) - clock(earlier["observation_time_utc"])
            ).total_seconds()
            if elapsed > 0:
                value = (
                    previous
                    + (previous - earlier["temperature_c"])
                    * (event - clock(prev["observation_time_utc"])).total_seconds()
                    / elapsed
                )
                emit("BASELINE", "metar_trend", value)
        ensemble = []
        for station, history in sorted(histories.items()):
            selection = selected_at(data["selections"][station], decision)
            reading = latest(history, decision) if selection else None
            availability.append(
                dict(
                    **base,
                    station_id=station,
                    selected=selection is not None,
                    eligible=reading is not None,
                    observation_id=reading["id"] if reading else None,
                )
            )
            if reading is None:
                continue
            assert selection is not None
            value = reading["temperature_c"]
            common = dict(
                input_observation_ids=[reading["id"]],
                selection_id=selection["id"],
                measurement_time=reading["observation_time"],
                receipt_time=reading["first_receive_time"],
            )
            emit(station, "pws_raw", value, **common)
            offset, count = correction(training[station], decision)
            if offset is not None:
                emit(
                    station,
                    "pws_calibrated",
                    value - offset,
                    correction_c=offset,
                    calibration_n=count,
                    **common,
                )
            # Anchor is available at previous reference receipt, from the SAME instrument.
            anchor = latest(
                [r for r in history if r["sensor_id"] == reading["sensor_id"]],
                clock(prev["first_received_utc"]),
                around=clock(prev["observation_time_utc"]),
            )
            if anchor and anchor["id"] != reading["id"]:
                value_trend = previous + value - anchor["temperature_c"]
                emit(
                    station,
                    "pws_change",
                    value_trend,
                    pws_delta_c=value - anchor["temperature_c"],
                    anchor_id=anchor["id"],
                    **common,
                )
            ensemble.append((station, reading))
            training[station].append(
                dict(
                    target_time=event.isoformat(),
                    first_received_utc=target["first_received_utc"],
                    residual=interval_residual(value, actual),
                )
            )
        if len(ensemble) >= 2:
            emit(
                "ENSEMBLE",
                "pws_equal_ensemble",
                mean(r["temperature_c"] for _, r in ensemble),
                stations=[s for s, _ in ensemble],
                input_observation_ids=[r["id"] for _, r in ensemble],
            )
    return output, availability


def matched_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    bykey: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    baselines = {
        (r["phase"], r["target_time"], r["method"]): r
        for r in records
        if r["station_id"] == "BASELINE"
    }
    for r in records:
        if r["station_id"] != "BASELINE":
            bykey[(r["phase"], r["station_id"], r["method"])].append(r)
    result = {}
    for (phase, station, method), group in sorted(bykey.items()):
        baseline = [baselines[(phase, r["target_time"], "previous_metar")] for r in group]
        trend = [
            baselines[(phase, r["target_time"], "metar_trend")]
            for r in group
            if (phase, r["target_time"], "metar_trend") in baselines
        ]
        own = metrics(group)
        own["persistence_on_identical_targets"] = metrics(baseline)
        own["trend_on_available_matched_targets"] = metrics(trend)
        own["trend_matched_candidate"] = metrics(
            [r for r in group if (phase, r["target_time"], "metar_trend") in baselines]
        )
        own["accuracy_delta_vs_persistence"] = (
            own["exact_accuracy"] - own["persistence_on_identical_targets"]["exact_accuracy"]
        )
        own["status"] = "PRELIMINARY" if own["n"] >= 30 else "INSUFFICIENT DATA"
        result[f"{phase}|{station}|{method}"] = own
    return result


def agreement(data: dict[str, Any]) -> list[dict[str, Any]]:
    routine, _ = initial_routine(data["metars"])
    output = []
    for r in data["observations"]:
        t = clock(r["observation_time"])
        nearest = min(
            routine,
            key=lambda m: abs((clock(m["observation_time_utc"]) - t).total_seconds()),
            default=None,
        )
        if (
            nearest is None
            or abs((clock(nearest["observation_time_utc"]) - t).total_seconds()) > 300
        ):
            continue
        output.append(
            dict(
                station_id=r["station_id"],
                sensor_id=r["sensor_id"],
                observation_id=r["id"],
                measurement_time_utc=r["measurement_time_utc"],
                time_difference_seconds=(
                    t - clock(nearest["observation_time_utc"])
                ).total_seconds(),
                collector_first_receive_time=r["first_receive_time"],
                temperature_c=r["temperature_c"],
                target_time=nearest["observation_time_utc"],
                metar_integer=nearest["temperature_c"],
                interval_residual_c=interval_residual(r["temperature_c"], nearest["temperature_c"]),
                evidence="EXPLORATORY_MEASUREMENT_ALIGNMENT_NOT_PREDICTION",
            )
        )
    return output


def inventory(data: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for st in data["stations"]:
        history = [r for r in data["observations"] if r["station_id"] == st["station_id"]]
        bad = [r for r in data["excluded"] if r["station_id"] == st["station_id"]]
        intervals = [
            (clock(b["observation_time"]) - clock(a["observation_time"])).total_seconds()
            for a, b in zip(history, history[1:], strict=False)
            if b["sensor_id"] == a["sensor_id"]
        ]
        decimals: Counter[str] = Counter()
        for r in history:
            try:
                exponent = Decimal(str(r["raw_temperature"])).as_tuple().exponent
                decimals[str(max(0, -exponent)) if isinstance(exponent, int) else "unknown"] += 1
            except (InvalidOperation, ValueError, TypeError):
                decimals["unknown"] += 1
        values = sorted(set(r["temperature_c"] for r in history))
        out.append(
            dict(
                station_id=st["station_id"],
                station_name=st["station_name"],
                distance_km=st["distance_km"],
                selected_at_snapshot=st["selected_at_snapshot"],
                sensor_types=[r["metadata"].get("sensor_type") for r in st["instruments"]],
                valid_observations=len(history),
                excluded_observations=len(bad),
                rejection_reasons=dict(Counter(reason for r in bad for reason in r["reasons"])),
                first=history[0]["measurement_time_utc"] if history else None,
                last=history[-1]["measurement_time_utc"] if history else None,
                median_interval_seconds=median(intervals) if intervals else None,
                largest_gap_seconds=max(intervals) if intervals else None,
                median_age_seconds=median(r["observation_age_seconds"] for r in history)
                if history
                else None,
                min_temperature_c=min(values) if values else None,
                max_temperature_c=max(values) if values else None,
                raw_decimal_places=dict(decimals),
                smallest_observed_distinct_step_c=min(
                    (round(b - a, 6) for a, b in zip(values, values[1:], strict=False)),
                    default=None,
                ),
                qc_flags=dict(
                    Counter(flag for r in history for flag in r.get("quality_flags", []))
                ),
            )
        )
    return out


def actual_forecasts(conn: sqlite3.Connection, data: dict[str, Any]) -> dict[str, Any]:
    routine, _ = initial_routine(data["metars"])
    target_map = {clock(r["observation_time_utc"]): r for r in routine}
    included_ids = {r["id"] for r in data["observations"]}
    valid, exclusions = [], []
    for row in rows(
        conn, "SELECT * FROM pws_predictions WHERE airport_icao='EPWA' ORDER BY created_at"
    ):
        pred = json.loads(row["data_json"])
        problems = prediction_issues(conn, pred)
        problems += [
            (r["reason"], r["input_id"])
            for r in rows(
                conn,
                "SELECT reason,input_id FROM prediction_exclusions WHERE prediction_id=?",
                (row["id"],),
            )
        ]
        report = target_map.get(clock(row["target_time"]))
        settled = rows(
            conn,
            "SELECT * FROM continuous_settlements WHERE prediction_id=? ORDER BY id",
            (row["id"],),
        )
        first_settled = next(
            (s for s in settled if report and s["report_identity"] == report["report_identity"]),
            None,
        )
        if problems or report is None or first_settled is None:
            exclusions.append(
                dict(
                    prediction_id=row["id"],
                    issues=sorted(set(reason for reason, _ in problems)),
                    outcome_available=first_settled is not None,
                )
            )
            continue
        settlement = json.loads(first_settled["data_json"])
        if (
            not settlement.get("valid_prospective")
            or settlement.get("startup_censored")
            or settlement.get("coverage_gap")
        ):
            exclusions.append(
                dict(
                    prediction_id=row["id"],
                    issues=["SETTLEMENT_NOT_UNCENSORED_PROSPECTIVE"],
                    outcome_available=True,
                )
            )
            continue
        previous = [
            m
            for m in routine
            if clock(m["observation_time_utc"]) < clock(row["target_time"])
            and clock(m["observation_time_utc"]) <= clock(row["created_at"])
            and clock(m["first_received_utc"]) <= clock(row["created_at"])
        ]
        if not previous:
            continue
        valid.append(
            dict(
                prediction_id=row["id"],
                target_time=clock(row["target_time"]).isoformat(),
                created_at=row["created_at"],
                checkpoint=pred.get("checkpoint"),
                method=pred.get("method"),
                actual_integer=int(report["temperature_c"]),
                previous_integer=int(previous[-1]["temperature_c"]),
                predicted_integer=pred["integer_temperature"],
                interval_error=abs(interval_residual(pred["estimate_c"], report["temperature_c"])),
                linked_requested_station=bool(
                    included_ids.intersection(pred.get("input_observation_ids", []))
                ),
                evidence="ACTUAL_IMMUTABLE_FORECAST",
                reference_first_seen=first_settled["reference_first_seen"],
            )
        )
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in valid:
        groups[f"{r['checkpoint']}|{r['method']}"].append(r)
    paired = {}
    baselines = {
        (r["checkpoint"], r["target_time"]): r for r in valid if r["method"] == "previous_metar"
    }
    for key, group in sorted(groups.items()):
        matched = [r for r in group if (r["checkpoint"], r["target_time"]) in baselines]
        paired[key] = dict(
            candidate=metrics(matched),
            recorded_baseline=metrics(
                [baselines[(r["checkpoint"], r["target_time"])] for r in matched]
            ),
            prediction_ids=[r["prediction_id"] for r in matched],
        )
    cohort_start = max(
        min(clock(s["created_at"]) for s in events if s["selected"])
        for events in data["selections"].values()
    )
    cohort_valid = [r for r in valid if clock(r["created_at"]) >= cohort_start]
    cohort_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in cohort_valid:
        cohort_groups[f"{r['checkpoint']}|{r['method']}"].append(r)
    cohort_paired = {}
    for key, group in sorted(cohort_groups.items()):
        matched = [r for r in group if (r["checkpoint"], r["target_time"]) in baselines]
        cohort_paired[key] = dict(
            candidate=metrics(matched),
            recorded_baseline=metrics(
                [baselines[(r["checkpoint"], r["target_time"])] for r in matched]
            ),
        )
    return dict(
        valid=valid,
        excluded=exclusions,
        groups={k: metrics(v) for k, v in sorted(groups.items())},
        matched_recorded_baselines=paired,
        requested_cohort_start=cohort_start.isoformat(),
        requested_cohort_forecasts=len(cohort_valid),
        requested_cohort_distinct_targets=len({r["target_time"] for r in cohort_valid}),
        requested_cohort_matched_groups=cohort_paired,
        distinct_targets=len({r["target_time"] for r in valid}),
    )


def common_target_comparisons(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Fixed-method, identical-target station comparison; no best-model selection."""
    output = {}
    for phase in ("PRE_OBSERVATION", "POST_OBSERVATION_PRE_RECEIPT"):
        for method in ("pws_raw", "pws_calibrated", "pws_change"):
            groups = {
                "opensensemap:" + station: [
                    r
                    for r in records
                    if r["phase"] == phase
                    and r["station_id"] == "opensensemap:" + station
                    and r["method"] == method
                ]
                for station in STATIONS
            }
            common = set.intersection(
                *({r["target_time"] for r in group} for group in groups.values())
            )
            measured = {
                station: metrics([r for r in group if r["target_time"] in common])
                for station, group in groups.items()
            }
            # A deterministic descriptive order, not validated station selection.
            order = (
                sorted(
                    measured,
                    key=lambda s: (
                        -(measured[s]["exact_accuracy"] or 0),
                        measured[s]["mean_interval_error"] or 0,
                        s,
                    ),
                )
                if common
                else []
            )
            output[f"{phase}|{method}"] = dict(
                targets=sorted(common),
                n=len(common),
                stations=measured,
                descriptive_order=order,
                ranking_status="PRELIMINARY" if len(common) >= 30 else "INSUFFICIENT DATA",
            )
    # H1/H2/H3 on the same targets within each station, to avoid calibration warmup bias.
    within = {}
    for station in STATIONS:
        sid = "opensensemap:" + station
        groups = {
            method: [
                r
                for r in records
                if r["phase"] == "PRE_OBSERVATION"
                and r["station_id"] == sid
                and r["method"] == method
            ]
            for method in ("pws_raw", "pws_calibrated", "pws_change")
        }
        common = set.intersection(*({r["target_time"] for r in group} for group in groups.values()))
        within[sid] = {
            method: metrics([r for r in group if r["target_time"] in common])
            for method, group in groups.items()
        }
    return dict(across_stations=output, within_station=within)


def operational_ranking(
    inv: list[dict[str, Any]], availability: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    ranking = []
    for st in inv:
        eligible_windows = [
            r
            for r in availability
            if r["station_id"] == st["station_id"]
            and r["selected"]
            and r["phase"] == "PRE_OBSERVATION"
        ]
        total = st["valid_observations"] + st["excluded_observations"]
        ranking.append(
            dict(
                station_id=st["station_id"],
                valid_receipt_fraction=st["valid_observations"] / total if total else 0,
                checkpoint_eligible=sum(r["eligible"] for r in eligible_windows),
                checkpoint_total=len(eligible_windows),
                checkpoint_coverage=mean(r["eligible"] for r in eligible_windows)
                if eligible_windows
                else 0,
                median_age_seconds=st["median_age_seconds"],
                largest_gap_seconds=st["largest_gap_seconds"],
            )
        )
    return sorted(
        ranking,
        key=lambda r: (
            -r["valid_receipt_fraction"],
            -r["checkpoint_coverage"],
            r["median_age_seconds"],
            r["largest_gap_seconds"],
            r["station_id"],
        ),
    )


def agreement_matched(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    nearest: dict[str, dict[str, dict[str, Any]]] = {"opensensemap:" + s: {} for s in STATIONS}
    for r in pairs:
        previous = nearest[r["station_id"]].get(r["target_time"])
        if previous is None or abs(r["time_difference_seconds"]) < abs(
            previous["time_difference_seconds"]
        ):
            nearest[r["station_id"]][r["target_time"]] = r
    common = set.intersection(*(set(group) for group in nearest.values()))
    return dict(
        n=len(common),
        targets=sorted(common),
        stations={
            sid: dict(
                mean_signed_interval_residual_c=mean(
                    group[t]["interval_residual_c"] for t in common
                )
                if common
                else None,
                mean_absolute_interval_error_c=mean(
                    abs(group[t]["interval_residual_c"]) for t in common
                )
                if common
                else None,
            )
            for sid, group in nearest.items()
        },
    )


def transition_rows(
    replay_rows: list[dict[str, Any]], prospective: dict[str, Any]
) -> list[dict[str, Any]]:
    out = []
    actual_by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in prospective["valid"]:
        actual_by_target[r["target_time"]].append(r)
    for r in replay_rows:
        if r["station_id"] == "BASELINE":
            continue
        actual_change = r["actual_integer"] - r["previous_integer"]
        predicted_change = r["predicted_integer"] - r["previous_integer"]
        out.append(
            dict(
                target_time=r["target_time"],
                target_time_local=local(r["target_time"], ZONE),
                reference_first_seen=r["first_received_utc"],
                decision_time=r["decision_time"],
                phase=r["phase"],
                station_id=r["station_id"],
                method=r["method"],
                previous_integer=r["previous_integer"],
                actual_integer=r["actual_integer"],
                actual_transition="UP"
                if actual_change > 0
                else "DOWN"
                if actual_change < 0
                else "UNCHANGED",
                predicted_integer=r["predicted_integer"],
                pws_delta_c=r.get("pws_delta_c"),
                measurement_time=r.get("measurement_time"),
                pws_first_received=r.get("receipt_time"),
                input_observation_ids=r.get("input_observation_ids"),
                exact_correct=r["predicted_integer"] == r["actual_integer"],
                correct_change_signal=bool(
                    actual_change and r["predicted_integer"] == r["actual_integer"]
                ),
                false_alarm=bool(not actual_change and predicted_change),
                persistence_correct=not bool(actual_change),
                immutable_predictions_before_first_receipt=[
                    p["prediction_id"] for p in actual_by_target[r["target_time"]]
                ],
                immutable_predictions_by_decision=[
                    p["prediction_id"]
                    for p in actual_by_target[r["target_time"]]
                    if clock(p["created_at"]) <= clock(r["decision_time"])
                ],
                analysis="RETROSPECTIVE_REPLAY_SEPARATE_FROM_LISTED_IMMUTABLE_FORECASTS",
            )
        )
    return out


def run(snapshot: Path, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = snapshot.parent / "snapshot_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if hashlib.sha256(snapshot.read_bytes()).hexdigest() != manifest["sha256"]:
        raise ValueError("Snapshot hash mismatch")
    as_of = clock(manifest["captured_at"])
    with sqlite3.connect(snapshot.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        data = load_data(conn, as_of)
        prospective = actual_forecasts(conn, data)
    replay_rows, availability = [], []
    for phase in ("PRE_OBSERVATION", "POST_OBSERVATION_PRE_RECEIPT"):
        rr, aa = replay(data, phase)
        replay_rows.extend(rr)
        availability.extend(aa)
    result = dict(
        version=VERSION,
        snapshot=manifest,
        inventory=inventory(data),
        agreement=agreement(data),
        replay=replay_rows,
        availability=availability,
        metrics=matched_metrics(replay_rows),
        prospective=prospective,
    )
    result["common_targets"] = common_target_comparisons(replay_rows)
    result["agreement_matched"] = agreement_matched(result["agreement"])
    for st in result["inventory"]:
        history = [r for r in data["observations"] if r["station_id"] == st["station_id"]]
        st["latest_valid_status_at_snapshot"] = (
            assess_time(history[-1], as_of).status if history else "NO_VALID_MEASUREMENT"
        )
    result["operational_ranking"] = operational_ranking(result["inventory"], availability)
    result["transitions"] = transition_rows(replay_rows, prospective)
    # Public normalized export, not duplicate raw payload/JSON blobs.
    observation_fields = (
        "id",
        "station_id",
        "sensor_id",
        "provider_sensor_id",
        "measurement_time_utc",
        "measurement_time_local",
        "collector_first_receive_time",
        "temperature_c",
        "raw_temperature",
        "raw_unit",
        "source_precision",
        "observation_age_seconds",
        "timestamp_provenance",
        "timestamp_semantics_verified",
        "qc_status",
        "quality_flags",
        "startup_censored",
    )
    observations_export = [{k: r.get(k) for k in observation_fields} for r in data["observations"]]
    for filename, content, defaults in (
        (
            "epwa_station_comparison.csv",
            observations_export,
            ["station_id", "sensor_id", "measurement_time_utc", "temperature_c"],
        ),
        ("epwa_agreement.csv", result["agreement"], ["station_id", "target_time"]),
        ("epwa_walk_forward.csv", replay_rows, ["phase", "target_time", "station_id", "method"]),
        ("epwa_forecasts.csv", prospective["valid"], ["target_time", "prediction_id"]),
        (
            "epwa_forecast_exclusions.csv",
            prospective["excluded"],
            ["prediction_id", "issues", "outcome_available"],
        ),
        ("epwa_availability.csv", availability, ["target_time", "station_id", "eligible"]),
        ("epwa_transitions.csv", result["transitions"], ["target_time", "station_id", "method"]),
        ("epwa_station_inventory.csv", result["inventory"], ["station_id", "station_name"]),
        (
            "epwa_metar_reports.csv",
            data["metars"],
            [
                "observation_time_utc",
                "first_received_utc",
                "temperature_c",
                "report_type",
                "correction",
            ],
        ),
    ):
        export(output / filename, content, defaults)
    first_local_day = (
        min(clock(r["observation_time"]) for r in data["observations"])
        .astimezone(ZONE)
        .replace(hour=0, minute=0, second=0, microsecond=0)
    )
    plot_comparison(
        data["observations"],
        [r for r in data["metars"] if clock(r["observation_time_utc"]) >= first_local_day],
        data["stations"],
        output / "epwa_station_comparison.png",
    )
    (output / "epwa_results.json").write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8"
    )
    summary = {
        k: v
        for k, v in result.items()
        if k not in ("agreement", "replay", "availability", "transitions", "prospective")
    }
    summary["prospective"] = {
        k: v
        for k, v in prospective.items()
        if k not in ("valid", "excluded", "matched_recorded_baselines")
    }
    (output / "epwa_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_markdown(result, output)
    write_findings(result, output)
    manifest["analysis_environment"] = dict(
        python=sys.version, sqlite=sqlite3.sqlite_version, version=VERSION
    )
    manifest["source_sha256"] = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [
            Path(__file__),
            Path("scripts/research/epwa_plot.py"),
            Path("scripts/research/epwa_diagnostics.py"),
            Path("docs/research/EPWA_M17_PROTOCOL.md"),
            Path("configs/timestamp-policy-v1.json"),
        ]
    }
    (output / "epwa_research_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return result


def write_markdown(result: dict[str, Any], output: Path) -> None:
    lines = [
        "# EPWA station comparison — Milestone1.7",
        "",
        f"Snapshot: {result['snapshot']['captured_at']}; SHA256 {result['snapshot']['sha256']}.",
        "",
        "Protocol: docs/research/EPWA_M17_PROTOCOL.md. Collector rules unchanged; analysis is offline read-only. As-of replays below are retrospective, never live forecast claims. Uncertainty: INSUFFICIENT DATA for robust information edge.",
        "",
        "## Operational inventory",
        "",
        "| Station | Instrument | Valid | Excluded | Update s | Receipt age s | Max gap s | Range °C |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for st in result["inventory"]:
        lines.append(
            f"| {st['station_name']} ({st['station_id']}) | {','.join(st['sensor_types'])} | {st['valid_observations']} | {st['excluded_observations']} | {st['median_interval_seconds']} | {st['median_age_seconds']} | {st['largest_gap_seconds']} | {st['min_temperature_c']}–{st['max_temperature_c']} |"
        )
    lines += [
        "",
        "## Walk-forward results against matched persistence",
        "",
        "H1 raw; H2 rolling48h minimum12 past interval-residual median correction; H3 previous METAR plus same-instrument change from previous cycle anchor. No outcome-based station selection. Training outcome receipt must precede decision. T−60 and T+60 experiments remain separate.",
        "",
        "| Phase / station / model | N | Exact | Matched persistence | METAR trend exact/N | Difference pp | Changed exact / Nchanges | False alarms | Interval error °C |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, m in result["metrics"].items():
        lines.append(
            f"| {key} | {m['n']} | {m['exact_accuracy']:.3f} | {m['persistence_on_identical_targets']['exact_accuracy']:.3f} | {m['trend_on_available_matched_targets']['exact_accuracy']}/{m['trend_on_available_matched_targets']['n']} | {100 * m['accuracy_delta_vs_persistence']:.2f} | {m['changed_exact_count']}/{m['changed_cycles']} | {m['false_alarm_count']} | {m['mean_interval_error']:.3f} |"
        )
    lines += [
        "",
        "## Operational ranking (no predictive score)",
        "",
        "Ordering fixed in protocol: valid receipt fraction, fresh checkpoint coverage, median age, largest gap. Coverage denominator: selected T−60 windows with an uncensored target and available baseline, not HTTP poll count. A valid historical receipt may be stale now.",
        "",
        "| Rank | Station | Valid fraction | Eligible/selected checkpoints | Median age s |",
        "|---|---|---:|---:|---:|",
    ]
    for rank, r in enumerate(result["operational_ranking"], 1):
        lines.append(
            f"| {rank} | {r['station_id']} | {r['valid_receipt_fraction']:.4f} | {r['checkpoint_eligible']}/{r['checkpoint_total']} | {r['median_age_seconds']:.2f} |"
        )
    lines += [
        "",
        "## Predictive ranking on identical targets",
        "",
        "Separate fixed-model comparisons. Descriptive ordering below is NOT approved future station selection. All-station intersections with <30 cycles are INSUFFICIENT DATA for ranking. Candidate results outside these intersections above must not be compared directly across stations.",
        "",
        "| Phase/model | Common N | Station | Exact | Same-target persistence | Status |",
        "|---|---:|---|---:|---:|---|",
    ]
    for key, item in result["common_targets"]["across_stations"].items():
        for sid in item["descriptive_order"]:
            m = item["stations"][sid]
            lines.append(
                f"| {key} | {item['n']} | {sid} | {m['exact_accuracy']:.3f} | {m['persistence_exact_accuracy']:.3f} | {item['ranking_status']} |"
            )
        if not item["n"]:
            lines.append(f"| {key} | 0 | — | — | — | INSUFFICIENT DATA |")
    lines += [
        "",
        "## Absolute vs calibration vs change on matched within-station cycles",
        "",
        "| Station | N | Raw exact | Calibrated exact | Change exact | Persistence |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for sid, group in result["common_targets"]["within_station"].items():
        raw, cal, trend = (group[k] for k in ("pws_raw", "pws_calibrated", "pws_change"))
        lines.append(
            f"| {sid} | {raw['n']} | {raw['exact_accuracy']} | {cal['exact_accuracy']} | {trend['exact_accuracy']} | {raw['persistence_exact_accuracy']} |"
        )
    lines += [
        "",
        "## Meteorological agreement (not forecasting)",
        "",
        "Every eligible source measurement is paired with its nearest initial routine METAR within±5min. Multiple sensor readings for one target are not independent outcomes. Signed interval residual >0 means warmer than the METAR rounding interval.",
        "",
        "| Station | Readings / distinct cycles | Mean signed interval residual °C | Mean absolute interval distance °C |",
        "|---|---:|---:|---:|",
    ]
    for st in result["inventory"]:
        a = [r for r in result["agreement"] if r["station_id"] == st["station_id"]]
        lines.append(
            f"| {st['station_name']} | {len(a)}/{len({r['target_time'] for r in a})} | {mean(r['interval_residual_c'] for r in a) if a else None} | {mean(abs(r['interval_residual_c']) for r in a) if a else None} |"
        )
    lines += [
        "",
        f"For a FAIR between-station agreement comparison, choose one nearest measurement per station/cycle and intersect cycles: common N={result['agreement_matched']['n']}. The broader reading-level rows above have unequal coverage and must not be directly ranked.",
        "",
        "| Station | Matched mean signed interval residual °C | Matched absolute interval distance °C |",
        "|---|---:|---:|",
    ]
    for sid, m in result["agreement_matched"]["stations"].items():
        lines.append(
            f"| {sid} | {m['mean_signed_interval_residual_c']} | {m['mean_absolute_interval_error_c']} |"
        )
    lines += [
        "",
        "## Actual immutable prospective forecasts",
        "",
        f"Valid forecasts: {len(result['prospective']['valid'])}; distinct target cycles: {result['prospective']['distinct_targets']}; excluded/unsettled rows: {len(result['prospective']['excluded'])}. Each checkpoint/model group below has one row per cycle; do not sum groups as independent events.",
        "",
        "| Checkpoint/model | N | Exact | Same-target persistence |",
        "|---|---:|---:|---:|",
    ]
    for key, m in result["prospective"]["groups"].items():
        lines.append(
            f"| {key} | {m['n']} | {m['exact_accuracy']:.3f} | {m['persistence_exact_accuracy']:.3f} |"
        )
    lines += [
        "",
        "### Requested four-station cohort: recorded matched baselines",
        "",
        f"Cohort starts {result['prospective']['requested_cohort_start']}; {result['prospective']['requested_cohort_forecasts']} eligible forecasts over {result['prospective']['requested_cohort_distinct_targets']} distinct cycles. Earlier all-history groups include the previous cohort and must not be attributed to these four sensors. Recorded production model definitions differ from the new research change model.",
        "",
        "| Checkpoint/model | Matched N | Candidate exact | Recorded previous-METAR exact |",
        "|---|---:|---:|---:|",
    ]
    for key, m in result["prospective"]["requested_cohort_matched_groups"].items():
        lines.append(
            f"| {key} | {m['candidate']['n']} | {m['candidate']['exact_accuracy']} | {m['recorded_baseline']['exact_accuracy']} |"
        )
    lines += [
        "",
        "## Transition counts (one target per station/method/phase)",
        "",
        "| Phase/station/model | Up/down/unchanged targets | Correct changed integer | False-alarm cycles |",
        "|---|---:|---:|---:|",
    ]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in result["transitions"]:
        grouped[f"{r['phase']}|{r['station_id']}|{r['method']}"].append(r)
    for key, group in sorted(grouped.items()):
        counts = Counter(r["actual_transition"] for r in group)
        lines.append(
            f"| {key} | {counts['UP']}/{counts['DOWN']}/{counts['UNCHANGED']} | {sum(r['correct_change_signal'] for r in group)} | {sum(r['false_alarm'] for r in group)} |"
        )
    lines += [
        "",
        "Transition CSV preserves latest input IDs, measurement/receipt/decision clocks, PWS delta, exact outcome and genuine immutable forecast IDs. Correct replay change signals are exploratory, not prospective successes; no future measurements enter replay. Same-target persistence never predicts a change. Checkpoint-diagnostics findings and full station metadata/QC histories: epwa_checkpoint_diagnostics.md/json.",
        "",
        "## Hardware, precision and mounting",
        "",
        "See docs/research/EPWA_HARDWARE.md for verified manufacturer documents and uncertainty. All four instruments publish two decimal places; observed minimum distinct steps are empirical, not hardware resolution. Declared BMP180 produces observed 0.02°C differences although the documented reference conversion uses0.1°C: firmware averaging or declaration mismatch remain hypotheses. No installed hardware is authenticated. Current QC remains UNVERIFIED; historical aggregate MISSING_INTERVALS flags do not invalidate every otherwise fresh receipt.",
    ]
    lines += [
        "",
        "## Limitations",
        "",
        "Short observational period, no random split, no robust confidence claim. METAR integer is a rounding interval; residual correction is a quantized-reference estimate, not precise airport calibration. Provider identities do not establish physical independence; one thermometer per provider station is represented. Metadata declarations do not verify actual mounting or shielding. Historical startup/coverage-censored inputs are excluded from replay. Current calibration/model comparisons are research replays only; actual immutable forecasts are evaluated separately. Clock synchronization uncertainty limits lead interpretation.",
        "",
        "## Reproduce",
        "",
        "```powershell",
        "uv run python -m scripts.research.epwa_comparison --snapshot data/research/m17/snapshot.sqlite3",
        "```",
        "",
        "Snapshot and raw payloads are intentionally ignored; CSV contains actual normalized measurements. Export includes first receipts and raw reported precision; no interpolation or forward fill. Chart lines stop at gaps>15min.",
    ]
    (output / "epwa_station_comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_findings(result: dict[str, Any], output: Path) -> None:
    names = {r["station_id"]: r["station_name"] for r in result["inventory"]}
    best = min(
        result["agreement_matched"]["stations"],
        key=lambda sid: result["agreement_matched"]["stations"][sid][
            "mean_absolute_interval_error_c"
        ],
    )
    lines = [
        "",
        "## Practical findings",
        "",
        f"Absolute meteorological agreement and incremental prediction are different questions. {names[best]} has the smallest mean absolute interval distance on {result['agreement_matched']['n']} common meteorological cycles in this snapshot; that does not establish a forecasting advantage.",
        "",
        "| Station change model, T−60 | Exact | Same-target persistence | Correct changed integer / actual changes | False alarms on unchanged cycles |",
        "|---|---:|---:|---:|---:|",
    ]
    for st in result["inventory"]:
        key = f"PRE_OBSERVATION|{st['station_id']}|pws_change"
        m = result["metrics"].get(key)
        if m:
            lines.append(
                f"| {st['station_name']} | {m['exact_count']}/{m['n']} | {m['persistence_on_identical_targets']['exact_count']}/{m['n']} | {m['changed_exact_count']}/{m['changed_cycles']} | {m['false_alarm_count']}/{m['unchanged_cycles']} |"
            )
    lines += [
        "",
        "These rows each compare with persistence on identical targets, but DIFFERENT STATIONS have different target sets. Do not rank these raw percentages across stations. The all-four trend intersection is reported above; insufficient overlap prevents a defensible predictive trend ranking. Any apparent single-station improvement remains a hypothesis, not a validated edge.",
        "",
        "### Correct retrospective change signals",
        "",
        "| Local target | Station | METAR previous→actual | PWS delta °C | Latest measurement UTC | First received UTC | Replay decision UTC | METAR received UTC |",
        "|---|---|---|---:|---|---|---|---|",
    ]
    for r in result["transitions"]:
        if (
            r["phase"] == "PRE_OBSERVATION"
            and r["method"] == "pws_change"
            and r["correct_change_signal"]
        ):
            lines.append(
                f"| {r['target_time_local']} | {names[r['station_id']]} | {r['previous_integer']}→{r['actual_integer']} | {r['pws_delta_c']:.3f} | {r['measurement_time']} | {r['pws_first_received']} | {r['decision_time']} | {r['reference_first_seen']} |"
            )
    lines += [
        "",
        "These are reconstructed signals using inputs available at the fixed decision. The new pws_change rule was NOT running as an immutable live model. Actual earlier forecasts are linked in the transition CSV, with separate IDs available by decision versus by first receipt. A genuine prospective claim cannot be created retrospectively.",
        "",
        "### Actual production outcomes, current cohort, T−60",
        "",
        "| Model | Candidate exact | Recorded persistence on SAME targets |",
        "|---|---:|---:|",
    ]
    for key, g in result["prospective"]["requested_cohort_matched_groups"].items():
        if key.startswith("T-60s|"):
            lines.append(
                f"| {key.split('|')[1]} | {g['candidate']['exact_count']}/{g['candidate']['n']} | {g['recorded_baseline']['exact_count']}/{g['recorded_baseline']['n']} |"
            )
    lines += [
        "",
        "The original production PWS methods do not outperform recorded persistence in this cohort. At T−60 calibration improves several raw models but does not beat persistence on their matched windows. The equal raw ensemble also fails to improve on its matched baseline. Retain all four for research; no production cohort or scoring rules were changed. Further prospective, multi-day validation is required before adopting any change rule.",
        "",
        "### Unavailable checkpoints",
        "",
        "The prior ten UNAVAILABLE rows reconstruct to six quality_weighted cases with fresh observations but NULL quality scores, and four EGLL T−180 methods with no selected input≤300s old. EDDM:3; EGLL:6; EHAM:1; EPWA:0. Scores are deliberately UNVERIFIED; no scheduler defect demonstrated. The stored generic reason discarded original exceptions/transient gate state; attribution is a durable-state reconstruction, not recovered original exceptions. Full details in epwa_checkpoint_diagnostics.md.",
    ]
    with (output / "epwa_station_comparison.md").open("a", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=Path("data/research/m17/snapshot.sqlite3"))
    parser.add_argument("--output", type=Path, default=Path("reports/research"))
    args = parser.parse_args()
    result = run(args.snapshot, args.output)
    print(
        json.dumps(
            dict(
                inventory=result["inventory"],
                metrics=result["metrics"],
                prospective_groups=result["prospective"]["groups"],
            ),
            indent=2,
        )
    )
