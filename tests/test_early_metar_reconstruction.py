"""Synthetic EXP-0010 invariants; never access a live collector or weather data."""

import copy
import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.research.early_metar_data import EPS, clock  # noqa: E402
from scripts.research.early_metar_reconstruction import candidate, decision_times, search  # noqa: E402


def observation(event: str, receipt: str, temperature: float) -> dict:
    return dict(
        id=receipt,
        provider="opensensemap",
        station_id="opensensemap:SYNTHETIC",
        sensor_id="SYNTHETIC-T",
        observation_time=event,
        first_receive_time=receipt,
        _event=clock(event),
        _received=clock(receipt),
        temperature_c=temperature,
        age_seconds=(clock(receipt) - clock(event)).total_seconds(),
        raw_unit="°C",
        raw_temperature=str(temperature),
        evidence_class="REALTIME_CAPTURED",
        timestamp_provenance="SENSOR_MEASUREMENT_TIME",
        timestamp_semantics_verified=True,
        qc_status="VALID",
        quality_flags=[],
        startup_censored=False,
    )


def fixture() -> tuple[dict, list[dict]]:
    base = clock("2026-10-26T00:00:00Z")
    pairs = [
        dict(
            _event=base + timedelta(minutes=30 * i),
            _received=base + timedelta(minutes=30 * i + 2),
            offset_midpoint_c=2.0,
            report_identity=f"SYNTHETIC-{i}",
        )
        for i in range(12)
    ]
    first = observation("2026-10-26T11:59:00Z", "2026-10-26T11:59:10Z", 12.5)
    sensor = dict(
        airport="EPWA",
        airport_metadata=dict(latitude=52, longitude=20),
        provider="opensensemap",
        station_id="opensensemap:SYNTHETIC",
        sensor_id="SYNTHETIC-T",
        sensor_type="synthetic",
        distance_km=0,
        metadata=[
            dict(
                station_name="SYNTHETIC",
                latitude=52,
                longitude=20,
                exposure="outdoor",
                mobile=False,
            )
        ],
        metadata_times=[base - timedelta(days=1)],
        selections=[dict(id=1, created_at="2026-10-25T00:00:00Z", selected=0)],
        selection_times=[base - timedelta(days=1)],
        readings=[first],
        event_times=[first["_event"]],
        conflicts={},
        pairs=pairs,
        stored_count=1,
        rejections=Counter(),
    )
    previous = dict(
        _event=clock("2026-10-26T11:30:00Z"),
        _received=clock("2026-10-26T11:32:00Z"),
        _closure=clock("2026-10-26T11:32:00Z"),
        temperature_c=10,
        startup_censored=False,
        coverage_gap=False,
    )
    target = dict(
        _event=clock("2026-10-26T12:00:00Z"),
        _received=clock("2026-10-26T12:03:00Z"),
        _closure=clock("2026-10-26T12:03:00Z"),
        temperature_c=11,
        startup_censored=False,
        coverage_gap=False,
    )
    return sensor, [previous, target]


def test_calibrated_candidate_is_causal_and_unselected_sensor_is_not_filtered() -> None:
    s, refs = fixture()
    before = copy.deepcopy(s)
    status, r = candidate(s, refs[-1], refs, "CAL-1", clock("2026-10-26T11:59:10Z"))
    assert status == "VALID" and r
    assert r["calibrated_temperature_c"] == 10.5 and r["predicted_integer"] == 11
    assert r["offset_c"] == 2 and r["calibration_n"] == 12
    assert r["offset_lower_c"] == 1.5 and r["offset_upper_c"] == 2.5
    assert r["incremental_correct"] and not r["selected_at_decision"]
    assert s == before
    refs[-1]["temperature_c"] = 16
    _, other = candidate(s, refs[-1], refs, "CAL-1", clock("2026-10-26T11:59:10Z"))
    assert other and other["predicted_integer"] == r["predicted_integer"]


def test_early_any_provider_receipt_closes_candidate_before_nominal() -> None:
    s, refs = fixture()
    refs[-1]["_closure"] = clock("2026-10-26T11:58:00Z")
    assert candidate(s, refs[-1], refs, "CAL-1", clock("2026-10-26T11:59:10Z")) == (
        "TARGET_ALREADY_RECEIVED",
        None,
    )


def test_post_checkpoint_does_not_relabel_pre_observation_receipt() -> None:
    s, refs = fixture()
    status, r = candidate(s, refs[-1], refs, "CAL-1", clock("2026-10-26T12:00:30Z"), window="EXP_B")
    assert status == "NO_POST_OBSERVATION_RECEIPT" and r is None
    _, carried = candidate(s, refs[-1], refs, "CAL-1", clock("2026-10-26T12:00:30Z"))
    assert carried and carried["phase"] == "CARRIED_PREOBS_INPUT"
    s["readings"].append(observation("2026-10-26T12:00:05Z", "2026-10-26T12:00:20Z", 12.5))
    s["event_times"] = [r["_event"] for r in s["readings"]]
    _, post = candidate(s, refs[-1], refs, "CAL-1", clock("2026-10-26T12:00:30Z"), window="EXP_B")
    assert post and post["phase"] == "EXP_B"


def test_rolling_calibration_expiry_is_a_trajectory_boundary() -> None:
    s, refs = fixture()
    boundary = clock("2026-10-26T12:00:00Z") + EPS
    times, _ = decision_times(s, refs[-1], refs)
    assert boundary in times
    assert candidate(s, refs[-1], refs, "CAL-2", boundary) == (
        "INSUFFICIENT_CALIBRATION_HISTORY",
        None,
    )
    assert candidate(s, refs[-1], refs, "CAL-1", boundary)[0] == "VALID"
    refs[0]["_ambiguous_from"] = clock("2026-10-26T11:59:40Z")
    assert refs[0]["_ambiguous_from"] in decision_times(s, refs[-1], refs)[0]


def test_latest_receipt_does_not_choose_an_earlier_correct_value() -> None:
    s, refs = fixture()
    s["readings"] = [
        observation("2026-10-26T11:57:00Z", "2026-10-26T11:57:10Z", 12.5),
        observation("2026-10-26T11:59:00Z", "2026-10-26T11:59:10Z", 13.5),
    ]
    s["event_times"] = [r["_event"] for r in s["readings"]]
    result = search({"EPWA": dict(references=refs, sensors={s["sensor_id"]: s})})
    rows = [
        r
        for r in result["candidates"]
        if r["method"] == "CAL-1"
        and r["decision_label"] == "LATEST_RECEIPT"
        and r["phase"] == "EXP_A"
    ]
    assert len(rows) == 1 and rows[0]["predicted_integer"] == 12 and not rows[0]["correct"]
    trajectory = next(r for r in result["trajectories"] if r["method"] == "CAL-1")
    assert trajectory["first_correct"] == "2026-10-26T11:57:10+00:00"
    assert trajectory["first_stable_correct"] is None
    assert trajectory["correct_to_wrong_reversals"] == 1


@pytest.mark.parametrize(
    ("value", "expected"), [(-2.5, -2), (-1.5, -1), (-0.5, 0), (0.5, 1), (10.5, 11)]
)
def test_calibrated_integer_rounds_half_toward_warmer(value: float, expected: int) -> None:
    s, refs = fixture()
    s["readings"][0]["temperature_c"] = value + 2
    _, r = candidate(s, refs[-1], refs, "CAL-1", clock("2026-10-26T11:59:10Z"))
    assert r and r["predicted_integer"] == expected
