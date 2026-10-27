from dataclasses import replace
from decimal import Decimal as D

import pytest

from premetar.research.trader_portfolio import (
    ExitRecord,
    ShadowLot,
    follow_exit_plans,
    portfolio_metrics,
    remaining_quantity,
    settlement_plans,
    take_profit_plans,
)

LOT = ShadowLot("a", "token", "COPY_FOLLOW", 0, D(10), D(20), D(100), D(10), D(0), D(10), D("0.5"))


def test_follow_proportional_fifo_per_cohort() -> None:
    other = replace(LOT, lot_id="b")
    delayed = replace(LOT, lot_id="c", delay_seconds=1)
    plans = follow_exit_plans(
        [LOT, other, delayed], [], token_id="token", target_sell_quantity=D(150)
    )
    assert [(p.lot_id, p.quantity) for p in plans] == [("a", D(20)), ("b", D(10)), ("c", D(20))]


def test_follow_actual_partial_fill_respects_remaining() -> None:
    exits = [ExitRecord("a", D(5), D(3), D(0), D(3), "COPY_FOLLOW")]
    plan = follow_exit_plans([LOT], exits, token_id="token", target_sell_quantity=D(50))[0]
    assert plan.quantity == D(10)
    assert remaining_quantity(LOT, exits) == D(15)


def test_no_reexit_closed_lot() -> None:
    exits = [ExitRecord("a", D(20), D(12), D(0), D(12), "COPY_FOLLOW")]
    assert not follow_exit_plans([LOT], exits, token_id="token", target_sell_quantity=D(100))
    assert not settlement_plans(
        [LOT], exits, token_id="token", payout=D(1), verified_resolution=True
    )


def test_take_profit_threshold_not_price_peeking() -> None:
    lot = replace(LOT, strategy="COPY_TAKE_PROFIT")
    assert not take_profit_plans([lot], [], token_id="token", best_bid=D("0.54"))
    plan = take_profit_plans([lot], [], token_id="token", best_bid=D("0.55"))[0]
    assert plan.limit_price == D("0.55")
    assert plan.quantity == D(20)
    high = replace(lot, entry_vwap=D("0.995"))
    assert not take_profit_plans([high], [], token_id="token", best_bid=D(1))


def test_settlement_requires_verified_binary_payout() -> None:
    assert not settlement_plans([LOT], [], token_id="token", payout=D(1), verified_resolution=False)
    assert (
        settlement_plans([LOT], [], token_id="token", payout=D(0), verified_resolution=True)[
            0
        ].payout_per_share
        == 0
    )
    with pytest.raises(ValueError):
        settlement_plans([LOT], [], token_id="token", payout=D("0.5"), verified_resolution=True)


def test_realized_only_metrics_and_unknown_fee() -> None:
    winning = ExitRecord("a", D(20), D(20), D(0), D(20), "SETTLEMENT")
    unknown = replace(LOT, lot_id="b", entry_fee=None, entry_net=None)
    open_lot = replace(LOT, lot_id="c")
    exits = [winning, replace(winning, lot_id="b")]
    metrics = portfolio_metrics([LOT, unknown, open_lot], exits)
    assert metrics["net_pnl"] == D(10)
    assert metrics["net_roi"] == D(1)
    assert metrics["wins"] == 1 and metrics["win_rate"] == 1
    assert metrics["unverifiable_closed_lots"] == 1
    assert metrics["unresolved_lots"] == 1
    assert metrics["unresolved_quantity"] == 20


def test_losses_and_closed_drawdown() -> None:
    second = replace(LOT, lot_id="b")
    exits = [
        ExitRecord("a", D(20), D(15), D(0), D(15), "EXIT"),
        ExitRecord("b", D(20), D(2), D(0), D(2), "EXIT"),
    ]
    metrics = portfolio_metrics([LOT, second], exits)
    assert metrics["net_pnl"] == D(-3)
    assert metrics["maximum_closed_equity_drawdown"] == D(8)
    assert metrics["profit_factor"] == D(5) / D(8)
    assert metrics["average_loss"] == D(-8)


def test_empty_no_manufactured_performance() -> None:
    metrics = portfolio_metrics([], [])
    assert metrics["net_pnl"] is None
    assert metrics["net_roi"] is None and metrics["win_rate"] is None


def test_overexit_and_duplicate_lots_rejected() -> None:
    with pytest.raises(ValueError):
        remaining_quantity(LOT, [ExitRecord("a", D(21), D(21), D(0), D(21), "EXIT")])
    with pytest.raises(ValueError):
        portfolio_metrics([LOT, LOT], [])
    with pytest.raises(ValueError):
        portfolio_metrics([], [ExitRecord("unknown", D(1), D(1), D(0), D(1), "EXIT")])
