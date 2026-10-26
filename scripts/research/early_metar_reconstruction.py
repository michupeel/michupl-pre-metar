"""EXP-0010: deterministic offline reconstruction, never production predictions.

uv run python -m scripts.research.early_metar_reconstruction
"""

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

from premetar.model import icao_round_temperature
from premetar.pws.analysis import interval_residual
from premetar.pws.daily import export
from premetar.pws.geometry import haversine_km
from scripts.research.early_metar_data import (
    AIRPORTS,
    EPS,
    asof_eligible,
    calibration,
    clock,
    latest,
    load_dataset,
    metadata_at,
    previous_reference,
    selection_at,
)
from scripts.research.early_metar_metrics import analyze_trajectory, summarize_candidates
from scripts.research.early_metar_prospective import audit_prospective
from scripts.research.early_metar_timeline import plot_timeline

METHODS = ("CAL-0", "CAL-1", "CAL-2")
CHECKPOINTS = (-600, -300, -180, -120, -60, 30, 60, 90)
VERSION = "exp0010-1.0"
EVIDENCE = "RETROSPECTIVE_AS_OF_RECONSTRUCTION"


def candidate(
    sensor: dict[str, Any],
    reference: dict[str, Any],
    references: list[dict[str, Any]],
    method: str,
    at: datetime,
    *,
    window: str | None = None,
    forced: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any] | None]:
    event, closure = reference["_event"], reference["_closure"]
    if at >= closure:
        return "TARGET_ALREADY_RECEIVED", None
    previous = previous_reference(references, event, at)
    if previous is None:
        return "NO_PRIOR_METAR", None
    reading = forced if forced is not None else latest(sensor, at, phase=window, nominal=event)
    if reading is None or not asof_eligible(sensor, reading, at):
        if window == "EXP_B" and latest(sensor, at) is not None:
            return "NO_POST_OBSERVATION_RECEIPT", None
        return "NO_ELIGIBLE_OBSERVATION", None
    if window == "EXP_B" and reading["_received"] < event:
        return "NO_POST_OBSERVATION_RECEIPT", None
    adjustment = calibration(sensor, method, event, at)
    if adjustment is None:
        return "INSUFFICIENT_CALIBRATION_HISTORY", None
    metadata = metadata_at(sensor, at)
    assert metadata is not None
    station_selection = selection_at(sensor, at)
    phase = (
        "EXP_A"
        if at < event
        else "EXP_B"
        if reading["_received"] >= event
        else "CARRIED_PREOBS_INPUT"
    )
    temperature = reading["temperature_c"] - adjustment["offset_c"]
    actual = int(reference["temperature_c"])
    predicted = icao_round_temperature(temperature)
    airport = sensor["airport_metadata"]
    result = dict(
        airport=sensor["airport"],
        station_id=sensor["station_id"],
        sensor_id=sensor["sensor_id"],
        sensor_type=sensor["sensor_type"],
        station_name=metadata.get("station_name"),
        provider=sensor["provider"],
        distance_km=haversine_km(
            metadata["latitude"], metadata["longitude"], airport["latitude"], airport["longitude"]
        ),
        target_time=event.isoformat(),
        actual_integer=actual,
        metar_first_received=closure.isoformat(),
        metar_first_provider=reference.get("_closure_providers", []),
        initial_outcome_received=reference["_received"].isoformat(),
        previous_target_time=previous["_event"].isoformat(),
        previous_integer=int(previous["temperature_c"]),
        previous_metar_received=previous["_received"].isoformat(),
        observation_id=reading["id"],
        measurement_time=reading["_event"].isoformat(),
        pws_first_received=reading["_received"].isoformat(),
        raw_temperature_c=reading["temperature_c"],
        raw_predicted_integer=icao_round_temperature(reading["temperature_c"]),
        raw_correct=icao_round_temperature(reading["temperature_c"]) == actual,
        raw_temperature=reading.get("raw_temperature"),
        raw_unit=reading.get("raw_unit"),
        observation_age_at_receipt_seconds=reading["age_seconds"],
        age_at_decision_seconds=(at - reading["_event"]).total_seconds(),
        timestamp_provenance=reading["timestamp_provenance"],
        qc_status="VALID",
        method=method,
        offset_c=adjustment["offset_c"],
        offset_lower_c=adjustment["offset_lower_c"],
        offset_upper_c=adjustment["offset_upper_c"],
        calibration_n=adjustment["calibration_n"],
        calibration_history_available_by=adjustment["history_available_by"],
        calibration_reference_hash=hashlib.sha256(
            json.dumps(adjustment["calibration_reference_ids"], sort_keys=True).encode()
        ).hexdigest(),
        calibration_kind=adjustment.get("calibration_kind", "NO_CALIBRATION"),
        calibrated_temperature_c=temperature,
        predicted_integer=predicted,
        decision_time=at.isoformat(),
        phase=phase,
        lead_seconds=(closure - at).total_seconds(),
        interval_error=abs(interval_residual(temperature, actual)),
        correct=predicted == actual,
        persistence_correct=previous["temperature_c"] == actual,
        incremental_correct=predicted == actual and previous["temperature_c"] != actual,
        incremental_harm=predicted != actual and previous["temperature_c"] == actual,
        selected_at_decision=bool(station_selection and station_selection["selected"]),
        station_selection_id=station_selection["id"] if station_selection else None,
        selection_scope="HISTORICAL_STATION_LEDGER_NOT_RETROACTIVE_FILTER",
        valid_until=(reading["_event"] + timedelta(seconds=300)).isoformat(),
        measurement_offset_from_nominal_seconds=(reading["_event"] - event).total_seconds(),
        status="VALID",
        evidence=EVIDENCE,
    )
    return "VALID", result


def decision_times(
    sensor: dict[str, Any], reference: dict[str, Any], references: list[dict[str, Any]]
) -> tuple[list[datetime], list[dict[str, Any]]]:
    event, closure = reference["_event"], reference["_closure"]
    start = event - timedelta(minutes=10)
    times = {start, event}
    times.update(event + timedelta(seconds=s) for s in CHECKPOINTS)
    receipts = []
    for r in sensor["readings"]:
        if start <= r["_received"] < closure:
            times.add(r["_received"])
            receipts.append(r)
        if start <= r["_event"] + timedelta(seconds=300) + EPS < closure:
            times.add(r["_event"] + timedelta(seconds=300) + EPS)
    times.update(
        r["_received"] + EPS for r in references if start <= r["_received"] + EPS < closure
    )
    times.update(
        r["_ambiguous_from"]
        for r in references
        if r.get("_ambiguous_from") is not None and start <= r["_ambiguous_from"] < closure
    )
    times.update(t for t in sensor["metadata_times"] if start <= t < closure)
    for r in sensor["pairs"]:
        expiry = r["_event"] + timedelta(hours=12) + EPS
        if start <= expiry < closure:
            times.add(expiry)
        ambiguous = r.get("_ambiguous_from")
        if ambiguous is not None and start <= ambiguous < closure:
            times.add(ambiguous)
    times.update(t for t in sensor["conflicts"].values() if start <= t < closure)
    return sorted(t for t in times if start <= t < closure), sorted(
        receipts, key=lambda r: (r["_received"], r["id"])
    )


def search(data: dict[str, Any]) -> dict[str, Any]:
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    statuses: dict[tuple[str, ...], Counter[str]] = defaultdict(Counter)
    trajectories = []
    first_cases = []
    inventories = []
    for airport, airport_data in data.items():
        references = airport_data["references"]
        targets = [
            r
            for r in references
            if not r["startup_censored"]
            and not r["coverage_gap"]
            and not r.get("_closure_censored", False)
            and r.get("_ambiguous_from") is None
        ]
        for sensor in airport_data["sensors"].values():
            intervals = [
                (b["_event"] - a["_event"]).total_seconds()
                for a, b in zip(sensor["readings"], sensor["readings"][1:], strict=False)
                if b["_event"] > a["_event"]
            ]
            inventories.append(
                dict(
                    airport=airport,
                    station_id=sensor["station_id"],
                    sensor_id=sensor["sensor_id"],
                    provider=sensor["provider"],
                    distance_km=sensor["distance_km"],
                    sensor_type=sensor["sensor_type"],
                    stored_records=sensor["stored_count"],
                    valid_timestamp_readings=len(sensor["readings"]),
                    calibration_pair_cycles=len(sensor["pairs"]),
                    rejection_flags=dict(sensor["rejections"]),
                    median_update_interval_seconds=median(intervals) if intervals else None,
                    median_age_seconds=median(r["age_seconds"] for r in sensor["readings"])
                    if sensor["readings"]
                    else None,
                )
            )
            for target in targets:
                event, closure = target["_event"], target["_closure"]
                for seconds in CHECKPOINTS:
                    at = event + timedelta(seconds=seconds)
                    phase = "EXP_A" if seconds < 0 else "EXP_B"
                    label = f"T{seconds:+d}s"
                    for method in METHODS:
                        key = (airport, sensor["sensor_id"], method, label, phase)
                        status, record = candidate(
                            sensor, target, references, method, at, window=phase
                        )
                        statuses[key][status] += 1
                        if record is not None:
                            grouped[key].append({**record, "decision_label": label})
                times, receipts = decision_times(sensor, target, references)
                # Latest ACTUAL receipt, not best hindsight-correct receipt.
                for phase in ("EXP_A", "EXP_B"):
                    possible = [
                        r
                        for r in receipts
                        if (r["_received"] < event) == (phase == "EXP_A")
                        and asof_eligible(sensor, r, r["_received"])
                    ]
                    newest = possible[-1] if possible else None
                    for method in METHODS:
                        key = (airport, sensor["sensor_id"], method, "LATEST_RECEIPT", phase)
                        if newest is None:
                            statuses[key]["NO_ELIGIBLE_OBSERVATION"] += 1
                            continue
                        status, record = candidate(
                            sensor, target, references, method, newest["_received"], forced=newest
                        )
                        statuses[key][status] += 1
                        if record is not None:
                            grouped[key].append({**record, "decision_label": "LATEST_RECEIPT"})
                start = event - timedelta(minutes=10)
                if not any(
                    r["_received"] < closure
                    and r["_event"] + timedelta(seconds=300) >= start
                    and r["_event"] < closure
                    for r in sensor["readings"]
                ):
                    continue
                for method in METHODS:
                    points = []
                    records_by_time = {}
                    for at in times:
                        status, record = candidate(sensor, target, references, method, at)
                        if record is None:
                            points.append(dict(decision_time=at.isoformat(), status=status))
                        else:
                            points.append(
                                dict(
                                    decision_time=at.isoformat(),
                                    status="VALID",
                                    correct=record["correct"],
                                    valid_until=record["valid_until"],
                                    phase=record["phase"],
                                    input_id=record["observation_id"],
                                    predicted_integer=record["predicted_integer"],
                                )
                            )
                            records_by_time[clock(record["decision_time"])] = record
                    if not records_by_time:
                        continue
                    evaluated = analyze_trajectory(points, closure)
                    evaluated["search_start"] = (event - timedelta(minutes=10)).isoformat()
                    evaluated["first_correct_at_search_start"] = (
                        evaluated["first_correct"] == evaluated["search_start"]
                    )
                    descriptor = dict(
                        airport=airport,
                        station_id=sensor["station_id"],
                        sensor_id=sensor["sensor_id"],
                        method=method,
                        target_time=event.isoformat(),
                        **evaluated,
                    )
                    trajectories.append(descriptor)
                    for kind in ("first_correct", "first_stable_correct"):
                        if evaluated[kind] is not None:
                            record = records_by_time[clock(evaluated[kind])]
                            first_cases.append({**record, "search_kind": kind, **evaluated})
    summaries = []
    all_candidates = []
    raw_candidates = {
        (key[0], key[1], key[3], key[4], r["target_time"]): r
        for key, group in grouped.items()
        if key[2] == "CAL-0"
        for r in group
    }
    for group_key, counts in sorted(statuses.items()):
        airport, sensor_id, method, label, phase = group_key
        sensor = data[airport]["sensors"][sensor_id]
        records = grouped.get(group_key, [])
        summary = dict(
            airport=airport,
            station_id=sensor["station_id"],
            sensor_id=sensor_id,
            distance_km=sensor["distance_km"],
            method=method,
            decision_label=label,
            phase=phase,
            attempted_cycles=sum(counts.values()),
            status_counts=dict(counts),
            **summarize_candidates(records),
        )
        raw = [
            raw_candidates[(airport, sensor_id, label, phase, r["target_time"])] for r in records
        ]
        summary["raw_correct_on_same_cycles"] = sum(r["correct"] for r in raw)
        summary["calibration_gain_vs_raw"] = sum(
            r["correct"] and not b["correct"] for r, b in zip(records, raw, strict=True)
        )
        summary["calibration_harm_vs_raw"] = sum(
            not r["correct"] and b["correct"] for r, b in zip(records, raw, strict=True)
        )
        summaries.append(summary)
        all_candidates.extend(records)
    return dict(
        summaries=summaries,
        candidates=all_candidates,
        trajectories=trajectories,
        first_cases=first_cases,
        inventory=inventories,
    )


def choose_examples(result: dict[str, Any]) -> list[dict[str, Any]]:
    winners = [
        r
        for r in result["first_cases"]
        if r["method"] != "CAL-0" and r["incremental_correct"] and r["phase"] in ("EXP_A", "EXP_B")
    ]
    winners.sort(
        key=lambda r: (
            r["search_kind"] != "first_stable_correct",
            -r["lead_seconds"],
            r["airport"],
            r["sensor_id"],
            r["method"],
        )
    )
    chosen = []
    seen = set()
    for airport in AIRPORTS:
        row = next(
            (
                r
                for r in winners
                if r["airport"] == airport and (airport, r["target_time"]) not in seen
            ),
            None,
        )
        if row:
            chosen.append({**row, "example_class": "EXPLORATORY_INCREMENTAL_SUCCESS"})
            seen.add((airport, row["target_time"]))
    for row in winners:
        if len(chosen) >= 8:
            break
        identity = (row["airport"], row["target_time"])
        if identity not in seen:
            chosen.append({**row, "example_class": "EXPLORATORY_INCREMENTAL_SUCCESS"})
            seen.add(identity)
    failures = [
        r
        for r in result["candidates"]
        if r["method"] != "CAL-0"
        and r["incremental_harm"]
        and r["decision_label"] in ("T-60s", "LATEST_RECEIPT")
    ]
    failures.sort(key=lambda r: (r["airport"], r["target_time"], r["sensor_id"], r["method"]))
    for airport in AIRPORTS:
        positive = next((r for r in chosen if r["airport"] == airport), None)
        row = next(
            (
                r
                for r in failures
                if r["airport"] == airport
                and positive
                and r["sensor_id"] == positive["sensor_id"]
                and r["method"] == positive["method"]
            ),
            None,
        )
        if row is None:
            row = next((r for r in failures if r["airport"] == airport), None)
        if row:
            chosen.append({**row, "example_class": "PERSISTENCE_CORRECT_PWS_FALSE_ALARM"})
    companions = []
    for row in chosen:
        if row["example_class"] != "EXPLORATORY_INCREMENTAL_SUCCESS":
            continue
        earlier = next(
            (
                r
                for r in result["first_cases"]
                if r["airport"] == row["airport"]
                and r["sensor_id"] == row["sensor_id"]
                and r["method"] == row["method"]
                and r["target_time"] == row["target_time"]
                and r["search_kind"] == "first_correct"
                and r["decision_time"] != row["decision_time"]
            ),
            None,
        )
        if earlier:
            companions.append(
                {**earlier, "example_class": "EARLIER_CORRECT_STATE_SAME_CYCLE_NOT_ANOTHER_EVENT"}
            )
    return chosen + companions


def write_report(result: dict[str, Any], output: Path) -> None:
    scope = result["scope"]
    lines = [
        "# EXP-0010 — Early METAR temperature reconstruction",
        "",
        f"Frozen database cutoff: {result['manifest']['captured_at']}; SHA256 {result['manifest']['sha256']}. Baseline a473f6c.",
        "",
        "**Exploratory retrospective reconstructions are NOT actual immutable live forecasts.** A positive lead is relative to our earliest configured-provider receipt, not global publication or a trading advantage. Clock synchronization remains unverified. No collector, selection, QC, calibration or prediction writes/restarts.",
        "",
        "Protocol: docs/research/EXP0010_PROTOCOL.md. CAL-0 raw; CAL-1 all-prior median midpoint offset; CAL-2 trailing12h median midpoint offset, >=12 earlier received distinct nominal cycles. Offset±0.5°C is a quantization identification interval, not a confidence interval. Initial-version outcomes, all-version first-receipt closure; SPECI/COR-only/ambiguous targets excluded from primary scoring. No affine or tuned model search.",
        "",
        "## Search scope",
        "",
        "| Airport | Targets | Audited sensors | Valid timestamp sensors | >=12 pair cycles |",
        "|---|---:|---:|---:|---:|",
    ]
    for a, s in scope.items():
        lines.append(
            f"| {a} | {s['targets']} | {s['sensors']} | {s['valid_sensors']} | {s['calibratable_sensors']} |"
        )
    lines += [
        "",
        f"Methods3; fixed checkpoints {CHECKPOINTS}; latest actual receipt separately for EXP-A and EXP-B; every actual receipt plus parameter/expiry boundaries from T−10min to first receipt. Summary groups={len(result['summaries'])}; valid fixed/latest candidates={len(result['candidates'])}; these are repeated evaluations, NOT independent weather events. All sensors/methods/statuses appear in CSV, including no eligible input and insufficient history. Historic station selection annotates but never filters offline candidates.",
        "",
        "## Fixed T−60 and latest-receipt calibrated results",
        "",
        "| Airport / sensor | Method | Decision | Window | N | Correct | Raw SAME cycles | Persistence | Gain | Harm | Net | Correct changed | False changes | Median lead all/correct s |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for s in result["summaries"]:
        if s["method"] != "CAL-0" and s["decision_label"] in ("T-60s", "LATEST_RECEIPT") and s["n"]:
            lines.append(
                f"| {s['airport']} / {s['sensor_id']} | {s['method']} | {s['decision_label']} | {s['phase']} | {s['n']} | {s['correct']} | {s['raw_correct_on_same_cycles']} | {s['persistence_correct']} | {s['incremental_correct']} | {s['incremental_harm']} | {s['net_improvement']} | {s['correct_changes']} | {s['false_changes']} | {s['median_lead_seconds']:.2f}/{s['median_correct_lead_seconds']} |"
            )
    lines += [
        "",
        "## Actual examples — outcome-conditioned illustrations",
        "",
        "Examples favor stable incremental cases, airport representation, then lead. This is hindsight example selection, NOT an unbiased success rate. Complete failures and search scope are retained.",
        "Earlier-correct companion rows show the ACTUAL DIFFERENT inputs/offsets at the first correct state of the same cycle; do not count these as extra events. A first correct point at T−10 is left-censored by the search window, not proof the signal first began there.",
        "",
    ]
    for i, r in enumerate(result["examples"], 1):
        lines += [
            f"### Example{i}: {r['example_class']}",
            "",
            f"Airport {r['airport']}; station {r['station_id']}; sensor {r['sensor_id']}; distance {r['distance_km']:.3f}km.",
            f"Previous METAR {r['previous_integer']}°C, nominal {r['previous_target_time']}, received {r['previous_metar_received']}.",
            f"PWS measured {r['measurement_time']}; first received {r['pws_first_received']}; raw {r['raw_temperature_c']}°C; age {r['observation_age_at_receipt_seconds']:.3f}s; provenance {r['timestamp_provenance']}; QC {r['qc_status']}.",
            f"{r['method']}: offset {r['offset_c']:.4f}°C, quantization bounds [{r['offset_lower_c']:.4f},{r['offset_upper_c']:.4f}]°C; {r['calibration_n']} earlier cycles; latest calibration outcome received {r['calibration_history_available_by']}.",
            f"Calibrated {r['calibrated_temperature_c']:.4f}°C → integer {r['predicted_integer']}; RAW integer {r['raw_predicted_integer']} (raw correct={r['raw_correct']}); decision {r['decision_time']}; target nominal {r['target_time']}; first METAR received {r['metar_first_received']}; actual {r['actual_integer']}°C.",
            f"Lead {r['lead_seconds']:.3f}s ({r['lead_seconds'] / 60:.3f}min); {r['phase']}; persistence correct={r['persistence_correct']}; PWS correct={r['correct']}; selected then={r['selected_at_decision']}; {EVIDENCE}.",
            f"First correct {r.get('first_correct')}; first stable correct {r.get('first_stable_correct')}; correct→wrong reversals {r.get('correct_to_wrong_reversals')}; eligibility failures {r.get('eligibility_failure_count')}. A missing stability field means this failure example is from a fixed checkpoint/latest receipt, not a selected correct suffix.",
            "",
        ]
    lines += [
        "## Real prospective forecasts",
        "",
        "Original immutable production forecasts retain their original methods/parameters; none is relabeled CAL-1/CAL-2. A PWS contribution is association, not causal proof of sensor benefit. Same-airport/checkpoint/target recorded persistence comparisons below.",
        "",
        "```json",
        json.dumps(result["prospective"]["airports"], indent=2),
        "```",
        "",
        "| Actual T−60 model | Matched cycles | Correct | Recorded persistence | Incremental correct | Harm | Net |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for key, group in result["prospective"]["groups"].items():
        if "|T-60s|" in key and key.rsplit("|", 1)[-1] in ("nearest", "median", "inverse_distance"):
            m, b = group["matched_candidate"], group["matched_recorded_baseline"]
            lines.append(
                f"| {key} | {m['n']} | {m['correct_integer']} | {b['correct_integer']} | {group['matched_incremental_correct']} | {group['matched_incremental_harm']} | {group['matched_net_improvement']} |"
            )
    lines += [
        "",
        "## Interpretation and limitations",
        "",
        "Per-sensor results must be compared against persistence on their SAME eligible cycles. Do not rank raw percentages with unequal coverage; ranking CSV orders the predefined CAL-2/T−60 endpoint and marks N<30 insufficient. Search is exploratory across airports, sensors,3methods and many decision times; isolated wins are expected by chance. Earliest correct and first stable are outcome-conditioned diagnostics within the searched T−10min window. Stability checks expiry and calibration/reference/metadata events; pre-observation inputs carried past nominal do not count as new EXP-B data. Fixed EXP-B checkpoints require a first PWS receipt>=nominal. No confidence/significance claim from this short correlated sample. Offsets are estimated from integer-reference midpoint intervals, not precise airport truth. Installation/microclimate, provider update delays, gaps and unknown clock offset remain confounders.",
        "",
        "## Reproduce",
        "",
        "```powershell",
        "uv run python -m scripts.research.early_metar_reconstruction --snapshot data/research/exp0010/snapshot.sqlite3",
        "```",
        "",
        "Local snapshot/raw payloads remain ignored. Manifest and sanitized summaries/examples are committed; full candidate diagnostics remain in ignored data/research/exp0010. Never write reconstructed candidates to production prediction tables.",
    ]
    (output / "early_metar_reconstruction.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_findings(result: dict[str, Any], output: Path) -> None:
    # Numerical interpretation is tied to the preregistered snapshot, not a
    # template that may assert stale results for a different future dataset.
    if (
        result["manifest"]["sha256"]
        != "666b06cad15c99b9fe8442dca27b67a180187dfbf9b03c398790860a158fb99f"
    ):
        return
    lines = ["", "## Direct answers and candidate for future shadow test", ""]
    wins = [
        r for r in result["examples"] if r["example_class"] == "EXPLORATORY_INCREMENTAL_SUCCESS"
    ]
    lines += [
        "YES: calibrated PWS data recorded before our earliest METAR receipt can reconstruct changed integers that persistence misses. This is retrospective, exploratory information-availability evidence, NOT proof a rule was chosen or executed prospectively."
        if wins
        else "NO EVIDENCE OF EARLY METAR TEMPERATURE INFORMATION",
        "",
        "The illustrated calibrated wins also disclose RAW integer correctness; calibration is not credited when raw data already gave the same integer. Eight selected success examples are outcome-conditioned, not a denominator. All inferior groups/failures remain in the full summary CSV. Sensor.Community timestamp proxies do not become measurement clocks; unknown timestamps stay excluded.",
        "",
        "### Predefined endpoint: CAL-2 at T−60, descriptive leaders",
        "",
        "| Airport | Sensor | N | Calibrated | Raw SAME cycles | Persistence | Gain | Harm | Net | Correct changes / actual changes |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for airport in AIRPORTS:
        rows = [s for s in result["ranking"] if s["airport"] == airport and s["n"]]
        if not rows:
            lines.append(
                f"| {airport} | INSUFFICIENT DATA / already-received targets | 0 | — | — | — | — | — | — | — |"
            )
        else:
            s = rows[0]
            lines.append(
                f"| {airport} | {s['sensor_id']} | {s['n']} | {s['correct']} | {s['raw_correct_on_same_cycles']} | {s['persistence_correct']} | {s['incremental_correct']} | {s['incremental_harm']} | {s['net_improvement']} | {s['correct_changes']}/{s['actual_changed']} |"
            )
    lines += [
        "",
        "EDDM esride_krb1 (station5beb063756a15500193139f0, instrument5beb063756a15500193139f7,16.398km) is the most useful *candidate to investigate next*, not a validated winner. On its38 T−60/CAL-2 cycles calibrated22,raw21,persistence21: gain8,harm7,net+1. Its latest actual EXP-B receipt endpoint has33cycles,19correct vs18persistence, gain6,harm5,net+1. Thus repeated successes coexist with almost as many harms. Do not interpret the more favorable exploratory T+90 subset (17cycles,+4net) as an independently selected validated rule.",
        "",
        "EPWA SaveDnipro is relatively good in absolute agreement after calibration: T−60/CAL-2 eleven of17 vsraw6 andpersistence10, gain5/harm4. This is too small for ranking. EGLL wd3-5 improves raw agreement after calibration but still underperforms persistence. EHAM's early KNMI receipts close most late/pre-publication opportunities; CAL-1/T−300 for Diemen has9/21 vs14/21persistence (gain4/harm9). There is no calibrated EXP-B sample there. Original production PWS forecasts remain separate and mostly lose to recorded persistence; this does not invalidate the recorded candidate examples, but prevents a live-edge claim.",
        "",
        "### Frozen future rule proposal — NOT DEPLOYED",
        "",
        "Use ONLY the fixed EDDM instrument above, CAL-2. At EVERY new unique trustworthy source measurement receipt between nominal T−10min and the first recorded target METAR receipt, compute b=median(PWS_aligned−initial_METAR_integer) over earlier nominal cycles in the trailing12hours, with>=12distinct earlier cycles. All outcomes must have been received strictly before computation, all pair sensor data frozen as of their earlier outcome receipt. Estimate=raw_PWS−b; integer=ICAO nearest Celsius with exact ties toward warmer. Report b±0.5°C quantization bounds, not confidence. Require valid accepted measurement provenance, event<=creation, receipt<=creation, age<=300s, physical/exposure checks. Close on ANY provider/COR target receipt, including early KNMI. Persist actual calculation completion time and original input/calibration IDs; never timestamp the result as if computation were instantaneous.",
        "",
        "Emit every shadow revision (do NOT choose the retrospectively latest receipt); label EXP-A and EXP-B separately, with no old pre-nominal receipt relabeled as new EXP-B data. Freeze station/method/window/thresholds before future collection, keep all misses/gaps/reversals, and evaluate once per target/checkpoint with matched persistence. Suggested evaluation horizon>=7future local days,>=200matched cycles and>=30temperature transitions; report day-block uncertainty and no repeated peeking/threshold tuning. This experiment does not authorize activating or changing any production rule.",
        "",
        "Earliest-correct and first-stable results are in early_metar_stability.csv. An unchanged correct integer is not incremental information; gains require PWS correct AND previous METAR wrong. Temperatures at multiple instruments of one provider station are not independent physical weather stations. Cross-airport/sensor/model/time search creates substantial multiplicity; apparent+1nets are INSUFFICIENT DATA for a reliable actionable edge.",
    ]
    with (output / "early_metar_reconstruction.md").open("a", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")


def run(snapshot: Path, output: Path) -> dict[str, Any]:
    started = time.perf_counter()
    manifest = json.loads((snapshot.parent / "snapshot_manifest.json").read_text(encoding="utf-8"))
    if hashlib.sha256(snapshot.read_bytes()).hexdigest() != manifest["sha256"]:
        raise ValueError("Snapshot hash mismatch")
    with sqlite3.connect(snapshot.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        data = load_dataset(conn, clock(manifest["captured_at"]))
        prospective = audit_prospective(conn)
    result = search(data)
    result.update(manifest=manifest, prospective=prospective)
    result["scope"] = {
        a: dict(
            targets=len(
                [
                    r
                    for r in v["references"]
                    if not r["startup_censored"]
                    and not r["coverage_gap"]
                    and not r.get("_closure_censored", False)
                    and r.get("_ambiguous_from") is None
                ]
            ),
            sensors=len(v["sensors"]),
            valid_sensors=sum(bool(s["readings"]) for s in v["sensors"].values()),
            calibratable_sensors=sum(len(s["pairs"]) >= 12 for s in v["sensors"].values()),
            sensors_with_eligible_reconstructions=len(
                {r["sensor_id"] for r in result["summaries"] if r["airport"] == a and r["n"]}
            ),
            sensors_with_calibrated_reconstructions=len(
                {
                    r["sensor_id"]
                    for r in result["summaries"]
                    if r["airport"] == a and r["n"] and r["method"] != "CAL-0"
                }
            ),
            reference_exclusions=v["reference_exclusions"],
        )
        for a, v in data.items()
    }
    result["examples"] = choose_examples(result)
    ranking = [
        {**r, "ranking_status": "PROVISIONAL_EXPLORATORY" if r["n"] >= 30 else "INSUFFICIENT DATA"}
        for r in result["summaries"]
        if r["method"] == "CAL-2" and r["decision_label"] == "T-60s"
    ]
    ranking.sort(key=lambda r: (r["airport"], -r["net_improvement"], -r["n"], r["sensor_id"]))
    result["ranking"] = ranking
    output.mkdir(parents=True, exist_ok=True)
    plot_timeline(result["examples"], output / "early_metar_timeline.png")
    actual_summary = []
    for key, group in prospective["groups"].items():
        airport, checkpoint, method = key.split("|")
        actual_summary.append(
            dict(
                airport=airport,
                checkpoint=checkpoint,
                method=method,
                **group["matched_candidate"],
                recorded_persistence_correct=group["matched_recorded_baseline"]["correct_integer"],
                recorded_incremental_correct=group["matched_incremental_correct"],
                recorded_incremental_harm=group["matched_incremental_harm"],
                recorded_net_improvement=group["matched_net_improvement"],
                missing_recorded_baseline=group["missing_recorded_baseline"],
            )
        )
    for filename, content, fields in (
        (
            "early_metar_reference_receipts.csv",
            [r for airport_data in data.values() for r in airport_data.get("receipt_audit", [])],
            ["airport", "target_time", "provider", "first_received"],
        ),
        (
            "early_metar_reconstruction.csv",
            result["summaries"],
            ["airport", "station_id", "sensor_id", "method", "decision_label", "phase"],
        ),
        ("early_metar_examples.csv", result["examples"], ["airport", "sensor_id", "example_class"]),
        (
            "early_metar_sensor_ranking.csv",
            ranking,
            ["airport", "sensor_id", "method", "decision_label"],
        ),
        (
            "early_metar_sensor_inventory.csv",
            result["inventory"],
            ["airport", "station_id", "sensor_id"],
        ),
        (
            "early_metar_stability.csv",
            result["trajectories"],
            ["airport", "sensor_id", "method", "target_time"],
        ),
        (
            "early_metar_actual_forecasts.csv",
            prospective["valid"],
            ["airport_icao", "prediction_id"],
        ),
        ("early_metar_actual_summary.csv", actual_summary, ["airport", "checkpoint", "method"]),
        (
            "early_metar_actual_exclusions.csv",
            prospective["excluded"],
            ["airport_icao", "prediction_id"],
        ),
    ):
        export(output / filename, content, fields)
    (snapshot.parent / "reconstruction_details.json").write_text(
        json.dumps(result, default=str), encoding="utf-8"
    )
    manifest["analysis"] = dict(
        version=VERSION,
        python=sys.version,
        sqlite=sqlite3.sqlite_version,
        duration_seconds=time.perf_counter() - started,
        source_sha256={
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [
                Path(__file__),
                Path("scripts/research/early_metar_data.py"),
                Path("scripts/research/early_metar_metrics.py"),
                Path("scripts/research/early_metar_prospective.py"),
                Path("scripts/research/early_metar_timeline.py"),
                Path("docs/research/EXP0010_PROTOCOL.md"),
                Path("configs/timestamp-policy-v1.json"),
            ]
        },
    )
    compact = {
        k: v
        for k, v in result.items()
        if k not in ("candidates", "first_cases", "trajectories", "prospective")
    }
    compact["prospective"] = {
        k: v for k, v in prospective.items() if k not in ("valid", "excluded")
    }
    (output / "early_metar_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    (snapshot.parent / "summary.json").write_text(json.dumps(compact, indent=2), encoding="utf-8")
    write_report(result, output)
    write_findings(result, output)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot", type=Path, default=Path("data/research/exp0010/snapshot.sqlite3")
    )
    parser.add_argument("--output", type=Path, default=Path("reports/research"))
    args = parser.parse_args()
    result = run(args.snapshot, args.output)
    print(
        json.dumps(
            dict(
                scope=result["scope"],
                example_count=len(result["examples"]),
                seconds=result["manifest"]["analysis"]["duration_seconds"],
            ),
            indent=2,
        )
    )
