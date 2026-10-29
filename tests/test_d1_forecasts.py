"""Synthetic schema fixtures, not observed forecasts or financial outcomes."""

import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from premetar.research.d1_forecasts import (
    MODEL_SPECS,
    consensus,
    empirical_probability,
    horizon_bucket,
    normalize_model,
)

ZONE = ZoneInfo("Europe/Warsaw")


def fixture(day="2026-10-25", model="icon_global"):
    start = datetime.combine(date.fromisoformat(day), time(0), ZONE).astimezone(UTC)
    end = datetime.combine(date.fromisoformat(day) + timedelta(days=1), time(0), ZONE).astimezone(
        UTC
    )
    hours = int((end - start).total_seconds() / 3600)
    return {
        "timezone": ZONE.key,
        "hourly_units": {"time": "unixtime", f"temperature_2m_{model}": "°C"},
        "daily_units": {"time": "unixtime", f"temperature_2m_max_{model}": "°C"},
        "hourly": {
            "time": [int((start + timedelta(hours=n)).timestamp()) for n in range(hours)],
            f"temperature_2m_{model}": [10.0] * hours,
        },
        "daily": {"time": [int(start.timestamp())], f"temperature_2m_max_{model}": [10.4]},
    }


def test_dst_fallback_keeps_both_repeated_hours_and_separate_maxima():
    f = normalize_model(fixture(), "icon_global", datetime(2026, 10, 24, 17, tzinfo=UTC))
    d = f["days"][0]
    assert d["complete"] and d["expected_hours"] == d["available_hours"] == 25
    assert d["daily_tmax_c"] == 10.4 and d["hourly_point_max_c"] == 10.0
    assert f["initialization_time"] is f["publication_time"] is None
    assert len({p["valid_time"] for p in f["points"]}) == 25


@pytest.mark.parametrize("day,hours", [("2026-03-29", 23), ("2026-10-26", 24)])
def test_daily_calendar_hours(day, hours):
    result = normalize_model(fixture(day), "icon_global", datetime(2026, 3, 28, tzinfo=UTC))
    assert result["days"][0]["expected_hours"] == hours


def test_missing_daily_value_never_filled_from_hourly_maximum():
    payload = fixture()
    payload["daily"]["temperature_2m_max_icon_global"] = [None]
    result = normalize_model(payload, "icon_global", datetime.now(UTC))
    assert result["days"][0]["daily_tmax_c"] is None
    assert result["days"][0]["hourly_point_max_c"] == 10


@pytest.mark.parametrize("change", ["naive", "unit", "duplicate", "timezone", "nan"])
def test_invalid_schema_rejected(change):
    payload = fixture()
    received = datetime.now(UTC)
    if change == "naive":
        received = datetime(2026, 10, 24)
    elif change == "unit":
        payload["hourly_units"]["temperature_2m_icon_global"] = "°F"
    elif change == "duplicate":
        payload["hourly"]["time"][1] = payload["hourly"]["time"][0]
    elif change == "timezone":
        payload["timezone"] = "UTC"
    else:
        payload["hourly"]["temperature_2m_icon_global"][0] = float("nan")
    with pytest.raises(ValueError):
        normalize_model(payload, "icon_global", received)


def test_consensus_causal_and_family_grouped():
    at = datetime(2026, 10, 24, 17, tzinfo=UTC)
    models = [normalize_model(fixture(model=m), m, at) for m in MODEL_SPECS]
    future = normalize_model(fixture(), "icon_global", at + timedelta(seconds=1))
    future["days"][0]["daily_tmax_c"] = 60
    result = consensus([*models, future], "2026-10-25", at)
    assert len(result["models"]) == 5
    assert result["family_count"] == 3
    assert result["range_max_c"] == 10.4
    assert result["probability"] is None


def test_revision_uses_previous_capture_only_not_future_and_not_claimed_run():
    at = datetime(2026, 10, 24, 17, tzinfo=UTC)
    old = normalize_model(fixture(), "icon_global", at - timedelta(hours=1))
    new = normalize_model(fixture(), "icon_global", at)
    new["days"][0]["daily_tmax_c"] = 10.8
    later = normalize_model(fixture(), "icon_global", at + timedelta(seconds=1))
    result = consensus([later, old, new], "2026-10-25", at)["models"][0]
    assert result["revision_daily_tmax_c"] == pytest.approx(0.4)
    assert result["previous_first_received"] == old["first_received"]
    assert result["age_seconds"] == 0
    assert "NOT_VERIFIED_MODEL_RUN" in result["revision_semantics"]


@pytest.mark.parametrize(
    "hour,expected", [(8, "D1_MORNING"), (12, "D1_AFTERNOON"), (18, "D1_EVENING")]
)
def test_local_horizon_windows(hour, expected):
    at = datetime(2026, 10, 24, hour, tzinfo=ZONE)
    assert horizon_bucket(at, "2026-10-25") == expected


def training():
    records = []
    for n in range(40):
        day = date(2026, 8, 1) + timedelta(days=n)
        receipt = datetime.combine(day - timedelta(days=1), time(18), ZONE).astimezone(UTC)
        records.append(
            {
                "model": "icon_global",
                "settlement_date": str(day),
                "forecast_first_received": receipt.isoformat(),
                "settlement_received": datetime.combine(
                    day + timedelta(days=1), time(12), UTC
                ).isoformat(),
                "official_settlement_verified": True,
                "reference_id": "SYNTHETIC_EPWA_REFERENCE",
                "target_semantics": "DAILY_API_MAX",
                "run_provenance": "PROSPECTIVE_CAPTURE",
                "availability_provenance": "FIRST_COLLECTOR_RECEIPT",
                "forecast_tmax_c": 10.4,
                "settlement_tmax_c": 11,
            }
        )
    forecast = {
        "model": "icon_global",
        "settlement_date": "2026-10-25",
        "first_received": "2026-10-24T16:00:00Z",
        "daily_tmax_c": 10.4,
        "reference_id": "SYNTHETIC_EPWA_REFERENCE",
    }
    outcome = {"kind": "EXACT", "value_c": 11, "rounding": "NEAREST_TIES_WARMER"}
    at = datetime(2026, 10, 24, 17, tzinfo=UTC)
    validation_dates = [str(date(2026, 9, 11) + timedelta(days=n)) for n in range(20)]
    validation = {
        "passed": True,
        "method": "CHRONOLOGICAL_WALK_FORWARD",
        "model": "icon_global",
        "horizon": "D1_EVENING",
        "reference_id": "SYNTHETIC_EPWA_REFERENCE",
        "independent_evaluation_days": 20,
        "available_at": "2026-10-02T00:00:00Z",
        "evaluation_end_date": "2026-09-30",
        "training_dates": [r["settlement_date"] for r in records],
        "training_end_date": "2026-09-09",
        "validation_dates": validation_dates,
        "audit_id": "SYNTHETIC_ONLY_AUDIT",
        "last_outcome_received": "2026-10-01T12:00:00+00:00",
        "evaluation_evidence": {
            day: {
                "forecast_first_received": datetime.combine(
                    date.fromisoformat(day) - timedelta(days=1), time(18), ZONE
                )
                .astimezone(UTC)
                .isoformat(),
                "settlement_first_received": datetime.combine(
                    date.fromisoformat(day) + timedelta(days=1), time(12), UTC
                ).isoformat(),
                "official_settlement_verified": True,
                "reference_id": "SYNTHETIC_EPWA_REFERENCE",
                "fold_training_end_date": "2026-09-09",
                "forecast_hash": hashlib.sha256(f"SYNTHETIC_FORECAST:{day}".encode()).hexdigest(),
                "settlement_hash": hashlib.sha256(
                    f"SYNTHETIC_SETTLEMENT:{day}".encode()
                ).hexdigest(),
            }
            for day in validation_dates
        },
    }
    freeze(validation)
    return records, forecast, outcome, at, validation


def freeze(validation):
    validation["artifact_hash"] = hashlib.sha256(
        json.dumps(
            {k: v for k, v in validation.items() if k != "artifact_hash"},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def test_calibration_requires_history_and_separate_validation():
    rows, f, o, at, v = training()
    assert (
        empirical_probability(rows[:29], f, o, at, validation=v)["status"] == "INSUFFICIENT_HISTORY"
    )
    pending = empirical_probability(rows, f, o, at)
    assert pending["status"] == "VALIDATION_PENDING" and pending["yes_probability"] is None
    accepted = empirical_probability(rows, f, o, at, validation=v)
    assert accepted["sample_days"] == 40 and accepted["yes_probability"] == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("official_settlement_verified", False),
        ("availability_provenance", "RECONSTRUCTED"),
        ("run_provenance", "STITCHED_HISTORICAL"),
        ("reference_id", "OTHER"),
        ("target_semantics", "MAX_ROUTINE_METAR"),
        ("settlement_received", "2026-10-26T00:00:00Z"),
    ],
)
def test_unverified_or_future_history_does_not_train(field, value):
    rows, f, o, at, v = training()
    for row in rows:
        row[field] = value
    result = empirical_probability(rows, f, o, at, validation=v)
    assert result["sample_days"] == 0 and result["yes_probability"] is None


def test_revisions_count_once_per_day_and_target_day_excluded():
    rows, f, o, at, v = training()
    duplicated = rows * 5
    duplicated.append({**rows[0], "settlement_date": "2026-10-25"})
    result = empirical_probability(duplicated, f, o, at, validation=v)
    assert result["sample_days"] == 40


def test_unknown_market_rounding_blocks_probability():
    rows, f, o, at, v = training()
    o["rounding"] = "UNKNOWN"
    result = empirical_probability(rows, f, o, at, validation=v)
    assert result["status"] == "UNVERIFIED_OUTCOME_SEMANTICS"


@pytest.mark.parametrize(
    "failure",
    [
        "overlap",
        "no_dates",
        "duplicate_dates",
        "missing_hash",
        "tampered",
        "future_outcome",
        "future_training",
        "short_validation",
        "wrong_training_end",
        "wrong_last_receipt",
    ],
)
def test_validation_requires_disjoint_chronological_hashed_evidence(failure):
    rows, f, o, at, v = training()
    first = v["validation_dates"][0]
    if failure == "overlap":
        v["validation_dates"][0] = rows[-1]["settlement_date"]
    elif failure == "no_dates":
        del v["validation_dates"]
    elif failure == "duplicate_dates":
        v["validation_dates"][1] = first
    elif failure == "missing_hash":
        del v["evaluation_evidence"][first]["forecast_hash"]
    elif failure == "future_outcome":
        v["evaluation_evidence"][first]["settlement_first_received"] = "2026-10-26T00:00:00Z"
    elif failure == "future_training":
        rows[-1]["settlement_received"] = "2026-10-20T00:00:00Z"
    elif failure == "short_validation":
        v["validation_dates"] = v["validation_dates"][:19]
    elif failure == "wrong_training_end":
        v["training_end_date"] = "2026-08-01"
    elif failure == "wrong_last_receipt":
        v["last_outcome_received"] = "2026-09-01T00:00:00Z"
    freeze(v)
    if failure == "tampered":
        v["audit_id"] = "CHANGED_AFTER_FREEZE"
    result = empirical_probability(rows, f, o, at, validation=v)
    assert result["status"] == "VALIDATION_PENDING" and result["yes_probability"] is None
