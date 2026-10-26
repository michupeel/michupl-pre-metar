"""Synthetic counterexamples for EXP-0010; these are never observed results."""

import copy
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.research.early_metar_metrics import (  # noqa: E402
    analyze_trajectory,
    summarize_candidates,
)


def candidate(
    target: str, actual: int, previous: int, predicted: int, phase: str = "EXP_A"
) -> dict:
    return dict(
        target_time=target,
        actual_integer=actual,
        previous_integer=previous,
        predicted_integer=predicted,
        lead_seconds=120,
        phase=phase,
        interval_error=0.5,
        selected_at_decision=True,
    )


def point(second: int, correct: bool | None, expiry: int = 600, *, status: str = "VALID") -> dict:
    return dict(
        decision_time=datetime(2026, 10, 26, 12, second // 60, second % 60, tzinfo=UTC).isoformat(),
        correct=correct,
        valid_until=datetime(2026, 10, 26, 12, expiry // 60, expiry % 60, tzinfo=UTC).isoformat(),
        status=status,
        phase="EXP_A",
    )


def test_counts_match_persistence_on_exact_same_cycles_and_do_not_mutate() -> None:
    records = [
        candidate("2026-10-26T12:00:00Z", 11, 10, 11),
        candidate("2026-10-26T12:30:00Z", 10, 10, 11, "EXP_B"),
        candidate("2026-10-26T13:00:00Z", 9, 10, 11),
        candidate("2026-10-26T13:30:00Z", 8, 8, 8),
    ]
    original = copy.deepcopy(records)
    result = summarize_candidates(records)
    assert result["n"] == result["distinct_cycles"] == 4
    assert result["correct"] == result["persistence_correct"] == 2
    assert result["incremental_correct"] == result["incremental_harm"] == 1
    assert result["net_improvement"] == 0
    assert result["correct_changes"] == result["missed_changes"] == 1
    assert result["false_changes"] == result["correct_unchanged"] == 1
    assert result["pre_observation_successes"] == 2
    assert result["pre_publication_successes"] == 0
    assert result["pre_observation_incremental_correct"] == 1
    assert records == original


def test_empty_summary_and_duplicate_utc_target_identity() -> None:
    result = summarize_candidates([])
    assert result["n"] == 0 and result["exact_accuracy"] is None
    assert result["median_lead_seconds"] is None
    records = [
        candidate("2026-10-26T12:00:00Z", 10, 10, 10),
        candidate("2026-10-26T13:00:00+01:00", 10, 10, 10),
    ]
    with pytest.raises(ValueError, match="Duplicate"):
        summarize_candidates(records)


@pytest.mark.parametrize(
    "field,value",
    [
        ("actual_integer", True),
        ("predicted_integer", 10.5),
        ("interval_error", float("nan")),
        ("lead_seconds", 0),
        ("lead_seconds", float("inf")),
        ("selected_at_decision", 1),
        ("target_time", None),
        ("target_time", "2026-10-26T12:00:00"),
        ("phase", "POST"),
    ],
)
def test_invalid_summary_data_is_not_silently_counted(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        summarize_candidates([{**candidate("2026-10-26T12:00:00Z", 10, 10, 10), field: value}])


def test_first_correct_and_stable_suffix_differ_after_reversal() -> None:
    points = [
        point(60, True, 180),
        point(180, False, 300),
        point(300, True, 480),
        point(480, True, 600),
    ]
    original = copy.deepcopy(points)
    result = analyze_trajectory(list(reversed(points)), datetime(2026, 10, 26, 12, 10, tzinfo=UTC))
    assert result["first_correct"] == "2026-10-26T12:01:00+00:00"
    assert result["first_stable_correct"] == "2026-10-26T12:05:00+00:00"
    assert result["correctness_reversals"] == 2
    assert result["wrong_prediction_count"] == 1
    assert result["first_stable_correct_lead_seconds"] == 300
    assert points == original


def test_freshness_gap_breaks_stability_but_later_suffix_can_recover() -> None:
    result = analyze_trajectory(
        [point(60, True, 120), point(180, True, 600)], datetime(2026, 10, 26, 12, 10, tzinfo=UTC)
    )
    assert result["first_correct"] == "2026-10-26T12:01:00+00:00"
    assert result["first_stable_correct"] == "2026-10-26T12:03:00+00:00"
    assert result["freshness_gap_count"] == 1
    assert result["correctness_reversals"] == 0


def test_expired_final_point_cannot_claim_stability_to_receipt() -> None:
    result = analyze_trajectory([point(60, True, 599)], datetime(2026, 10, 26, 12, 10, tzinfo=UTC))
    assert result["first_correct"] is not None
    assert result["first_stable_correct"] is None
    assert result["freshness_gap_count"] == 1
    equality = analyze_trajectory(
        [point(60, True, 600)], datetime(2026, 10, 26, 12, 10, tzinfo=UTC)
    )
    assert equality["first_stable_correct"] is not None


def test_explicit_eligibility_failure_breaks_otherwise_correct_suffix() -> None:
    result = analyze_trajectory(
        [
            point(60, True, 600),
            point(180, None, status="NO_ELIGIBLE_OBSERVATION"),
            point(300, True, 600),
        ],
        datetime(2026, 10, 26, 12, 10, tzinfo=UTC),
    )
    assert result["first_stable_correct"] == "2026-10-26T12:05:00+00:00"
    assert result["eligibility_failure_count"] == 1


@pytest.mark.parametrize(
    "points",
    [
        [point(600, True, 600)],
        [point(601, True, 700)],
        [point(60, True, 600), point(60, True, 600)],
        [{**point(60, True, 600), "valid_until": None}],
        [{**point(60, True, 600), "decision_time": "2026-10-26T12:01:00"}],
    ],
)
def test_late_duplicate_and_untrusted_trajectory_clocks_are_rejected(points: list[dict]) -> None:
    with pytest.raises(ValueError):
        analyze_trajectory(points, datetime(2026, 10, 26, 12, 10, tzinfo=UTC))


def test_empty_trajectory_has_no_success() -> None:
    result = analyze_trajectory([], datetime(2026, 10, 26, 12, 10, tzinfo=UTC))
    assert result["first_correct"] is result["first_stable_correct"] is None
    assert result["wrong_prediction_count"] == result["decision_count"] == 0
