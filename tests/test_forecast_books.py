"""Synthetic public stream shapes; never represent these as observed market data."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from premetar.research.forecast_books import BookTracker

AT = datetime(2026, 10, 28, 12, tzinfo=UTC)


def subscribe(tracker: BookTracker, tokens: list[str] | None = None, connection: str = "a") -> None:
    tracker.observe(
        "STREAMHEALTH",
        {"state": "SUBSCRIBED", "tokens": tokens or ["yes", "no"], "connection_id": connection},
        AT,
    )


def book(token: str = "no", connection: str = "a") -> dict[str, Any]:
    return {
        "token_id": token,
        "connection_id": connection,
        "market": "condition",
        "complete": True,
        "bids": [{"price": "0.40", "size": "10"}, {"price": "0.30", "size": "15"}],
        "asks": [{"price": "0.50", "size": "12"}, {"price": "0.60", "size": "18"}],
    }


def delta(changes: list[dict[str, Any]] | None = None, connection: str = "a") -> dict[str, Any]:
    return {
        "connection_id": connection,
        "market": "condition",
        "price_changes": changes
        if changes is not None
        else [{"asset_id": "no", "side": "BUY", "price": "0.40", "size": "0"}],
    }


def tracker() -> BookTracker:
    instance = BookTracker()
    subscribe(instance)
    instance.observe("BOOK", book(), AT)
    return instance


def test_full_snapshot_preserves_depth_sorted_and_decimal_midpoint() -> None:
    view = tracker().view("no", AT)
    assert view["status"] == "VALID"
    assert view["best_bid"] == "0.40"
    assert view["bid_size"] == "10"
    assert view["best_ask"] == "0.50"
    assert view["midpoint"] == "0.45"
    assert view["depth"] == {"bid_shares": "25", "ask_shares": "30"}
    assert view["bids"][0] == {"price": "0.40", "size": "10"}


def test_full_snapshot_required_and_wrong_epoch_ignored() -> None:
    instance = BookTracker()
    subscribe(instance)
    instance.observe("WS_DELTA", delta(), AT)
    assert instance.view("no", AT)["status"] != "VALID"
    instance.observe("BOOK", book(connection="old"), AT)
    assert instance.view("no", AT)["status"] != "VALID"
    instance.observe("BOOK", book(), AT)
    assert instance.view("no", AT)["status"] == "VALID"


def test_future_and_stale_no_pong_or_trade_freshness() -> None:
    instance = tracker()
    assert instance.view("no", AT - timedelta(microseconds=1))["status"] == "FUTURE_BOOK"
    assert instance.view("no", AT + timedelta(seconds=10))["status"] == "VALID"
    for kind in ("PONG", "WS_TRADE", "WS_RAW"):
        instance.observe(kind, {"connection_id": "a"}, AT + timedelta(seconds=15))
    assert instance.view("no", AT + timedelta(seconds=15))["status"] == "STALE_BOOK"


@pytest.mark.parametrize("state", ["RECONNECTING", "MALFORMED_MESSAGE"])
def test_bad_health_invalidates_until_new_full_snapshot(state: str) -> None:
    instance = tracker()
    instance.observe("STREAMHEALTH", {"connection_id": "a", "state": state}, AT)
    assert instance.view("no", AT)["status"] != "VALID"
    instance.observe("WS_DELTA", delta(), AT)
    assert instance.view("no", AT)["status"] != "VALID"
    if state == "RECONNECTING":
        instance.observe("BOOK", book(), AT)
        assert instance.view("no", AT)["status"] != "VALID"
        subscribe(instance, connection="b")
        instance.observe("BOOK", book(connection="b"), AT)
    else:
        instance.observe("BOOK", book(), AT)
    assert instance.view("no", AT)["status"] == "VALID"


def test_unsubscribe_resubscribe_does_not_resurrect_depth() -> None:
    instance = tracker()
    instance.observe(
        "STREAMHEALTH",
        {"connection_id": "a", "state": "SUBSCRIPTIONS_CHANGED", "tokens": ["yes"]},
        AT,
    )
    assert instance.view("no", AT)["status"] == "NOT_SUBSCRIBED"
    instance.observe(
        "STREAMHEALTH",
        {"connection_id": "a", "state": "SUBSCRIPTIONS_CHANGED", "tokens": ["yes", "no"]},
        AT,
    )
    assert instance.view("no", AT)["status"] != "VALID"


def test_deletion_and_repricing_with_exact_threshold() -> None:
    instance = tracker()
    signals = instance.observe("WS_DELTA", delta(), AT + timedelta(seconds=1))
    assert instance.view("no", AT + timedelta(seconds=1))["best_bid"] == "0.30"
    assert len(signals) == 1
    assert signals[0]["kind"] == "ORDERBOOK_REPRICING_DETECTED"
    assert signals[0]["threshold"] == "0.02"
    assert signals[0]["causal_attribution"] == "UNKNOWN"


def test_small_change_is_not_repricing_and_old_baseline_is_not_current() -> None:
    instance = tracker()
    change = [{"asset_id": "no", "side": "BUY", "price": "0.41", "size": "3"}]
    assert instance.observe("WS_DELTA", delta(change), AT + timedelta(seconds=1)) == []
    assert instance.observe("WS_DELTA", delta(), AT + timedelta(seconds=20)) == []


@pytest.mark.parametrize(
    "problem",
    ["crossed", "locked", "duplicate", "zero_size", "nan", "zero_price", "one_price"],
)
def test_invalid_full_depth_rejected(problem: str) -> None:
    instance = tracker()
    source = book()
    if problem == "crossed":
        source["bids"][0]["price"] = "0.51"
    elif problem == "locked":
        source["bids"][0]["price"] = "0.50"
    elif problem == "duplicate":
        source["bids"].append(dict(source["bids"][0]))
    elif problem == "zero_size":
        source["bids"][0]["size"] = "0"
    else:
        source["bids"][0]["price"] = {"nan": "NaN", "zero_price": "0", "one_price": "1"}[problem]
    instance.observe("BOOK", source, AT)
    assert instance.view("no", AT)["status"] != "VALID"


@pytest.mark.parametrize("problem", ["best_bid", "best_ask", "market", "side", "negative"])
def test_bad_delta_invalidates_without_partial_success(problem: str) -> None:
    instance = tracker()
    source = delta()
    if problem in {"best_bid", "best_ask"}:
        source["price_changes"][0][problem] = "0.99"
    elif problem == "market":
        source["market"] = "wrong"
    elif problem == "side":
        source["price_changes"][0]["side"] = "OTHER"
    else:
        source["price_changes"][0]["size"] = "-1"
    instance.observe("WS_DELTA", source, AT + timedelta(seconds=1))
    assert instance.view("no", AT + timedelta(seconds=1))["status"] != "VALID"


def test_empty_asks_keep_complementary_indication_with_exact_size() -> None:
    instance = tracker()
    no = book()
    no["asks"] = []
    instance.observe("BOOK", no, AT)
    yes = book("yes")
    yes["bids"] = [{"price": "0.02", "size": "38.35"}]
    yes["asks"] = [{"price": "0.03", "size": "5"}]
    instance.observe("BOOK", yes, AT)
    pair = instance.opportunities("yes", "no", AT, "condition")
    assert pair["status"] == "COMPLEMENTARY_INDICATIVE_NOT_FILL"
    assert pair["direct_no_asks"] == []
    assert pair["complement_yes_bids"] == [{"price": "0.98", "size": "38.35"}]
    assert not pair["guaranteed_fill"]
    assert pair["net_execution"] == "BLOCKED_UNKNOWN_FEES_AND_MATCHING_PRIORITY"
    assert instance.view("no", AT)["midpoint"] is None


def test_pair_rejects_wrong_condition_old_depth_and_same_token() -> None:
    instance = tracker()
    instance.observe("BOOK", book("yes"), AT)
    assert instance.opportunities("yes", "no", AT, "wrong")["status"] == "WRONG_CONDITION"
    assert instance.opportunities("no", "no", AT)["status"] == "INVALID_PAIR"
    assert (
        instance.opportunities("yes", "no", AT + timedelta(seconds=11))["status"]
        == "PAIR_NOT_FRESH"
    )


def test_new_connection_and_process_stop_invalidate_previous_snapshot() -> None:
    instance = tracker()
    subscribe(instance, connection="b")
    assert instance.view("no", AT)["status"] != "VALID"
    instance.observe("BOOK", book(connection="b"), AT)
    instance.observe("STOP", {}, AT)
    assert instance.view("no", AT)["status"] != "VALID"


def test_out_of_order_depth_never_rewrites_available_state() -> None:
    instance = tracker()
    instance.observe("BOOK", book(), AT + timedelta(seconds=2))
    instance.observe("WS_DELTA", delta(), AT + timedelta(seconds=1))
    assert instance.view("no", AT + timedelta(seconds=2))["status"] != "VALID"


def test_naive_clock_and_excess_age_bound_rejected() -> None:
    with pytest.raises(ValueError, match="UTC"):
        tracker().view("no", datetime(2026, 10, 28))
    with pytest.raises(ValueError):
        BookTracker(11)


@pytest.mark.parametrize("kind", ["BOOK", "WS_DELTA"])
def test_identified_invalid_depth_does_not_invalidate_independent_condition(kind: str) -> None:
    """Synthetic top-quote disagreement mirrors the failure shape, not live values."""
    instance = tracker()
    independent = book("yes")
    independent["market"] = "another-condition"
    instance.observe("BOOK", independent, AT)
    if kind == "BOOK":
        malformed = book()
        malformed["bids"].append(dict(malformed["bids"][0]))
    else:
        malformed = delta()
        malformed["price_changes"][0]["best_bid"] = "0.99"
    assert instance.observe(kind, malformed, AT + timedelta(seconds=1)) == []
    assert (
        instance.view("no", AT + timedelta(seconds=1))["status"]
        == "INVALID_DEPTH_REQUIRES_SNAPSHOT"
    )
    unrelated = instance.view("yes", AT + timedelta(seconds=1))
    assert unrelated["status"] == "VALID"
    assert unrelated["received_at"] == AT.isoformat()
    assert unrelated["market"] == "another-condition"


def test_batch_failure_invalidates_all_identified_assets_without_partial_depth() -> None:
    instance = tracker()
    instance.observe("BOOK", book("yes"), AT)
    source = delta(
        [
            {"asset_id": "no", "side": "BUY", "price": "0.40", "size": "0"},
            {"asset_id": "yes", "side": "BUY", "price": "0.40", "size": "-1"},
        ]
    )
    instance.observe("WS_DELTA", source, AT + timedelta(seconds=1))
    for token in ("yes", "no"):
        view = instance.view(token, AT + timedelta(seconds=1))
        assert view["status"] == "INVALID_DEPTH_REQUIRES_SNAPSHOT"
        assert view["bids"] == []


@pytest.mark.parametrize("missing", [None, "unknown", [], {}])
def test_ambiguous_affected_asset_invalidates_all(missing: Any) -> None:
    instance = tracker()
    instance.observe("BOOK", book("yes"), AT)
    source = delta([{"asset_id": missing, "side": "BUY", "price": "0.40", "size": "-1"}])
    instance.observe("WS_DELTA", source, AT + timedelta(seconds=1))
    assert instance.view("yes", AT + timedelta(seconds=1))["status"] != "VALID"
    assert instance.view("no", AT + timedelta(seconds=1))["status"] != "VALID"


def test_malformed_wire_message_still_invalidates_all_conditions() -> None:
    instance = tracker()
    independent = book("yes")
    independent["market"] = "another-condition"
    instance.observe("BOOK", independent, AT)
    instance.observe("STREAMHEALTH", {"connection_id": "a", "state": "MALFORMED_MESSAGE"}, AT)
    assert instance.view("yes", AT)["status"] == "MALFORMED_MESSAGE"
    assert instance.view("no", AT)["status"] == "MALFORMED_MESSAGE"
