"""Synthetic fixtures for fail-closed EXP0016 decision and horizon behavior."""

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from premetar.research.d1_strategy import (
    default_config,
    exit_policy,
    horizon_bucket,
    local_day_bounds,
    outcome_wins,
    parse_outcome,
)
from premetar.research.d1_strategy import (
    evaluate_candidate as pure_evaluate_candidate,
)

AT = datetime(2026, 10, 29, 17, tzinfo=UTC)


def evaluate_candidate(market, books, probability, at, **kwargs):
    config = default_config()
    config["calibration_promotion_id"] = "SYNTHETIC_TEST_PROMOTION"
    return pure_evaluate_candidate(market, books, probability, at, config=config, **kwargs)


def inputs():
    market = {
        "received_at": AT.isoformat(),
        "identity": {
            "airport": "EPWA",
            "condition_id": "c",
            "day": "2026-10-30",
            "outcome_label": "9°C",
            "yes": "y",
            "no": "n",
        },
        "metadata": {
            "active": True,
            "closed": False,
            "acceptingOrders": True,
            "feeSchedule": {"rate": 0},
            "feeType": "zero_fees",
            "orderPriceMinTickSize": ".01",
            "orderMinSize": "5",
        },
        "rules": {
            "verified": True,
            "reference_station": "EPWA",
            "timezone": "Europe/Warsaw",
            "settlement_source": "SYNTHETIC_OFFICIAL",
            "daily_maximum_definition": "SYNTHETIC_OFFICIAL_FINAL",
            "rounding": "SYNTHETIC_VERIFIED",
        },
    }
    books = {
        side: {
            "status": "VALID",
            "token_id": token,
            "market": "c",
            "connection_id": "epoch",
            "received_at": AT.isoformat(),
            "bids": [{"price": ".4", "size": "100"}],
            "asks": [{"price": ".5", "size": "100"}],
        }
        for side, token in [("YES", "y"), ("NO", "n")]
    }
    prob = {
        "status": "CALIBRATED",
        "promotion_id": "SYNTHETIC_TEST_PROMOTION",
        "audit": {
            "verified_settlement_targets": True,
            "original_horizon_forecasts": True,
            "chronological_out_of_sample_validation": True,
            "artifact_sha256": "a" * 64,
            "forecast_record_ids": ["synthetic_f"],
            "settlement_record_ids": ["synthetic_s"],
            "validation_record_ids": ["synthetic_v"],
            "verified_at": AT.isoformat(),
        },
        "yes_probability": 0.2,
        "sample_size": 40,
        "validated_out_of_sample": True,
        "condition_id": "c",
        "available_at": AT.isoformat(),
        "training_last_settlement_date": "2026-10-28",
        "training_last_outcome_received_at": "2026-10-29T10:00:00Z",
        "horizon_bucket": "D1_EVENING",
    }
    return market, books, prob


def test_warsaw_dst_boundaries_are_calendar_days():
    start, end = local_day_bounds(date(2026, 10, 25))
    assert start.isoformat() == "2026-10-24T22:00:00+00:00"
    assert end.isoformat() == "2026-10-25T23:00:00+00:00"
    assert end - start == timedelta(hours=25)
    start, end = local_day_bounds(date(2026, 3, 29))
    assert end - start == timedelta(hours=23)


@pytest.mark.parametrize(
    "label,kind",
    [
        ("9°C", "EXACT"),
        ("9°C or below", "AT_MOST"),
        ("9°C or higher", "AT_LEAST"),
        ("−2 C", "EXACT"),
    ],
)
def test_explicit_outcomes(label, kind):
    assert parse_outcome(label)["kind"] == kind


def test_unknown_outcome_not_exact():
    assert parse_outcome("below 9") is None
    assert outcome_wins({"kind": "EXACT", "temperature_c": 9}, 9)
    assert not outcome_wins({"kind": "EXACT", "temperature_c": 9}, 8)
    assert outcome_wins({"kind": "AT_MOST", "temperature_c": 9}, 8)
    with pytest.raises(ValueError):
        outcome_wins({"kind": "UNKNOWN", "temperature_c": 9}, 9)


def test_missing_probability_keeps_both_quotes_without_entry():
    m, b, _ = inputs()
    result = evaluate_candidate(m, b, {}, AT)
    assert result["status"] == "RESEARCH_CANDIDATE"
    assert result["reasons"] == ["PROBABILITY_UNVALIDATED"]
    assert result["sides"]["NO"]["estimated_probability"] is None
    assert result["sides"]["NO"]["expected_return_usd"] is None
    assert result["sides"]["NO"]["quote"]["average_buy_price"] == "0.5"
    assert not result["is_order"]


def test_valid_calibrated_signal_is_not_fill():
    m, b, p = inputs()
    original = deepcopy((m, b, p))
    r = evaluate_candidate(m, b, p, AT)
    assert r["status"] == "ENTRY_SIGNAL"
    assert r["sides"]["NO"]["status"] == "ENTRY_SIGNAL"
    assert r["sides"]["NO"]["expected_return_usd"] == "3.0000000"
    assert r["sides"]["YES"]["status"] == "BLOCKED"
    assert r["sides"]["NO"]["quote"]["is_fill"] is False
    assert (m, b, p) == original


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("validated_out_of_sample", False, "PROBABILITY_UNVALIDATED"),
        ("sample_size", 29, "PROBABILITY_UNVALIDATED"),
        ("condition_id", "other", "PROBABILITY_OUTCOME_IDENTITY_MISMATCH"),
        ("available_at", "2026-10-29T17:00:01Z", "PROBABILITY_UNAVAILABLE_OR_STALE"),
        ("training_last_settlement_date", "2026-10-30", "CALIBRATION_LOOKAHEAD"),
        ("training_last_outcome_received_at", "2026-10-29T18:00:00Z", "CALIBRATION_LOOKAHEAD"),
        ("horizon_bucket", "D1_MORNING", "CALIBRATION_HORIZON_MISMATCH"),
    ],
)
def test_probability_guards(field, value, reason):
    m, b, p = inputs()
    p[field] = value
    r = evaluate_candidate(m, b, p, AT)
    assert reason in r["reasons"]
    assert all(x["expected_return_usd"] is None for x in r["sides"].values())


def test_bid_is_not_purchase_cost():
    m, b, p = inputs()
    b["NO"]["bids"] = [{"price": ".50", "size": "100"}]
    b["NO"]["asks"] = [{"price": ".99", "size": "100"}]
    r = evaluate_candidate(m, b, p, AT)
    assert r["sides"]["NO"]["quote"]["average_buy_price"] == "0.99"
    assert r["sides"]["NO"]["status"] == "BLOCKED"


@pytest.mark.parametrize(
    "change,reason",
    [
        ("stale", "NO_FRESH_DIRECT_BOOK"),
        ("future", "NO_FRESH_DIRECT_BOOK"),
        ("token", "NO_FRESH_DIRECT_BOOK"),
        ("depth", "INSUFFICIENT_EXECUTABLE_DEPTH"),
        ("tick", "INSUFFICIENT_EXECUTABLE_DEPTH"),
    ],
)
def test_books_fail_closed(change, reason):
    m, b, p = inputs()
    if change == "stale":
        b["NO"]["received_at"] = (AT - timedelta(seconds=6)).isoformat()
    if change == "future":
        b["NO"]["received_at"] = (AT + timedelta(seconds=1)).isoformat()
    if change == "token":
        b["NO"]["token_id"] = "wrong"
    if change == "depth":
        b["NO"]["asks"] = [{"price": ".5", "size": "1"}]
    if change == "tick":
        b["NO"]["asks"] = [{"price": ".505", "size": "100"}]
    r = evaluate_candidate(m, b, p, AT)
    assert reason in r["sides"]["NO"]["reasons"]
    assert r["sides"]["NO"]["status"] == "BLOCKED"


def test_unknown_fees_rules_and_dates_block():
    m, b, p = inputs()
    m["rules"]["verified"] = False
    m["metadata"].pop("feeSchedule")
    m["identity"]["day"] = "2026-10-29"
    r = evaluate_candidate(m, b, p, AT)
    assert "SETTLEMENT_RULES_UNVERIFIED" in r["reasons"]
    assert "UNKNOWN_OR_UNSUPPORTED_FEES" in r["reasons"]
    assert "OUTSIDE_D_MINUS_1_ENTRY_DAY" in r["reasons"]
    assert all(x["status"] == "BLOCKED" for x in r["sides"].values())


@pytest.mark.parametrize(
    "portfolio,reason",
    [
        ({"cash": "4"}, "INSUFFICIENT_CASH"),
        ({"open_or_pending_positions": 3}, "MAX_OPEN_POSITIONS"),
        ({"day_committed_usd": "21"}, "MAX_DAY_EXPOSURE"),
    ],
)
def test_common_risk_limits(portfolio, reason):
    m, b, p = inputs()
    assert reason in evaluate_candidate(m, b, p, AT, portfolio=portfolio)["reasons"]


def test_horizons_use_warsaw_not_utc():
    assert horizon_bucket(AT, date(2026, 10, 30)) == "D1_EVENING"
    assert (
        horizon_bucket(datetime(2026, 10, 29, 23, 10, tzinfo=UTC), date(2026, 10, 30))
        == "D0_MORNING"
    )
    with pytest.raises(ValueError):
        horizon_bucket(datetime(2026, 10, 29), date(2026, 10, 30))


def test_exit_trigger_never_asserts_fill():
    day = date(2026, 10, 30)
    assert exit_policy("D1_FORECAST_VALUE_V1", day, AT)["action"] == "WAIT_D0_NOON"
    at = datetime(2026, 10, 30, 11, tzinfo=UTC)
    assert exit_policy("D1_FORECAST_VALUE_V1", day, at)["action"] == "ATTEMPT_DIRECT_BID_EXIT"
    assert (
        exit_policy("D1_TO_D0_REPRICING_V1", day, at, net_return_fraction=Decimal(".05"))["action"]
        == "ATTEMPT_DIRECT_BID_EXIT"
    )
    assert (
        exit_policy("D1_HOLD_TO_SETTLEMENT_V1", day, at)["action"]
        == "HOLD_UNTIL_VERIFIED_OFFICIAL_RESOLUTION"
    )
    assert not exit_policy("D1_FORECAST_VALUE_V1", day, at)["is_fill"]
    assert (
        exit_policy("D1_FORECAST_VALUE_V1", day, AT, signal_valid=False)["action"]
        == "CANCEL_UNFILLED_ENTRY_WITH_LATENCY"
    )


def test_live_default_cannot_be_promoted_by_caller_status():
    m, b, p = inputs()
    result = pure_evaluate_candidate(m, b, p, AT)
    assert "PROBABILITY_UNVALIDATED" in result["reasons"]
    assert result["status"] != "ENTRY_SIGNAL"


def test_audit_record_references_mandatory():
    m, b, p = inputs()
    p["audit"]["settlement_record_ids"] = []
    assert "CALIBRATION_AUDIT_MISSING" in evaluate_candidate(m, b, p, AT)["reasons"]


def test_not_yet_complete_current_local_day_cannot_train_d1_final_target():
    m, b, p = inputs()
    p["training_last_settlement_date"] = "2026-10-29"
    assert "CALIBRATION_LOOKAHEAD" in evaluate_candidate(m, b, p, AT)["reasons"]
