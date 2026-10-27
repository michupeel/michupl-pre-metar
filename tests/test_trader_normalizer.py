"""Synthetic variants of the captured EXP0011 public v2 trade response schema.

The base values identify a historical public probe row; mutated values are test
fixtures, never prospective observations or simulated economic results.
"""

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from premetar.research.trader_normalizer import WALLET, normalize_trade, parse_page


@pytest.fixture
def trade() -> dict[str, Any]:
    return {
        "proxy_wallet": WALLET,
        "side": "BUY",
        "token_id": "95245293523260222399550614575308192351600127219887032158713399702440750469565",
        "condition_id": "0x911a04456977c617d1f0bccad136293017bbc80c14aa9cc796fe2962ff593aa8",
        "size": 9.0,
        "price": 0.98,
        "timestamp": 1793087526,
        "transaction_hash": "0x0a5049fe093a64ea3ce21d2fffab15aa586d7b0dad3d3eae0f6e8905783ad03e",
        "title": "Will the highest temperature in Tel Aviv be 26°C on October 27?",
        "outcome": "No",
    }


def received(trade: dict[str, Any], seconds: float = 3) -> datetime:
    return datetime.fromtimestamp(trade["timestamp"], UTC) + timedelta(seconds=seconds)


def test_trade_keeps_independent_source_and_receipt_clocks(trade: dict[str, Any]) -> None:
    result = normalize_trade(trade, received(trade), "LIVE_CAPTURED")
    assert result["trade_detection_latency"] == 3
    assert result["source_timestamp_precision_seconds"] == 1
    assert result["source_trade_timestamp"] != result["first_collector_receipt_utc"]
    assert result["source_publication_timestamp_if_available"] is None
    assert result["order_creation_time"] is None
    assert result["order_role"] == "UNKNOWN"


def test_dedup_identity_ignores_receipt_and_numeric_spelling(trade: dict[str, Any]) -> None:
    original = normalize_trade(trade, received(trade), "LIVE_CAPTURED")
    variant = dict(trade, price="0.9800", size="9.000", proxy_wallet=WALLET.upper())
    duplicate = normalize_trade(variant, received(trade, 60), "HISTORICAL")
    assert original["trade_id"] == duplicate["trade_id"]
    assert original["first_collector_receipt_utc"] != duplicate["first_collector_receipt_utc"]


@pytest.mark.parametrize("field,value", [("size", 10), ("price", 0.97), ("side", "SELL")])
def test_distinct_economic_rows_not_conflated(
    trade: dict[str, Any], field: str, value: object
) -> None:
    before = normalize_trade(trade, received(trade), "LIVE_CAPTURED")
    after = normalize_trade(dict(trade, **{field: value}), received(trade), "LIVE_CAPTURED")
    assert before["trade_id"] != after["trade_id"]


@pytest.mark.parametrize("wallet", [None, "", "0x" + "1" * 40])
def test_missing_or_wrong_wallet_rejected(trade: dict[str, Any], wallet: object) -> None:
    trade["proxy_wallet"] = wallet
    with pytest.raises(ValueError, match="WRONG_OR_MISSING_WALLET"):
        normalize_trade(trade, received(trade), "LIVE_CAPTURED")


@pytest.mark.parametrize("side", [None, "IN", "buy", ""])
def test_non_trade_side_rejected(trade: dict[str, Any], side: object) -> None:
    trade["side"] = side
    with pytest.raises(ValueError, match="INVALID_SIDE"):
        normalize_trade(trade, received(trade), "LIVE_CAPTURED")


@pytest.mark.parametrize(
    "field,value",
    [
        ("price", "NaN"),
        ("price", "Infinity"),
        ("price", 0),
        ("price", 1),
        ("price", -0.1),
        ("size", 0),
        ("size", -2),
        ("size", "NaN"),
    ],
)
def test_nonfinite_or_invalid_economics_rejected(
    trade: dict[str, Any], field: str, value: object
) -> None:
    trade[field] = value
    with pytest.raises(ValueError, match="INVALID_PRICE_OR_SIZE"):
        normalize_trade(trade, received(trade), "LIVE_CAPTURED")


@pytest.mark.parametrize("stamp", [None, True, False, "1793087526", 1793087526.0, 0, -1])
def test_source_time_must_be_real_integer_epoch(trade: dict[str, Any], stamp: object) -> None:
    receipt = received(trade)
    trade["timestamp"] = stamp
    with pytest.raises(ValueError, match="INVALID_SOURCE_TIME"):
        normalize_trade(trade, receipt, "LIVE_CAPTURED")


@pytest.mark.parametrize("field", ["price", "size", "timestamp"])
def test_missing_required_values_not_filled_from_now(trade: dict[str, Any], field: str) -> None:
    receipt = received(trade)
    del trade[field]
    with pytest.raises(ValueError, match="MALFORMED_TRADE"):
        normalize_trade(trade, receipt, "LIVE_CAPTURED")


def test_future_source_clock_changes_eligibility_evidence(trade: dict[str, Any]) -> None:
    result = normalize_trade(trade, received(trade, -5), "LIVE_CAPTURED")
    assert result["evidence_class"] == "SOURCE_CLOCK_ANOMALY"
    assert result["trade_detection_latency"] == -5
    assert result["order_role"] == "UNKNOWN"


def test_naive_receipt_rejected(trade: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="NAIVE_RECEIPT"):
        normalize_trade(trade, received(trade).replace(tzinfo=None), "LIVE_CAPTURED")


def test_aware_receipt_normalized_to_utc(trade: dict[str, Any]) -> None:
    receipt = received(trade).astimezone(timezone(timedelta(hours=2)))
    result = normalize_trade(trade, receipt, "LIVE_CAPTURED")
    assert result["first_collector_receipt_utc"] == received(trade).isoformat()


def test_v2_cursor_is_opaque_and_offset_in_response_is_not_a_request(trade: dict[str, Any]) -> None:
    payload = {
        "data": [trade],
        "pagination": {
            "limit": 1,
            "offset": 0,
            "has_more": True,
            "next_cursor": "opaque-next",
        },
    }
    rows, cursor = parse_page(payload)
    assert rows == [trade]
    assert cursor == "opaque-next"


def test_empty_final_page_is_successful_no_activity() -> None:
    assert parse_page({"data": [], "pagination": {"has_more": False, "next_cursor": None}}) == (
        [],
        None,
    )


@pytest.mark.parametrize(
    "payload,reason",
    [
        ([], "INVALID_V2_ENVELOPE"),
        ({"data": None}, "INVALID_V2_ENVELOPE"),
        ({"data": [None], "pagination": {}}, "INVALID_TRADE_ROW"),
        ({"data": []}, "MISSING_PAGINATION"),
        ({"data": [], "pagination": {"has_more": True, "next_cursor": ""}}, "INVALID_CURSOR"),
        ({"data": [], "pagination": {"has_more": True, "next_cursor": 1}}, "INVALID_CURSOR"),
        (
            {"data": [], "pagination": {"has_more": True, "next_cursor": None}},
            "INCONSISTENT_PAGINATION",
        ),
        (
            {"data": [], "pagination": {"has_more": False, "next_cursor": "next"}},
            "INCONSISTENT_PAGINATION",
        ),
    ],
)
def test_bad_v2_pages_never_silently_look_like_empty_history(payload: object, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        parse_page(payload)
