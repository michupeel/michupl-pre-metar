"""Synthetic archived-run/label joins; no historical values fabricated as observations."""

import json
import sqlite3
from copy import deepcopy
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from premetar.research.settlement_calibration import evaluate, export, load_archived_runs

ZONE = ZoneInfo("Europe/Warsaw")
DAY = date(2026, 10, 26)
AT = datetime(2026, 10, 29, 12, tzinfo=UTC)


def inputs(day=DAY):
    start = datetime.combine(day, time.min, ZONE).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, ZONE).astimezone(UTC)
    points = [
        dict(valid_time=(start + timedelta(hours=i)).isoformat(), temperature_c=11.5)
        for i in range(int((end - start).total_seconds() / 3600))
    ]
    run = dict(
        model="icon_global",
        run_id="r",
        initialization_time=f"{day - timedelta(days=1)}T00:00:00+00:00",
        first_received="2026-10-28T12:00:00Z",
        availability_class="APPROXIMATE_REPLAY",
        availability_time=None,
        decision_assumption="INIT_PLUS_6H_SCENARIO_NOT_VERIFIED_ORIGINAL_AVAILABILITY",
        points=points,
        raw_payload_hash="raw",
    )
    target = dict(
        settlement_date=day.isoformat(),
        classification="VERIFIED_SOURCE_AND_MARKET",
        raw_maximum_c=11.0,
        settlement_integer=11,
        target_available_at="2026-10-28T13:00:00Z",
        source_provenance="SYNTHETIC_VERIFIED_CUTOFF",
    )
    return run, target


def test_approximate_d1_pairs_do_not_become_prospective_or_daily_api_max():
    run, target = inputs()
    result = evaluate([run], [target], at=AT)
    assert len(result["records"]) == 2  # 06Warsaw precedes assumed06UTC release
    row = result["records"][0]
    assert row["checkpoint_local"].startswith("D-1 12")
    assert row["daily_api_tmax_c"] is None and row["hourly_point_max_c"] == 11.5
    assert row["hourly_point_error_c"] == 0.5 and row["daily_api_error_c"] is None
    assert row["hourly_point_integer_prediction"] == 12
    assert row["target_known_at_historical_decision"] is False
    assert row["original_availability_time"] is None
    assert not row["strict_calibration_pair"] and result["strict_pair_days"] == 0
    assert result["approximate_replay_model_day_pairs"] == 1


def test_complete_dst_fallback_day_keeps25_distinct_hours():
    run, target = inputs(date(2026, 10, 25))
    result = evaluate([run], [target], at=AT)
    assert result["records"][0]["expected_hourly_points"] == 25
    del run["points"][4]
    assert not evaluate([run], [target], at=AT)["records"]


def test_incomplete_or_duplicate_forecast_cannot_join():
    run, target = inputs()
    run["points"].append(run["points"][0])
    result = evaluate([run], [target], at=AT)
    assert not result["records"]
    assert result["exclusions"]["DUPLICATE_FORECAST_VALID_TIME"] == 1


def test_future_init_forecast_cannot_win_earlier_checkpoint():
    run, target = inputs()
    future = deepcopy(run)
    future.update(run_id="future", initialization_time="2026-10-25T15:00:00Z")
    for p in future["points"]:
        p["temperature_c"] = 50
    result = evaluate([run, future], [target], at=AT)
    assert all(row["run_id"] == "r" for row in result["records"])


def test_prospective_receipt_after_decision_excludes_forecast():
    run, target = inputs()
    run.update(availability_class="PROSPECTIVE_CAPTURED", first_received="2026-10-26T00:00:00Z")
    assert not evaluate([run], [target], at=AT)["records"]


def test_verified_historical_availability_requires_explicit_evidence_flag():
    run, target = inputs()
    run.update(
        availability_class="VERIFIED_HISTORICAL_AVAILABILITY",
        availability_time="2026-10-25T01:00:00Z",
    )
    assert not evaluate([run], [target], at=AT)["records"]
    run["availability_verified"] = True
    result = evaluate([run], [target], at=AT)
    assert len(result["records"]) == 3
    assert result["strict_pair_days"] == 1 and result["strict_independent_model_day_pairs"] == 1
    assert result["progress"]["probability"] is None


def test_backfilled_target_is_only_visible_after_actual_evidence_receipt():
    run, target = inputs()
    target["target_available_at"] = "2026-10-30T00:00:00Z"
    result = evaluate([run], [target], at=AT)
    assert result["target_days"] == 0 and not result["records"]
    assert result["exclusions"]["TARGET_NOT_YET_AVAILABLE_TO_ANALYSIS"] == 1


def test_conflicting_or_insufficient_target_never_trains():
    run, target = inputs()
    for classification in ["CONFLICT", "INSUFFICIENT_EVIDENCE"]:
        target["classification"] = classification
        assert not evaluate([run], [target], at=AT)["records"]


def test_conflicting_duplicate_days_cannot_inflate_verified_count():
    run, target = inputs()
    other = dict(target, settlement_integer=12, raw_maximum_c=12)
    result = evaluate([run], [target, other], at=AT)
    assert result["verified_target_days"] == 0 and not result["records"]


def test_market_only_target_has_no_continuous_error_or_strict_pair():
    run, target = inputs()
    target.update(classification="VERIFIED_MARKET_ONLY", raw_maximum_c=None)
    row = evaluate([run], [target], at=AT)["records"][0]
    assert row["hourly_point_error_c"] is None
    assert row["hourly_point_interval_error_c"] == 0
    assert row["hourly_point_integer_match"] is False  # upper boundary rounds warmer
    assert not row["strict_calibration_pair"]


def test_run_deduplication_does_not_inflate_days_or_models():
    run, target = inputs()
    result = evaluate([run, run], [target, target], at=AT)
    assert len(result["records"]) == 2 and result["target_days"] == 1
    assert result["exclusions"]["DUPLICATE_RUN_ID"] == 1


def test_latest_initialization_eligible_before_fixed_checkpoint_selected():
    run, target = inputs()
    older = deepcopy(run)
    older.update(run_id="old", initialization_time="2026-10-24T00:00:00Z")
    result = evaluate([older, run], [target], at=AT)
    assert [r["run_id"] for r in result["records"]] == ["old", "r", "r"]


def test_negative_exact_half_rounds_toward_warmer():
    run, target = inputs()
    for p in run["points"]:
        p["temperature_c"] = -1.5
    target.update(raw_maximum_c=-1.5, settlement_integer=-1)
    row = evaluate([run], [target], at=AT)["records"][0]
    assert row["hourly_point_integer_prediction"] == -1
    assert row["hourly_point_integer_match"] is True


def test_daily_api_and_hourly_point_errors_remain_separate():
    run, target = inputs()
    run["days"] = [dict(settlement_date=DAY.isoformat(), daily_tmax_c=11.8)]
    row = evaluate([run], [target], at=AT)["records"][0]
    assert row["daily_api_tmax_c"] == 11.8
    assert abs(row["daily_api_error_c"] - 0.8) < 1e-9
    assert row["hourly_point_error_c"] == 0.5


def test_loader_readonly_and_exports_reproducible(tmp_path: Path):
    run, target = inputs()
    path = tmp_path / "archive.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "create table events(id integer,kind text,received_at text,payload text,payload_hash text)"
        )
        conn.execute(
            "insert into events values(1,'ARCHIVED_RUN',?,?,?)",
            (run["first_received"], json.dumps(run), "hash"),
        )
    before = path.read_bytes()
    loaded = load_archived_runs(path)
    assert len(loaded) == 1 and path.read_bytes() == before
    result = evaluate(loaded, [target], at=AT)
    out = tmp_path / "reports"
    export(result, out)
    first = {p.name: p.read_bytes() for p in out.iterdir()}
    export(result, out)
    assert first == {p.name: p.read_bytes() for p in out.iterdir()}


def test_claimed_final_label_before_end_or_conflicting_rawvalue_is_rejected():
    run, target = inputs()
    target["target_available_at"] = "2026-10-26T10:00:00Z"
    assert not evaluate([run], [target], at=AT)["records"]
    target["target_available_at"] = "2026-10-28T13:00:00Z"
    target["settlement_integer"] = 12
    assert not evaluate([run], [target], at=AT)["records"]


def test_single_correlated_family_does_not_claim_disagreement_information():
    run, target = inputs()
    other = deepcopy(run)
    other.update(model="icon_eu", run_id="eu")
    for point in other["points"]:
        point["temperature_c"] = 15
    result = evaluate([run, other], [target], at=AT)
    assert result["model_disagreement"]["days"] == []
    assert result["model_disagreement"]["status"] == "INSUFFICIENT_MATCHED_INDEPENDENT_DAYS"
