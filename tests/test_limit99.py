"""Synthetic public-feed shadow execution, never actual orders or live databases."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from premetar.research.limit99 import Limit99

AT = datetime(2026, 10, 28, 10, tzinfo=UTC)
D = Decimal


def test_missing_arrival_book_is_unknown_with_reserved_risk_not_zero_profit() -> None:
    engine = Limit99(config())
    engine.observe(AT, market(), book(), {})
    engine.observe(AT + timedelta(seconds=4), market(), None, {})
    p = portfolio(engine)
    assert orders(p)[0]["state"] == "UNKNOWN"
    assert D(p["reserved"]) > D("4.9")
    metric = next(
        r
        for r in engine.metrics(AT + timedelta(seconds=4))
        if r["family"] == "SIMPLE" and r["mode"] == "TAKER"
    )
    assert metric["net_pnl"] is None
    assert metric["realized_pnl"] is None
    assert metric["unresolved_orders"] == 1
    assert metric["maximum_loss"] > 4.9
    assert metric["paper_orders_never_filled"] == 0


def config(**changes: Any) -> dict[str, Any]:
    result = json.loads(
        (Path(__file__).parents[1] / "configs/experiments/epwa-battle-v1.json").read_text()
    )
    result["latencies_ms"] = [100]
    result.update(changes)
    return result


def market(at: datetime = AT, condition: str = "c", **metadata: Any) -> dict[str, Any]:
    return dict(
        identity=dict(
            airport="EPWA",
            station_match=True,
            day="2026-10-28",
            condition_id=condition,
            no="no-" + condition,
            yes="yes-" + condition,
            outcome_label="15°C",
        ),
        metadata=dict(
            orderPriceMinTickSize=".01",
            orderMinSize="5",
            active=True,
            closed=False,
            acceptingOrders=True,
            feeType="zero_fees",
            feeSchedule={"rate": 0},
            **metadata,
        ),
        received_at=at.isoformat(),
    )


def book(
    at: datetime = AT,
    bid: str = ".90",
    ask: str = ".95",
    bid_size: str = "20",
    ask_size: str = "20",
    condition: str = "c",
) -> dict[str, Any]:
    return dict(
        status="VALID",
        token_id="no-" + condition,
        market=condition,
        connection_id="epoch",
        received_at=at.isoformat(),
        bids=[dict(price=bid, size=bid_size)],
        asks=[dict(price=ask, size=ask_size)],
    )


def portfolio(
    engine: Limit99, mode: str = "TAKER", scenario: str | None = None, family: str = "SIMPLE"
) -> dict[str, Any]:
    scenario = scenario or ("DEPTH_SUPPORTED" if mode == "TAKER" else "EVIDENCE_SUPPORTED")
    return engine.state["portfolios"][f"{family}:{mode}:{scenario}:100"]


def orders(p: dict[str, Any], side: str = "BUY") -> list[dict[str, Any]]:
    return [o for o in p["orders"] if o["side"] == side]


def trade(
    at: datetime,
    *,
    quantity: str = "6",
    price: str = ".95",
    side: str = "SELL",
    source: datetime | None = None,
) -> dict[str, Any]:
    return dict(
        token_id="no-c",
        market="c",
        connection_id="epoch",
        price=price,
        size=quantity,
        side=side,
        received_at=at.isoformat(),
        source_timestamp=str(int((source or at - timedelta(milliseconds=10)).timestamp() * 1000)),
    )


def opened_taker() -> tuple[Limit99, dict[str, Any]]:
    engine = Limit99(config())
    engine.observe(AT, market(), book(), {})
    arrival = AT + timedelta(milliseconds=100)
    engine.observe(arrival, market(), book(arrival), {})
    return engine, portfolio(engine)


def rested_maker(scenario: str = "EVIDENCE_SUPPORTED") -> tuple[Limit99, dict[str, Any]]:
    engine = Limit99(config())
    engine.observe(AT, market(), book(bid=".95", ask=".97", bid_size="4"), {})
    arrival = AT + timedelta(milliseconds=100)
    engine.observe(arrival, market(), book(arrival, bid=".95", ask=".97", bid_size="4"), {})
    return engine, portfolio(engine, "MAKER", scenario)


@pytest.mark.parametrize("age,expected", [(0, 1), (91, 0)])
def test_hybrid_requires_fresh_frozen_weather_assessment(age: int, expected: int) -> None:
    engine = Limit99(config())
    weather = dict(
        weather_gate=True,
        adaptive_tmax={"temperature_c": 12},
        created_at=(AT - timedelta(seconds=age)).isoformat(),
    )
    engine.observe(AT, market(), book(), weather)
    assert portfolio(engine, family="HYBRID")["submitted_orders"] == expected
    assert portfolio(engine)["submitted_orders"] == 1


def test_unrelated_stale_token_does_not_invalidate_resting_queue() -> None:
    engine, p = rested_maker()
    engine.invalidate(AT + timedelta(seconds=1), None, "unrelated-token")
    assert orders(p)[0]["queue_valid"]
    engine.invalidate(AT + timedelta(seconds=1), None, "no-c")
    assert not orders(p)[0]["queue_valid"]


@pytest.mark.parametrize(("price", "expected"), [(".91", 0), (".92", 1), (".97", 1), (".98", 0)])
def test_strict_primary_entry_boundaries(price: str, expected: int) -> None:
    engine = Limit99(config())
    engine.observe(AT, market(), book(ask=price), {})
    assert portfolio(engine)["submitted_orders"] == expected


def test_98_is_separate_predeclared_control() -> None:
    engine = Limit99(config())
    engine.observe(AT, market(), book(ask=".98"), {})
    assert portfolio(engine)["submitted_orders"] == 0
    assert portfolio(engine, family="SIMPLE_98_CONTROL")["submitted_orders"] == 1


def test_decision_book_cannot_fill_later_arrival() -> None:
    engine = Limit99(config())
    engine.observe(AT, market(), book(), {})
    engine.observe(AT + timedelta(milliseconds=100), market(), book(), {})
    assert not portfolio(engine)["positions"]
    assert orders(portfolio(engine))[0]["state"] == "PENDING_SUBMISSION"


def test_partial_depth_only_buys_available_inventory_and_cancels_remainder() -> None:
    engine = Limit99(config())
    engine.observe(AT, market(), book(), {})
    arrival = AT + timedelta(milliseconds=100)
    engine.observe(arrival, market(), book(arrival, ask_size="2"), {})
    p = portfolio(engine)
    assert D(p["positions"]["c"]["quantity"]) == 2
    assert orders(p)[0]["state"] == "CANCELLED"
    assert D(p["reserved"]) == 0
    assert sum(D(o["quantity"]) for o in orders(p, "SELL")) == 2
    assert D(p["cash"]) + D(p["positions"]["c"]["cost"]) == 100


def test_post_only_would_cross_is_rejected_without_inventory() -> None:
    engine = Limit99(config())
    engine.observe(AT, market(), book(bid=".95", ask=".97"), {})
    arrival = AT + timedelta(milliseconds=100)
    engine.observe(arrival, market(), book(arrival, bid=".94", ask=".95"), {})
    p = portfolio(engine, "MAKER")
    assert not p["positions"]
    assert orders(p)[0]["state"] == "REJECTED"
    assert D(p["reserved"]) == 0


def test_maker_queue_trade_consumes_displayed_ahead_before_partial_fill() -> None:
    engine, p = rested_maker()
    at = AT + timedelta(seconds=2)
    engine.observe(at, market(), book(at, bid=".95", ask=".97", bid_size="4"), {}, trade(at))
    assert D(p["positions"]["c"]["quantity"]) == 2
    assert D(orders(p)[0]["queue_ahead"]) == 0
    assert orders(p)[0]["state"] == "PARTIALLY_FILLED"


def test_duplicate_upstream_trade_does_not_fill_twice() -> None:
    engine, p = rested_maker()
    at = AT + timedelta(seconds=2)
    execution = trade(at)
    engine.observe(at, market(), book(at, bid=".95", ask=".97"), {}, execution)
    before = deepcopy(p["positions"])
    later = at + timedelta(seconds=1)
    execution["received_at"] = later.isoformat()
    engine.observe(later, market(), book(later, bid=".95", ask=".97"), {}, execution)
    assert p["positions"] == before


@pytest.mark.parametrize("source", [AT, AT + timedelta(milliseconds=100)])
def test_delayed_trade_from_before_resting_cannot_fill(source: datetime) -> None:
    engine, p = rested_maker()
    at = AT + timedelta(seconds=2)
    engine.observe(at, market(), book(at, bid=".95", ask=".97"), {}, trade(at, source=source))
    assert not p["positions"]


def test_pessimistic_maker_has_no_fill_from_public_trade_alone() -> None:
    engine, p = rested_maker("PESSIMISTIC")
    at = AT + timedelta(seconds=2)
    engine.observe(at, market(), book(at, bid=".95", ask=".97"), {}, trade(at, quantity="100"))
    assert not p["positions"]


def test_cancel_request_is_not_effective_until_declared_arrival() -> None:
    engine, p = rested_maker()
    expires = AT + timedelta(seconds=60)
    engine.observe(expires, market(), book(expires, bid=".95", ask=".97"), {})
    assert orders(p)[0]["state"] == "CANCEL_PENDING"
    intermediate = expires + timedelta(milliseconds=100)
    engine.observe(
        intermediate,
        market(),
        book(intermediate, bid=".95", ask=".97"),
        {},
        trade(intermediate, quantity="5"),
    )
    assert D(p["positions"]["c"]["quantity"]) == 1
    cancelled = expires + timedelta(milliseconds=250)
    engine.observe(cancelled, market(), book(cancelled, bid=".95", ask=".97"), {})
    assert orders(p)[0]["state"] == "EXPIRED"
    assert D(p["reserved"]) == 0


def test_missing_fee_schedule_blocks_entry() -> None:
    engine = Limit99(config())
    m = market()
    m["metadata"].pop("feeSchedule")
    engine.observe(AT, m, book(), {})
    assert not portfolio(engine)["positions"]
    assert not orders(portfolio(engine))
    assert any(
        e["kind"] == "ORDER_REJECTED"
        and e["payload"].get("reason") == "UNKNOWN_OR_UNSUPPORTED_FEES"
        for e in engine.drain()
    )


def test_stale_book_blocks_entry() -> None:
    engine = Limit99(config())
    engine.observe(AT + timedelta(seconds=6), market(), book(), {})
    assert portfolio(engine)["submitted_orders"] == 0


def test_current_metadata_must_still_be_eligible_at_arrival() -> None:
    engine = Limit99(config(metadata_max_age_seconds=0.05))
    engine.observe(AT, market(), book(), {})
    arrival = AT + timedelta(milliseconds=100)
    engine.observe(arrival, market(), book(arrival), {})
    assert not portfolio(engine)["positions"]
    assert orders(portfolio(engine))[0]["state"] == "REJECTED"


def test_restart_does_not_refresh_old_queue_evidence() -> None:
    engine, p = rested_maker()
    reserve = p["reserved"]
    engine.restart(AT + timedelta(seconds=1))
    at = AT + timedelta(seconds=2)
    engine.observe(at, market(), book(at, bid=".95", ask=".97"), {}, trade(at, quantity="100"))
    assert not p["positions"]
    assert not orders(p)[0]["queue_valid"]
    assert orders(p)[0]["state"] == "UNKNOWN"
    assert p["reserved"] == reserve
    engine.restart(at)
    assert p["reserved"] == reserve


def test_full_taker_roundtrip_conserves_cash_and_cannot_sell_more_than_bought() -> None:
    engine, p = opened_taker()
    quantity = D(p["positions"]["c"]["quantity"])
    cost = D(p["positions"]["c"]["cost"])
    arrival = AT + timedelta(milliseconds=200)
    engine.observe(arrival, market(), book(arrival, bid=".99", ask=".999", bid_size="1000"), {})
    assert D(p["positions"]["c"]["quantity"]) == 0
    assert D(p["cash"]) == 100 - cost + quantity * D(".99")
    assert D(p["realized"]) == quantity * D(".99") - cost
    cash = p["cash"]
    engine.observe(
        arrival + timedelta(seconds=1),
        market(),
        book(arrival + timedelta(seconds=1), bid=".99", ask=".999"),
        {},
    )
    assert p["cash"] == cash


@pytest.mark.parametrize("payout", ["0", "1"])
def test_verified_settlement_includes_loss_or_gain_and_is_idempotent(payout: str) -> None:
    engine, p = opened_taker()
    quantity = D(p["positions"]["c"]["quantity"])
    cost = D(p["positions"]["c"]["cost"])
    m = market()
    m["metadata"].update(
        closed=True,
        acceptingOrders=False,
        umaResolutionStatus="resolved",
        outcomes=["Yes", "No"],
        outcomePrices=[str(1 - int(payout)), payout],
    )
    engine.settle(AT + timedelta(hours=1), m)
    assert D(p["cash"]) == 100 - cost + quantity * D(payout)
    assert D(p["realized"]) == quantity * D(payout) - cost
    state = deepcopy(engine.state)
    engine.settle(AT + timedelta(hours=2), m)
    assert engine.state == state


def test_unresolved_market_cannot_be_settled_using_temperature_proxy() -> None:
    engine, p = opened_taker()
    original = deepcopy(p)
    m = market()
    m["metadata"].update(closed=True, outcomePrices=["1", "0"], outcomes=["Yes", "No"])
    engine.settle(AT + timedelta(hours=1), m)
    assert p == original


def test_frozen_portfolio_cannot_restart_with_changed_configuration() -> None:
    engine, _ = opened_taker()
    with pytest.raises(ValueError, match="Frozen config mismatch"):
        Limit99(config(order_budget_usd="10"), deepcopy(engine.state))


def test_capital_time_counts_only_actual_holding_interval() -> None:
    engine = Limit99(config())
    engine.metrics(AT)
    entry = AT + timedelta(seconds=30)
    engine.observe(entry, market(entry), book(entry), {})
    arrival = entry + timedelta(milliseconds=100)
    engine.observe(arrival, market(entry), book(arrival), {})
    p = portfolio(engine)
    cost = D(p["positions"]["c"]["cost"])
    result = next(
        r
        for r in engine.metrics(AT + timedelta(seconds=60))
        if r["family"] == "SIMPLE" and r["mode"] == "TAKER"
    )
    assert D(result["capital_time_usd_seconds"]) == cost * D("29.9")


def test_simple_strategy_decisions_do_not_depend_on_weather() -> None:
    a, b = Limit99(config()), Limit99(config())
    a.observe(AT, market(), book(), {})
    b.observe(
        AT,
        market(),
        book(),
        {"weather_gate": True, "adaptive_tmax": 12, "confidence": "FORECAST HIGH RISK"},
    )
    assert portfolio(a) == portfolio(b)
