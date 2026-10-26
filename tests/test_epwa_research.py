"""Synthetic research invariants; fixtures are not live weather measurements."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.research.epwa_comparison import (  # noqa: E402
    STATIONS,
    agreement_matched,
    clock,
    common_target_comparisons,
    correction,
    initial_routine,
    latest,
    metrics,
    replay,
)


def test_correction_uses_only_earlier_received_outcomes() -> None:
    records = [
        dict(
            target_time="2026-10-25T11:00:00Z",
            first_received_utc="2026-10-25T11:02:00Z",
            residual=1,
        ),
        dict(
            target_time="2026-10-25T11:30:00Z",
            first_received_utc="2026-10-25T11:32:00Z",
            residual=3,
        ),
        dict(
            target_time="2026-10-25T10:00:00Z",
            first_received_utc="2026-10-25T12:00:00Z",
            residual=999,
        ),
        dict(
            target_time="2026-10-25T09:00:00Z",
            first_received_utc="2026-10-25T12:01:00Z",
            residual=999,
        ),
        dict(
            target_time="2026-10-22T09:00:00Z",
            first_received_utc="2026-10-22T09:02:00Z",
            residual=999,
        ),
        dict(
            target_time="2026-10-25T12:30:00Z",
            first_received_utc="2026-10-25T11:59:00Z",
            residual=999,
        ),
    ]
    assert correction(records, clock("2026-10-25T12:00:00Z"), minimum=2) == (2, 2)
    assert correction(records, clock("2026-10-25T12:00:00Z"), minimum=3) == (None, 2)


def test_transition_metrics_have_correct_sign_and_baseline_denominator() -> None:
    records = [
        dict(
            target_time="a",
            actual_integer=11,
            previous_integer=10,
            predicted_integer=9,
            interval_error=1.5,
        ),
        dict(
            target_time="b",
            actual_integer=10,
            previous_integer=10,
            predicted_integer=11,
            interval_error=0.5,
        ),
        dict(
            target_time="c",
            actual_integer=9,
            previous_integer=10,
            predicted_integer=9,
            interval_error=0,
        ),
    ]
    before = copy.deepcopy(records)
    result = metrics(records)
    assert result["change_direction_accuracy"] == 0.5
    assert result["false_alarm_count"] == 1
    assert result["persistence_exact_accuracy"] == pytest.approx(1 / 3)
    assert result["integer_bias"] == pytest.approx(-1 / 3)
    assert records == before
    assert metrics([])["exact_accuracy"] is None


def reading(event: str, received: str, value: float = 13) -> dict:
    return dict(
        id=event,
        provider="opensensemap",
        station_id="opensensemap:" + STATIONS[0],
        sensor_id="sensor",
        observation_time=event,
        first_receive_time=received,
        timestamp_provenance="SENSOR_MEASUREMENT_TIME",
        timestamp_semantics_verified=True,
        temperature_c=value,
        raw_unit="°C",
        evidence_class="REALTIME_CAPTURED",
        quality_flags=[],
        startup_censored=False,
    )


def report(event: str, received: str, value: int) -> dict:
    return dict(
        observation_time_utc=event,
        first_received_utc=received,
        temperature_c=value,
        report_type="METAR",
        correction=False,
        startup_censored=False,
        coverage_gap=False,
    )


def dataset() -> dict:
    sid = "opensensemap:" + STATIONS[0]
    return dict(
        observations=[
            reading("2026-10-25T00:01:00Z", "2026-10-25T00:01:30Z", 12.5),
            reading("2026-10-25T00:28:00Z", "2026-10-25T00:28:30Z", 13.2),
        ],
        metars=[
            report("2026-10-25T00:00:00Z", "2026-10-25T00:02:00Z", 10),
            report("2026-10-25T00:30:00Z", "2026-10-25T00:32:00Z", 11),
        ],
        selections={sid: [dict(id=1, created_at="2026-10-24T23:00:00Z", selected=1)]},
    )


def test_delayed_future_stale_and_startup_measurements_cannot_enter_replay() -> None:
    history = [reading("2026-10-25T00:28:00Z", "2026-10-25T00:30:00Z")]
    assert latest(history, clock("2026-10-25T00:29:00Z")) is None
    assert (
        latest(
            [reading("2026-10-25T00:30:00Z", "2026-10-25T00:28:00Z")], clock("2026-10-25T00:29:00Z")
        )
        is None
    )
    assert (
        latest(
            [reading("2026-10-25T00:20:00Z", "2026-10-25T00:20:10Z")], clock("2026-10-25T00:29:00Z")
        )
        is None
    )
    assert (
        latest(
            [{**reading("2026-10-25T00:28:00Z", "2026-10-25T00:28:10Z"), "startup_censored": True}],
            clock("2026-10-25T00:29:00Z"),
        )
        is None
    )


def test_replay_preserves_phase_selection_and_same_instrument_trend() -> None:
    data = dataset()
    before = copy.deepcopy(data)
    result, _ = replay(data, "PRE_OBSERVATION")
    trend = next(r for r in result if r["method"] == "pws_change")
    assert trend["predicted_integer"] == 11
    assert trend["pws_delta_c"] == pytest.approx(0.7)
    assert "NOT_LIVE" in trend["evidence"]
    assert data == before
    post, _ = replay(data, "POST_OBSERVATION_PRE_RECEIPT")
    assert all(r["decision_time"] == "2026-10-25T00:31:00+00:00" for r in post)
    sid = next(iter(data["selections"]))
    data["selections"][sid][0]["created_at"] = "2026-10-25T00:29:01Z"
    result, _ = replay(data, "PRE_OBSERVATION")
    assert not any(r["method"].startswith("pws_") for r in result)


def test_already_received_target_is_closed_even_before_nominal_time() -> None:
    data = dataset()
    data["metars"][1]["first_received_utc"] = "2026-10-25T00:28:00Z"
    assert replay(data, "PRE_OBSERVATION")[0] == []
    assert replay(data, "POST_OBSERVATION_PRE_RECEIPT")[0] == []


def test_correction_receipt_does_not_reveal_later_initial_outcome() -> None:
    data = dataset()
    early_cor = {
        **data["metars"][1],
        "correction": True,
        "first_received_utc": "2026-10-25T00:31:00Z",
    }
    data["metars"].append(early_cor)
    # No future initial outcome may become available merely through an earlier COR.
    assert correction(
        [
            dict(
                target_time="2026-10-25T00:30:00Z",
                first_received_utc=data["metars"][1]["first_received_utc"],
                residual=2,
            )
        ],
        clock("2026-10-25T00:31:30Z"),
        1,
    ) == (None, 0)


def test_replay_training_waits_for_selected_outcome_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.research.epwa_comparison as module

    data = dataset()
    data["metars"][1]["first_received_utc"] = "2026-10-25T01:01:00Z"
    data["metars"].append(
        {**data["metars"][1], "correction": True, "first_received_utc": "2026-10-25T00:32:00Z"}
    )
    data["metars"].append(report("2026-10-25T01:00:00Z", "2026-10-25T01:02:00Z", 12))
    data["observations"].append(reading("2026-10-25T00:58:00Z", "2026-10-25T00:58:30Z", 14))
    counts = {}
    original = module.correction

    def audited(history: list[dict], at: object, minimum: int = 12) -> tuple:
        result = original(history, at, minimum=1)
        counts[at.isoformat()] = result[1]
        return result

    monkeypatch.setattr(module, "correction", audited)
    replay(data, "PRE_OBSERVATION")
    assert counts["2026-10-25T00:59:00+00:00"] == 0


def test_matched_station_comparison_never_uses_different_target_sets() -> None:
    records = []
    for i, sid in enumerate(STATIONS):
        for t in ["a", "b"] if i == 0 else ["b", "c"]:
            records.append(
                dict(
                    phase="PRE_OBSERVATION",
                    station_id="opensensemap:" + sid,
                    method="pws_raw",
                    target_time=t,
                    actual_integer=10,
                    previous_integer=10,
                    predicted_integer=10,
                    interval_error=0,
                )
            )
    result = common_target_comparisons(records)["across_stations"]["PRE_OBSERVATION|pws_raw"]
    assert result["targets"] == ["b"]
    assert all(m["n"] == 1 for m in result["stations"].values())
    assert result["ranking_status"] == "INSUFFICIENT DATA"


def test_reference_variants_and_timezone_validation() -> None:
    r = report("2026-10-25T01:00:00Z", "2026-10-25T01:02:00Z", 10)
    initial, ambiguous = initial_routine([r, {**r, "correction": True, "temperature_c": 11}])
    assert len(initial) == 1 and ambiguous == []
    assert initial_routine([r, {**r, "temperature_c": 11}])[0] == []
    with pytest.raises(ValueError):
        clock("2026-10-25T02:30:00")
    assert clock("2026-10-25T02:30:00+02:00") != clock("2026-10-25T02:30:00+01:00")


def test_early_received_future_previous_report_cannot_be_baseline() -> None:
    data = dataset()
    data["metars"].append(report("2026-10-25T00:29:30Z", "2026-10-25T00:28:30Z", 15))
    result, _ = replay(data, "PRE_OBSERVATION")
    baseline = next(r for r in result if r["method"] == "previous_metar")
    assert baseline["predicted_integer"] == 10


def test_agreement_uses_one_nearest_measurement_on_common_cycles() -> None:
    pairs = []
    for sid in STATIONS:
        pairs.extend(
            [
                dict(
                    station_id="opensensemap:" + sid,
                    target_time="shared",
                    time_difference_seconds=200,
                    interval_residual_c=99,
                ),
                dict(
                    station_id="opensensemap:" + sid,
                    target_time="shared",
                    time_difference_seconds=-10,
                    interval_residual_c=0.5,
                ),
            ]
        )
    pairs.append(
        dict(
            station_id="opensensemap:" + STATIONS[0],
            target_time="unshared",
            time_difference_seconds=0,
            interval_residual_c=99,
        )
    )
    result = agreement_matched(pairs)
    assert result["n"] == 1
    assert all(r["mean_absolute_interval_error_c"] == 0.5 for r in result["stations"].values())
