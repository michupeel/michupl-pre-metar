from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from premetar.research.trader_execution import (
    BookSnapshot,
    FeePolicy,
    Level,
    simulate_buy,
    simulate_sell,
)

DETECTED = datetime(2026, 10, 27, tzinfo=UTC)
RECEIVED = DETECTED + timedelta(seconds=2)
BOOK = BookSnapshot(
    "token",
    RECEIVED,
    (Level(D("0.4"), D(20)),),
    (
        Level(D("0.5"), D(10)),
        Level(D("0.6"), D(20)),
    ),
)
ZERO_FEE = FeePolicy(D(0), 1, "synthetic verified zero-fee fixture", False)


def buy(book: BookSnapshot = BOOK, notional: D = D(10), **kwargs: object):  # type: ignore[no-untyped-def]
    values = dict(
        detected_at=DETECTED,
        due_at=DETECTED,
        decision_at=RECEIVED,
        market_open=True,
        fee_policy=ZERO_FEE,
    )
    values.update(kwargs)
    return simulate_buy(book, notional, **values)  # type: ignore[arg-type]


def test_depth_walk_and_total_budget() -> None:
    result = buy()
    assert result.status == "FILLED"
    assert result.gross_value == D(10)
    assert result.quantity == D(10) + D(5) / D("0.6")
    assert result.net_value == D(10)
    assert result.executed_at == RECEIVED


def test_unknown_fees_do_not_certify_net_cost() -> None:
    result = buy(fee_policy=None)
    assert result.status == "FILLED_FEE_UNKNOWN"
    assert result.gross_value == D(10)
    assert result.fee is None and result.net_value is None


def test_fee_consumes_buy_budget() -> None:
    fee = FeePolicy(D("0.1"), 1, "synthetic explicit formula", False)
    result = buy(notional=D(5), fee_policy=fee)
    assert result.quantity == D(5) / D("0.525")
    assert result.net_value == D(5)
    assert result.fee is not None and result.fee > 0


def test_explicit_price_multiplier() -> None:
    policy = FeePolicy(D("0.1"), 1, "fixture", True)
    assert policy.per_share(D("0.5")) == D("0.0125")


def test_partial_depth_not_full_fill() -> None:
    result = buy(notional=D(100))
    assert result.status == "PARTIAL"
    assert result.quantity == D(30)
    assert result.unfilled == D(83)


@pytest.mark.parametrize(
    "changes, reason",
    [
        ({"received_at": DETECTED}, "BOOK_BEFORE_EXECUTION_DEADLINE"),
        ({"received_at": RECEIVED + timedelta(seconds=1)}, "FUTURE_BOOK"),
        ({"complete": False}, "INCOMPLETE_BOOK"),
        ({"token_id": ""}, "MISSING_TOKEN_ID"),
        ({"asks": (Level(D("NaN"), D(1)),)}, "INVALID_BOOK_LEVEL"),
        ({"asks": (Level(D("0.5"), D(-1)),)}, "INVALID_BOOK_LEVEL"),
        ({"asks": (Level(D("0.5"), D(1)), Level(D("0.5"), D(1)))}, "DUPLICATE_BOOK_LEVEL"),
        ({"bids": (Level(D("0.6"), D(1)),)}, "CROSSED_BOOK"),
    ],
)
def test_invalid_books_unknown(changes: dict[str, object], reason: str) -> None:
    result = buy(replace(BOOK, **changes))  # type: ignore[arg-type]
    assert result.status == "UNKNOWN"
    assert result.reason == reason
    assert result.quantity == 0


def test_due_time_and_staleness() -> None:
    assert (
        buy(
            due_at=RECEIVED + timedelta(seconds=1), decision_at=RECEIVED + timedelta(seconds=1)
        ).reason
        == "BOOK_BEFORE_EXECUTION_DEADLINE"
    )
    assert buy(decision_at=RECEIVED + timedelta(seconds=6)).reason == "STALE_BOOK"
    assert buy(market_open=None).reason == "UNKNOWN_MARKET_STATE"
    assert buy(market_open=False).reason == "MARKET_CLOSED"
    assert buy(decision_at=RECEIVED.replace(tzinfo=None)).reason == "NAIVE_TIMESTAMP"


def test_sell_cannot_short_and_can_partially_fill() -> None:
    result = simulate_sell(
        BOOK,
        D(30),
        holdings=D(10),
        detected_at=DETECTED,
        due_at=DETECTED,
        decision_at=RECEIVED,
        fee_policy=ZERO_FEE,
        market_open=True,
    )
    assert result.status == "PARTIAL"
    assert result.quantity == D(10)
    assert result.unfilled == D(20)
    assert result.net_value == D(4)


def test_no_liquidity() -> None:
    assert buy(replace(BOOK, asks=())).status == "NO_LIQUIDITY"


@pytest.mark.parametrize("amount", [D(0), D(-1), D("NaN"), D("Infinity")])
def test_invalid_notional(amount: D) -> None:
    with pytest.raises(ValueError):
        buy(notional=amount)


def test_fee_requires_documented_parameters() -> None:
    with pytest.raises(ValueError):
        FeePolicy(D("0.1"), 1, "", False).per_share(D("0.5"))
