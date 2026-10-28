"""Labeled synthetic forecasts/references; no fabricated observed archive data."""

import json
import math
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from premetar.dashboard.calibration import METHODS, evaluate, horizon_bin
from premetar.pws.daily_time import local_day_bounds

BASE = datetime(2026, 10, 1, tzinfo=UTC)


def run(
    decision: datetime,
    points: list[tuple[datetime, float]],
    model: str = "icon",
    kind: str = "PROSPECTIVE_CAPTURED",
    identity: str | None = None,
) -> dict[str, Any]:
    return dict(
        model=model,
        run_id=identity or f"{model}-{decision.isoformat()}",
        initialization_time=(decision - timedelta(hours=6)).isoformat(),
        first_received=decision.isoformat(),
        decision_time=decision.isoformat(),
        availability_time=None,
        availability_class=kind,
        points=[dict(valid_time=event.isoformat(), temperature_c=temp) for event, temp in points],
    )


def ref(
    event: datetime,
    temperature: int = 10,
    *,
    received: datetime | None = None,
    correction: bool = False,
    identity: str | None = None,
) -> dict[str, Any]:
    return dict(
        observation_time_utc=event.isoformat(),
        first_received_utc=(received or event + timedelta(minutes=3)).isoformat(),
        temperature_c=temperature,
        report_identity=identity or f"report-{event.isoformat()}-{correction}",
        report_type="METAR",
        correction=correction,
        quantized=True,
    )


def row(result: dict[str, Any], run_id: str, method: str = "GLOBAL_MEDIAN") -> dict[str, Any]:
    return next(r for r in result["records"] if r["run_id"] == run_id and r["method"] == method)


def training() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    runs = []
    refs = []
    for d in range(3):
        decision = BASE + timedelta(days=d)
        points = [(decision + timedelta(hours=h), 12.0) for h in range(8)]
        runs.append(run(decision, points))
        refs.extend(ref(event) for event, _ in points)
    return runs, refs


def test_global_midpoint_median_uses_only24_prior_targets_across3days() -> None:
    runs, refs = training()
    decision = BASE + timedelta(days=3)
    runs.append(run(decision, [(decision + timedelta(hours=1), 12.0)], identity="future"))
    refs.append(ref(decision + timedelta(hours=1), 14))
    result = evaluate(runs, refs)
    output = row(result, "future")
    assert output["parameters"]["fit_n"] == 24
    assert output["parameters"]["fit_days"] == 3
    assert output["parameters"]["correction_c"] == 2
    assert output["calibrated_temperature_c"] == 10
    assert output["actual_metar_integer"] == 14
    assert not output["exact_integer_match"]
    assert output["parameters"]["semantics"] == "QUANTIZED_REFERENCE_MIDPOINT_ESTIMATE"
    assert output["parameters"]["reference_interval_ambiguity_c"] == [-0.5, 0.5]


def test_missing_history_falls_back_to_raw_on_same_target_pairs() -> None:
    decision = BASE
    result = evaluate(
        [run(decision, [(decision + timedelta(hours=1), 12.0)], identity="one")],
        [ref(decision + timedelta(hours=1))],
    )
    assert len(result["records"]) == len(METHODS)
    for method in ("GLOBAL_MEDIAN", "HOUR_HORIZON_MEDIAN", "CAUSAL_NOWCAST"):
        output = row(result, "one", method)
        assert output["fallback_raw"]
        assert output["calibrated_temperature_c"] == output["raw_temperature_c"]
    assert len({r["reference_id"] for r in result["records"]}) == 1


def test_multiple_forecasts_of_same_target_do_not_inflate_training_minimum() -> None:
    event = BASE + timedelta(hours=12)
    runs = [run(BASE + timedelta(minutes=i), [(event, 12.0)], identity=str(i)) for i in range(30)]
    decision = BASE + timedelta(days=1)
    runs.append(run(decision, [(decision + timedelta(hours=1), 12.0)], identity="later"))
    result = evaluate(runs, [ref(event), ref(decision + timedelta(hours=1))])
    output = row(result, "later")
    assert output["parameters"]["fit_n"] == 1
    assert output["fallback_raw"]


def test_three_day_guard_is_separate_from24samples() -> None:
    points = [(BASE + timedelta(hours=h), 12.0) for h in range(24)]
    decision = BASE + timedelta(days=1, hours=1)
    result = evaluate(
        [
            run(BASE, points),
            run(decision, [(decision + timedelta(hours=1), 12.0)], identity="future"),
        ],
        [*(ref(event) for event, _ in points), ref(decision + timedelta(hours=1))],
    )
    output = row(result, "future")
    assert output["parameters"]["fit_n"] == 24
    assert output["parameters"]["fit_days"] < 3
    assert output["fallback_raw"]


def test_delayed_reference_does_not_enter_training_before_receipt() -> None:
    runs, refs = training()
    decision = BASE + timedelta(days=3)
    refs[-1]["first_received_utc"] = (decision + timedelta(hours=3)).isoformat()
    runs.append(run(decision, [(decision + timedelta(hours=1), 12.0)], identity="future"))
    refs.append(ref(decision + timedelta(hours=1)))
    output = row(evaluate(runs, refs), "future")
    assert output["parameters"]["fit_n"] == 23
    assert output["fallback_raw"]


def test_future_conflicting_reference_cannot_retroactively_change_training_cohort() -> None:
    runs, refs = training()
    decision = BASE + timedelta(days=3)
    target = decision + timedelta(hours=1)
    runs.append(run(decision, [(target, 12.0)], identity="future"))
    refs.append(ref(target))
    before = row(evaluate(runs, refs), "future")
    refs.append(ref(BASE, 15, received=decision + timedelta(hours=2), identity="later-conflict"))
    after = row(evaluate(runs, refs), "future")
    assert before["parameters"]["fit_n"] == after["parameters"]["fit_n"] == 24
    assert before["parameters"]["correction_c"] == after["parameters"]["correction_c"]


def test_same_run_later_hours_never_train_other_hours() -> None:
    points = [(BASE + timedelta(hours=h), 12.0) for h in range(30)]
    result = evaluate([run(BASE, points, identity="long")], [ref(event) for event, _ in points])
    assert all(
        r["parameters"]["fit_n"] == 0 for r in result["records"] if r["method"] == "GLOBAL_MEDIAN"
    )


def test_nowcast_correction_available_after_decision_cannot_leak() -> None:
    event = BASE + timedelta(hours=9)
    target = BASE + timedelta(hours=12)
    refs = [
        ref(event, 10),
        ref(event, 11, received=BASE + timedelta(hours=10, minutes=30), correction=True),
        ref(target, 12),
    ]
    first = run(BASE + timedelta(hours=10), [(event, 12.0), (target, 12.0)], identity="before")
    second = run(BASE + timedelta(hours=11), [(event, 12.0), (target, 12.0)], identity="after")
    result = evaluate([first, second], refs)
    before, after = (row(result, key, "CAUSAL_NOWCAST") for key in ("before", "after"))
    assert before["parameters"]["correction_c"] == pytest.approx(math.exp(-2 / 6))
    assert after["parameters"]["correction_c"] == pytest.approx(0.5 * math.exp(-1 / 6))
    assert before["parameters"]["reference_ids"] != after["parameters"]["reference_ids"]
    assert before["parameters"]["history_available_by"] < before["decision_time"]


def test_initial_evaluation_truth_is_preserved_after_later_correction() -> None:
    target = BASE + timedelta(hours=1)
    result = evaluate(
        [run(BASE, [(target, 10.0)], identity="one")],
        [
            ref(target, 10),
            ref(target, 11, received=target + timedelta(minutes=10), correction=True),
        ],
    )
    assert all(r["actual_metar_integer"] == 10 for r in result["records"])


def test_hour_horizon_minimum_uses_distinct_same_hour_targets() -> None:
    runs = []
    refs = []
    for d in range(13):
        decision = BASE + timedelta(days=d, hours=8)
        target = decision + timedelta(hours=2)
        runs.append(run(decision, [(target, 12.0)], identity=str(d)))
        refs.append(ref(target))
    output = row(evaluate(runs, refs), "12", "HOUR_HORIZON_MEDIAN")
    assert output["parameters"]["fit_n"] == 12
    assert not output["fallback_raw"]
    assert output["calibrated_temperature_c"] == 10


@pytest.mark.parametrize(
    "hours,bucket", [(0, "0-6"), (6, "6-24"), (24, "24-48"), (48, "24-48"), (48.1, ">48")]
)
def test_fixed_horizon_boundaries(hours: float, bucket: str) -> None:
    assert horizon_bin(hours) == bucket


def test_negative_half_boundary_interval_error_is_not_exact_match() -> None:
    target = BASE + timedelta(hours=1)
    result = evaluate([run(BASE, [(target, -1.5)], identity="negative")], [ref(target, -2)])
    output = row(result, "negative", "RAW")
    assert output["interval_residual_c"] == 0
    assert output["predicted_metar_integer"] == -1
    assert not output["exact_integer_match"]


def test_future_nominal_point_does_not_evaluate_against_already_received_report() -> None:
    target = BASE + timedelta(hours=1)
    decision = target + timedelta(minutes=5)
    result = evaluate(
        [run(decision, [(target + timedelta(minutes=10), 12.0)])],
        [ref(target, received=target + timedelta(minutes=3))],
    )
    assert result["records"] == []


def test_models_and_replay_classes_never_share_calibration_history() -> None:
    runs, refs = training()
    decision = BASE + timedelta(days=3)
    target = decision + timedelta(hours=1)
    runs.extend(
        [
            run(decision, [(target, 12.0)], model="other", identity="other"),
            run(decision, [(target, 12.0)], kind="APPROXIMATE_REPLAY", identity="replay"),
        ]
    )
    refs.append(ref(target))
    result = evaluate(runs, refs)
    assert row(result, "other")["parameters"]["fit_n"] == 0
    assert row(result, "replay")["parameters"]["fit_n"] == 0


def test_unknown_availability_and_archive_receipt_are_not_promoted_to_prospective() -> None:
    target = BASE + timedelta(hours=1)
    archived = run(BASE, [(target, 12.0)], kind="APPROXIMATE_REPLAY", identity="archive")
    archived["first_received"] = (BASE + timedelta(days=20)).isoformat()
    result = evaluate([archived], [ref(target)])
    assert result["records"][0]["availability_time"] is None
    assert result["records"][0]["availability_class"] == "APPROXIMATE_REPLAY"
    assert result["status"] == "CALIBRATION_PENDING"
    assert result["calibrated_tmax"] is None
    assert result["daily"]["verified_reference_days"] == 0
    assert not result["daily"]["approximate_replay_can_promote"]
    json.dumps(result, allow_nan=False)


def test_prospective_forecast_not_yet_received_is_rejected() -> None:
    target = BASE + timedelta(hours=1)
    future = run(BASE, [(target, 12.0)])
    future["first_received"] = (BASE + timedelta(minutes=1)).isoformat()
    result = evaluate([future], [ref(target)])
    assert result["records"] == []
    assert result["exclusions"]["FORECAST_NOT_YET_RECEIVED"] == 1


def test_cross_model_scores_require_identical_target_and_decision_pairs() -> None:
    first, second = BASE + timedelta(hours=1), BASE + timedelta(hours=2)
    result = evaluate(
        [
            run(BASE, [(first, 11.0), (second, 12.0)], model="a"),
            run(BASE, [(first, 10.0)], model="b"),
        ],
        [ref(first), ref(second)],
    )
    matched = next(
        r
        for r in result["matched_models"]
        if r["availability_class"] == "PROSPECTIVE_CAPTURED" and r["method"] == "RAW"
    )
    assert matched["matched_target_decision_pairs"] == 1
    assert matched["model_metrics"]["a"]["N"] == matched["model_metrics"]["b"]["N"] == 1


def test_missing_or_unverified_daily_target_never_uses_hourly_metar_maximum() -> None:
    runs, refs = training()
    report = evaluate(
        runs,
        refs,
        [
            dict(
                day="2026-10-01",
                temperature_c=10,
                rounded_integer=10,
                available_at="2026-10-02T00:00:00Z",
                status="INTEGER_METAR_MAX_PROXY",
            )
        ],
    )
    assert report["daily"]["verified_reference_days"] == 0
    assert report["daily"]["records"] == []
    assert report["calibrated_tmax"] is None
    assert not report["daily"]["hourly_metar_max_used_as_daily_truth"]


def test_complete_warsaw_dst_day_has25_separate_forecast_points() -> None:
    day = date(2026, 10, 25)
    start, end = local_day_bounds(day, "Europe/Warsaw")
    points = [(start + timedelta(hours=i), 12.0) for i in range(25)]
    report = evaluate(
        [run(start - timedelta(hours=1), points)],
        [],
        [
            dict(
                day=day.isoformat(),
                temperature_c=10,
                rounded_integer=10,
                available_at=(end + timedelta(hours=1)).isoformat(),
                status="VERIFIED_SETTLEMENT_REFERENCE_FINAL",
            )
        ],
    )
    assert len(report["daily"]["previews"]) == 1
    assert report["daily"]["verified_reference_days"] == 1
    assert report["daily"]["previews"][0]["training_days"] == 0
    assert report["calibrated_tmax"] is None


def test_approximate_daily_replay_with14training_and7oos_days_still_cannot_promote() -> None:
    runs = []
    targets = []
    for i in range(23):
        day = date(2026, 9, 1) + timedelta(days=i)
        start, end = local_day_bounds(day, "Europe/Warsaw")
        points = [(start + timedelta(hours=h), 12.0) for h in range(24)]
        runs.append(
            run(start - timedelta(hours=1), points, kind="APPROXIMATE_REPLAY", identity=str(i))
        )
        targets.append(
            dict(
                day=day.isoformat(),
                temperature_c=10,
                rounded_integer=10,
                available_at=(end + timedelta(minutes=1)).isoformat(),
                status="VERIFIED_SETTLEMENT_REFERENCE_FINAL",
            )
        )
    report = evaluate(runs, [], targets)
    assert report["daily"]["summary"][0]["out_of_sample_days"] >= 7
    assert report["daily"]["summary"][0]["paired_mae_improvement"] > 0
    assert not report["daily"]["summary"][0]["promotion_eligible"]
    assert report["daily"]["summary"][0]["improvement_interval"]["lower"] is None
    assert report["daily"]["status"] == "CALIBRATION_PENDING"


@pytest.mark.parametrize(
    "field,value",
    [
        ("temperature_c", float("nan")),
        ("temperature_c", float("inf")),
        ("temperature_c", True),
        ("valid_time", "2026-10-01T12:00:00"),
    ],
)
def test_invalid_forecast_values_and_naive_clocks_are_rejected(field: str, value: Any) -> None:
    raw = run(BASE, [(BASE + timedelta(hours=1), 12.0)])
    raw["points"][0][field] = value
    assert evaluate([raw], [])["run_count"] == 0


def test_daily_promotion_cannot_use_outcomes_received_after_forecast_decision() -> None:
    runs = []
    targets = []
    for i in range(23):
        day = date(2026, 9, 1) + timedelta(days=i)
        start, end = local_day_bounds(day, "Europe/Warsaw")
        runs.append(
            run(
                start - timedelta(hours=1),
                [(start + timedelta(hours=h), 12.0) for h in range(24)],
                identity=str(i),
            )
        )
        targets.append(
            dict(
                day=day.isoformat(),
                temperature_c=10,
                rounded_integer=10,
                available_at=(end + timedelta(minutes=1)).isoformat(),
                status="VERIFIED_SETTLEMENT_REFERENCE_FINAL",
                peak_time=(start + timedelta(hours=12)).isoformat(),
            )
        )
    report = evaluate(runs, [], targets)
    assert report["daily"]["summary"][0]["promotion_eligible"]
    assert report["daily"]["status"] == "CALIBRATION_PENDING"
    assert report["daily"]["calibrated_tmax"] is None
    assert report["daily"]["summary"][0]["forecast_tmax_timing_mae_minutes"] == 0
