"""Pure evaluation helpers for EXP-0010; never create or modify predictions.

Outcomes are used only to evaluate already frozen candidate values. A distinct
METAR cycle is a sampling unit, not a claim of statistical independence.
"""

import math
from datetime import UTC, datetime
from statistics import median
from typing import Any


def _clock(value: Any) -> datetime:
    if value is None:
        raise ValueError("Missing timezone-aware clock")
    try:
        parsed = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Invalid timezone-aware clock") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Timezone-aware clock required")
    return parsed.astimezone(UTC)


def _number(value: Any, *, integer: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Finite numeric value required")
    parsed = float(value)
    if not math.isfinite(parsed) or (integer and not parsed.is_integer()):
        raise ValueError("Finite integer required" if integer else "Finite number required")
    return parsed


def summarize_candidates(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate one airport/sensor/method/decision/window group on matched cycles.

    Every record must contain target_time, predicted_integer, actual_integer,
    previous_integer, positive lead_seconds, EXP_A/EXP_B phase, nonnegative
    interval_error, and boolean selected_at_decision. Duplicate canonical target
    clocks are rejected: callers must not pool checkpoints as independent cycles.
    """
    targets: set[datetime] = set()
    correct = persistence = incremental_correct = incremental_harm = 0
    changed = correct_changes = missed_changes = false_changes = correct_unchanged = 0
    selected = pre_successes = post_successes = pre_incremental = post_incremental = 0
    leads: list[float] = []
    correct_leads: list[float] = []
    interval_errors: list[float] = []
    integer_errors: list[float] = []
    for record in records:
        target = _clock(record.get("target_time"))
        if target in targets:
            raise ValueError("Duplicate target cycle in candidate summary")
        targets.add(target)
        actual = _number(record.get("actual_integer"), integer=True)
        previous = _number(record.get("previous_integer"), integer=True)
        predicted = _number(record.get("predicted_integer"), integer=True)
        lead = _number(record.get("lead_seconds"))
        interval_error = _number(record.get("interval_error"))
        if lead <= 0 or interval_error < 0:
            raise ValueError("Positive information lead and nonnegative interval error required")
        phase = record.get("phase")
        if phase not in {"EXP_A", "EXP_B"}:
            raise ValueError("EXP_A or EXP_B phase required")
        selected_flag = record.get("selected_at_decision")
        if not isinstance(selected_flag, bool):
            raise ValueError("Boolean historical selection flag required")
        hit = predicted == actual
        baseline_hit = previous == actual
        change = actual != previous
        gain = hit and not baseline_hit
        harm = baseline_hit and not hit
        correct += hit
        persistence += baseline_hit
        incremental_correct += gain
        incremental_harm += harm
        changed += change
        correct_changes += change and hit
        missed_changes += change and not hit
        false_changes += not change and predicted != previous
        correct_unchanged += not change and hit
        selected += selected_flag
        pre_successes += hit and phase == "EXP_A"
        post_successes += hit and phase == "EXP_B"
        pre_incremental += gain and phase == "EXP_A"
        post_incremental += gain and phase == "EXP_B"
        leads.append(lead)
        interval_errors.append(interval_error)
        integer_errors.append(predicted - actual)
        if hit:
            correct_leads.append(lead)
    n = len(records)
    return dict(
        n=n,
        distinct_cycles=len(targets),
        correct=correct,
        exact_accuracy=correct / n if n else None,
        persistence_correct=persistence,
        persistence_accuracy=persistence / n if n else None,
        incremental_correct=incremental_correct,
        incremental_harm=incremental_harm,
        net_improvement=incremental_correct - incremental_harm,
        actual_changed=changed,
        actual_unchanged=n - changed,
        correct_changes=correct_changes,
        missed_changes=missed_changes,
        false_changes=false_changes,
        correct_unchanged=correct_unchanged,
        median_lead_seconds=median(leads) if leads else None,
        median_correct_lead_seconds=median(correct_leads) if correct_leads else None,
        pre_observation_successes=pre_successes,
        pre_publication_successes=post_successes,
        pre_observation_incremental_correct=pre_incremental,
        pre_publication_incremental_correct=post_incremental,
        selected_n=selected,
        unselected_n=n - selected,
        mean_interval_error=sum(interval_errors) / n if n else None,
        integer_mae=sum(abs(error) for error in integer_errors) / n if n else None,
        integer_bias=sum(integer_errors) / n if n else None,
        status="PRELIMINARY" if n >= 30 else "INSUFFICIENT DATA",
    )


def analyze_trajectory(points: list[dict[str, Any]], closure: datetime) -> dict[str, Any]:
    """Evaluate first correct and final uninterrupted correct suffix before receipt.

    Decisions must be unique and strictly before closure. VALID points require
    boolean correct and valid_until>=decision. Failed points may omit expiry and
    always break stability. A candidate is stable only if its correct suffix has
    no expiry/eligibility gap and covers closure. Exact expiry equality is valid.
    This is outcome-conditioned evaluation, never a retrospective live forecast.
    """
    end = _clock(closure)
    prepared: list[tuple[datetime, datetime | None, dict[str, Any]]] = []
    seen: set[datetime] = set()
    for point in points:
        decision = _clock(point.get("decision_time"))
        if decision >= end:
            raise ValueError("Trajectory decision must precede first METAR receipt")
        if decision in seen:
            raise ValueError("Duplicate trajectory decision")
        seen.add(decision)
        expiry = None
        if point.get("status") == "VALID":
            if not isinstance(point.get("correct"), bool):
                raise ValueError("VALID trajectory point requires boolean correctness")
            expiry = _clock(point.get("valid_until"))
            if expiry < decision:
                raise ValueError("Trajectory candidate expired before decision")
        prepared.append((decision, expiry, point))
    prepared.sort(key=lambda entry: entry[0])
    valid = [entry for entry in prepared if entry[1] is not None]
    correct = [entry for entry in valid if entry[2]["correct"]]
    first = correct[0] if correct else None

    # Work backwards: an earlier correct point may extend an already complete
    # suffix only when its validity reaches the suffix's start without a gap.
    stable: tuple[datetime, datetime | None, dict[str, Any]] | None = None
    covered_from = end
    for entry in reversed(prepared):
        decision, expiry, point = entry
        if expiry is None or not point["correct"] or expiry < covered_from:
            break
        stable = entry
        covered_from = decision

    reversals = correct_to_wrong = wrong_to_correct = gaps = 0
    for previous, current in zip(valid, valid[1:], strict=False):
        if previous[2]["correct"] != current[2]["correct"]:
            reversals += 1
            correct_to_wrong += previous[2]["correct"] and not current[2]["correct"]
            wrong_to_correct += not previous[2]["correct"] and current[2]["correct"]
    for previous, current in zip(prepared, prepared[1:], strict=False):
        if previous[1] is not None and previous[1] < current[0]:
            gaps += 1
    if prepared and prepared[-1][1] is not None and prepared[-1][1] < end:
        gaps += 1

    def revisions(key: str) -> int:
        values = [entry[2][key] for entry in valid if entry[2].get(key) is not None]
        return sum(a != b for a, b in zip(values, values[1:], strict=False))

    return dict(
        decision_count=len(prepared),
        valid_prediction_count=len(valid),
        wrong_prediction_count=sum(not entry[2]["correct"] for entry in valid),
        eligibility_failure_count=len(prepared) - len(valid),
        freshness_gap_count=gaps,
        first_correct=first[0].isoformat() if first else None,
        first_correct_phase=first[2].get("phase") if first else None,
        first_correct_lead_seconds=(end - first[0]).total_seconds() if first else None,
        first_stable_correct=stable[0].isoformat() if stable else None,
        first_stable_correct_phase=stable[2].get("phase") if stable else None,
        first_stable_correct_lead_seconds=(end - stable[0]).total_seconds() if stable else None,
        correctness_reversals=reversals,
        correct_to_wrong_reversals=correct_to_wrong,
        wrong_to_correct_reversals=wrong_to_correct,
        input_revisions=revisions("input_id"),
        prediction_revisions=revisions("predicted_integer"),
        stability_definition="FINAL_CONTIGUOUS_CORRECT_ELIGIBLE_SUFFIX_COVERS_FIRST_RECEIPT",
        evidence="RETROSPECTIVE_AS_OF_RECONSTRUCTION_EVALUATION",
    )
