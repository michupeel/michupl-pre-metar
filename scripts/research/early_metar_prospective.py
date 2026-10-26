"""Read-only audit of ACTUAL immutable forecasts; no reconstructed candidates.

The caller supplies an offline/read-only SQLite connection. No migration,
settlement, exclusion insertion or model execution occurs in this module.
"""

import json
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from statistics import mean, median
from typing import Any

from premetar.pws.analysis import interval_residual
from premetar.pws.integrity import prediction_issues
from premetar.pws.repository import rows
from premetar.pws.timestamps import parse_utc

AIRPORTS = ("EDDM", "EHAM", "EPWA", "EGLL")


def _clock(value: Any) -> datetime:
    parsed = parse_utc(value)
    if parsed is None:
        raise ValueError("Missing clock")
    return parsed


def reference_targets(conn: sqlite3.Connection) -> dict[str, dict[datetime, dict[str, Any]]]:
    """Initial routine outcomes and earliest closure across all versions/providers."""
    grouped: dict[tuple[str, datetime], dict[str, dict[str, Any]]] = defaultdict(dict)
    for r in rows(
        conn,
        """SELECT o.*,r.collector_receive_time receipt FROM observations o
        JOIN report_receipts r ON r.observation_id=o.id
        WHERE o.product_type='METAR' AND o.station_icao IN ('EDDM','EHAM','EPWA','EGLL')""",
    ):
        try:
            event, received = _clock(r["event_time"]), _clock(r["receipt"])
            payload = json.loads(r["data_json"])
        except (ValueError, TypeError, OverflowError):
            continue
        group = grouped[(r["station_icao"], event)]
        old = group.get(r["identity"])
        if old is None or received < old["received"]:
            group[r["identity"]] = dict(
                identity=r["identity"],
                event=event,
                received=received,
                temperature=r["temperature_c"],
                correction=bool(payload.get("cor")),
                startup_censored=bool(r["startup_censored"]),
                coverage_gap=bool(r["coverage_gap"]),
            )
    result: dict[str, dict[datetime, dict[str, Any]]] = {a: {} for a in AIRPORTS}
    for (airport, event), versions in grouped.items():
        copies = list(versions.values())
        first = min(copies, key=lambda r: r["received"])
        initial = [r for r in copies if not r["correction"] and r["temperature"] is not None]
        reason = None
        if not initial:
            reason = "NO_INITIAL_ROUTINE_OUTCOME"
            chosen = None
        elif len({r["temperature"] for r in initial}) != 1:
            reason = "AMBIGUOUS_INITIAL_TEMPERATURE"
            chosen = None
        else:
            chosen = min(initial, key=lambda r: r["received"])
            value = chosen["temperature"]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or int(value) != value
            ):
                reason = "INVALID_INITIAL_TEMPERATURE"
            if (
                first["startup_censored"]
                or first["coverage_gap"]
                or chosen["startup_censored"]
                or chosen["coverage_gap"]
            ):
                reason = "CENSORED_REFERENCE_RECEIPT"
        result[airport][event] = dict(
            target=event,
            closure=first["received"],
            chosen=chosen,
            exclusion=reason,
            versions=len(versions),
        )
    return result


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    """One record per target/checkpoint/method, no summing checkpoints as events."""
    n = len(records)
    correct = [r["predicted_integer"] == r["actual_integer"] for r in records]
    persistent = [r["previous_integer"] == r["actual_integer"] for r in records]
    changes = [r for r in records if r["actual_integer"] != r["previous_integer"]]
    incremental = sum(p and not b for p, b in zip(correct, persistent, strict=True))
    harm = sum(b and not p for p, b in zip(correct, persistent, strict=True))
    return dict(
        n=n,
        distinct_cycles=len({r["target_time"] for r in records}),
        correct_integer=sum(correct),
        exact_accuracy=mean(correct) if n else None,
        persistence_correct=sum(persistent),
        persistence_accuracy=mean(persistent) if n else None,
        incremental_correct=incremental,
        incremental_harm=harm,
        net_improvement=incremental - harm,
        transition_cycles=len(changes),
        correct_transitions=sum(r["predicted_integer"] == r["actual_integer"] for r in changes),
        missed_transitions=sum(r["predicted_integer"] == r["previous_integer"] for r in changes),
        wrong_changed_integer=sum(r["predicted_integer"] != r["actual_integer"] for r in changes),
        correct_unchanged_cycles=sum(
            r["actual_integer"] == r["previous_integer"]
            and r["predicted_integer"] == r["actual_integer"]
            for r in records
        ),
        false_transition_alarms=sum(
            r["actual_integer"] == r["previous_integer"]
            and r["predicted_integer"] != r["previous_integer"]
            for r in records
        ),
        mean_interval_error=mean(r["interval_error"] for r in records) if n else None,
        median_information_lead_seconds=median(r["lead_seconds"] for r in records) if n else None,
        evidence="ACTUAL_IMMUTABLE_FORECAST",
    )


def match_recorded_baselines(valid: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Earliest actual forecast per method/checkpoint/target, deterministic ties."""
    unique: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for r in sorted(valid, key=lambda x: (_clock(x["created_at"]), x["prediction_id"])):
        unique.setdefault((r["airport_icao"], r["checkpoint"], r["target_time"], r["method"]), r)
    baseline = {k[:3]: r for k, r in unique.items() if k[3] == "previous_metar"}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in unique.values():
        grouped[f"{r['airport_icao']}|{r['checkpoint']}|{r['method']}"].append(r)
    result = {}
    for key, records in sorted(grouped.items()):
        matched = [
            r for r in records if (r["airport_icao"], r["checkpoint"], r["target_time"]) in baseline
        ]
        paired = [
            (r, baseline[(r["airport_icao"], r["checkpoint"], r["target_time"])]) for r in matched
        ]
        incremental = sum(
            r["predicted_integer"] == r["actual_integer"]
            and b["predicted_integer"] != b["actual_integer"]
            for r, b in paired
        )
        harm = sum(
            b["predicted_integer"] == b["actual_integer"]
            and r["predicted_integer"] != r["actual_integer"]
            for r, b in paired
        )
        result[key] = dict(
            all_valid=summarize_records(records),
            matched_candidate=summarize_records(matched),
            matched_recorded_baseline=summarize_records([b for _, b in paired]),
            matched_incremental_correct=incremental,
            matched_incremental_harm=harm,
            matched_net_improvement=incremental - harm,
            missing_recorded_baseline=len(records) - len(matched),
        )
    return result


def audit_prospective(conn: sqlite3.Connection) -> dict[str, Any]:
    """Audit all recorded airport forecasts, retaining explicit exclusions/pending."""
    references = reference_targets(conn)
    ledger: dict[str, set[str]] = defaultdict(set)
    for r in rows(conn, "SELECT prediction_id,reason FROM prediction_exclusions"):
        ledger[r["prediction_id"]].add(r["reason"])
    settlements: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows(conn, "SELECT * FROM continuous_settlements ORDER BY id"):
        settlements[r["prediction_id"]].append(r)
    valid: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for r in rows(
        conn,
        "SELECT * FROM pws_predictions WHERE airport_icao IN ('EDDM','EHAM','EPWA','EGLL') ORDER BY created_at,id",
    ):
        airport, identity = r["airport_icao"], r["id"]
        counts[airport] += 1
        reasons = set(ledger[identity])
        try:
            pred = json.loads(r["data_json"])
            created, target = _clock(r["created_at"]), _clock(r["target_time"])
            # JSON cannot override the immutable relational clocks or station identity.
            pred = {
                **pred,
                "id": identity,
                "airport_icao": airport,
                "created_at": r["created_at"],
                "target_time": r["target_time"],
            }
            reasons.update(reason for reason, _ in prediction_issues(conn, pred))
            ref = references[airport].get(target)
            if ref and created >= ref["closure"]:
                reasons.add("TARGET_ALREADY_RECEIVED")
            if ref and ref["exclusion"]:
                reasons.add(ref["exclusion"])
            if (
                not math.isfinite(pred["estimate_c"])
                or isinstance(pred["integer_temperature"], bool)
                or int(pred["integer_temperature"]) != pred["integer_temperature"]
            ):
                reasons.add("INVALID_PREDICTED_TEMPERATURE")
        except (ValueError, TypeError, KeyError, OverflowError):
            excluded.append(
                dict(
                    airport_icao=airport,
                    prediction_id=identity,
                    status="EXCLUDED",
                    reasons=["MALFORMED_PREDICTION"],
                    outcome_available=False,
                )
            )
            continue
        chosen = ref["chosen"] if ref else None
        settlement = next(
            (
                s
                for s in settlements[identity]
                if chosen and s["report_identity"] == chosen["identity"]
            ),
            None,
        )
        if settlement:
            evidence = json.loads(settlement["data_json"])
            if (
                not evidence.get("valid_prospective")
                or evidence.get("startup_censored")
                or evidence.get("coverage_gap")
            ):
                reasons.add("SETTLEMENT_NOT_UNCENSORED_PROSPECTIVE")
        if reasons or chosen is None or settlement is None:
            excluded.append(
                dict(
                    airport_icao=airport,
                    prediction_id=identity,
                    target_time=target.isoformat(),
                    created_at=created.isoformat(),
                    status="EXCLUDED" if reasons else "PENDING_OUTCOME_OR_SETTLEMENT",
                    reasons=sorted(reasons),
                    outcome_available=chosen is not None,
                    settlement_available=settlement is not None,
                )
            )
            continue
        assert ref is not None
        previous = [
            v["chosen"]
            for event, v in references[airport].items()
            if event < target
            and event <= created
            and v["chosen"] is not None
            and v["chosen"]["received"] <= created
        ]
        if not previous:
            excluded.append(
                dict(
                    airport_icao=airport,
                    prediction_id=identity,
                    status="EXCLUDED",
                    reasons=["NO_PREVIOUS_INITIAL_REPORT"],
                    outcome_available=True,
                )
            )
            continue
        prev = max(previous, key=lambda p: p["event"])
        inputs = pred.get("input_observation_ids", [])
        stations = sorted(
            {x["station_id"] for x in pred.get("contributions", []) if x.get("station_id")}
        )
        valid.append(
            dict(
                airport_icao=airport,
                prediction_id=identity,
                created_at=created.isoformat(),
                target_time=target.isoformat(),
                checkpoint=str(pred.get("checkpoint") or "UNSCHEDULED"),
                method=pred.get("method") or "UNKNOWN",
                predicted_integer=int(pred["integer_temperature"]),
                calibrated_temperature_c=pred["estimate_c"],
                actual_integer=int(chosen["temperature"]),
                previous_integer=int(prev["temperature"]),
                previous_metar_receipt=prev["received"].isoformat(),
                reference_first_seen=ref["closure"].isoformat(),
                interval_error=abs(interval_residual(pred["estimate_c"], chosen["temperature"])),
                lead_seconds=(ref["closure"] - created).total_seconds(),
                experiment_window="EXP-A" if created < target else "EXP-B",
                input_observation_ids=inputs,
                contribution_station_ids=stations,
                has_pws_input=any(isinstance(x, str) for x in inputs),
                evidence="ACTUAL_IMMUTABLE_FORECAST",
                attribution="Input inclusion does not establish causal sensor benefit",
            )
        )
    airports = {}
    for airport in AIRPORTS:
        good = [r for r in valid if r["airport_icao"] == airport]
        bad = [r for r in excluded if r["airport_icao"] == airport]
        airports[airport] = dict(
            total_predictions=counts[airport],
            valid_forecasts=len(good),
            excluded_forecasts=sum(r["status"] == "EXCLUDED" for r in bad),
            pending_forecasts=sum(r["status"] != "EXCLUDED" for r in bad),
            distinct_valid_cycles=len({r["target_time"] for r in good}),
            exclusion_flags=dict(Counter(reason for r in bad for reason in r["reasons"])),
        )
    return dict(
        airports=airports,
        groups=match_recorded_baselines(valid),
        valid=valid,
        excluded=excluded,
        scope="Recorded models and original parameters only; no forecast creation",
        reference_scope="Earliest receipt among configured providers, not worldwide publication",
    )
