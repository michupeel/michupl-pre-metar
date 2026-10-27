"""Entirely synthetic shadow flows; no public trades, network or real fills.

Virtual receipt clocks make all six predefined delays deterministic and fast.
Actual APIs are replaced with recorded-shape HTTP fixtures, never historical books.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from premetar.research import trader_monitor as module
from premetar.research.trader_monitor import DELAYS, NOTIONALS, STRATEGIES, Monitor
from premetar.research.trader_normalizer import WALLET, normalize_trade
from premetar.research.trader_portfolio import remaining_quantity
from premetar.research.trader_store import TraderStore

TOKEN = "987654321"
CONDITION = "0x" + "c" * 64


class SyntheticWorld:
    def __init__(self, root: Path) -> None:
        self.origin = datetime(2026, 10, 27, 8, tzinfo=UTC)
        self.clock = self.origin
        self.closed = False
        self.selling = False
        self.store = TraderStore(root / "synthetic.sqlite3")
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(self.http))
        self.monitor = Monitor(self.store, self.client, root / "absent-weather.sqlite3", 3)

    def http(self, request: httpx.Request) -> httpx.Response:
        self.clock += timedelta(milliseconds=20)
        if request.url.path == "/markets":
            assert request.url.params["condition_ids"] == CONDITION
            return httpx.Response(
                200,
                json=[
                    {
                        "conditionId": CONDITION,
                        "active": True,
                        "closed": self.closed,
                        "acceptingOrders": not self.closed,
                        "version": "v1",
                        "clobTokenIds": f'["{TOKEN}"]',
                        "outcomePrices": '["1"]',
                        "feeType": "zero_fees",
                        "feeSchedule": {"rate": 0, "exponent": 1},
                        "umaResolutionStatus": "resolved" if self.closed else "proposed",
                    }
                ],
            )
        assert request.url.path == "/book"
        assert request.url.params["token_id"] == TOKEN
        return httpx.Response(
            200,
            json={
                "asset_id": TOKEN,
                "hash": "synthetic-snapshot",
                "bids": [{"price": "0.60" if self.selling else "0.40", "size": "10000"}],
                "asks": [{"price": "0.70" if self.selling else "0.50", "size": "10000"}],
            },
        )

    async def pause(self, seconds: float) -> None:
        self.clock += timedelta(seconds=max(0, seconds), milliseconds=1)

    def trade(self, side: str, detected: datetime, index: int) -> dict[str, Any]:
        return normalize_trade(
            {
                "proxy_wallet": WALLET,
                "side": side,
                "token_id": TOKEN,
                "condition_id": CONDITION,
                "size": 100,
                "price": 0.4 if side == "BUY" else 0.6,
                "timestamp": int(detected.timestamp()) - 1,
                "transaction_hash": "0x" + f"{index:064x}",
                "title": "SYNTHETIC WEATHER FLOW",
                "outcome": "Yes",
            },
            detected,
            "PROSPECTIVE_POLL",
        )

    async def execute(self, trade: dict[str, Any], delay: int) -> None:
        due = datetime.fromisoformat(trade["first_collector_receipt_utc"]) + timedelta(
            seconds=delay
        )
        self.clock = max(self.clock, due)
        key = f"{trade['trade_id']}:{delay}"
        request = {"trade": trade, "delay_seconds": delay, "due_at": due.isoformat()}
        self.monitor.emit("COPY_REQUEST", request, self.clock, key)
        await self.monitor.copy_trade(request, key)


@pytest.fixture
async def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[SyntheticWorld]:
    scenario = SyntheticWorld(tmp_path)
    monkeypatch.setattr(module, "now", lambda: scenario.clock)
    monkeypatch.setattr(scenario.monitor, "pause", scenario.pause)
    try:
        yield scenario
    finally:
        await scenario.client.aclose()
        scenario.store.close()


async def test_all_delay_size_strategy_flows_follow_then_settle_without_rewriting(
    world: SyntheticWorld,
) -> None:
    buy = world.trade("BUY", world.origin, 1)
    for delay in DELAYS:
        await world.execute(buy, delay)
    original = world.store.events("SHADOW")
    assert len(original) == len(DELAYS) * len(NOTIONALS) * len(STRATEGIES) == 72
    assert {event["payload"]["status"] for event in original} == {"FILLED"}
    for event in original:
        payload = event["payload"]
        assert Decimal(payload["fee"]) == 0
        assert Decimal(payload["net_value"]) == Decimal(payload["notional"])
        assert datetime.fromisoformat(payload["executed_at"]) >= datetime.fromisoformat(
            payload["due_at"]
        )
    world.selling = True
    detected = world.clock + timedelta(seconds=10)
    sell = world.trade("SELL", detected, 2)
    for delay in DELAYS:
        await world.execute(sell, delay)
    lots, exits = world.monitor.portfolio()
    followed = [lot for lot in lots if lot.strategy == "COPY_FOLLOW"]
    assert len(followed) == 24
    assert all(remaining_quantity(lot, exits) == 0 for lot in followed)
    assert all(remaining_quantity(lot, exits) > 0 for lot in lots if lot.strategy != "COPY_FOLLOW")
    world.closed = True
    await world.monitor.lifecycle()
    lots, exits = world.monitor.portfolio()
    assert len(exits) == 72
    assert all(remaining_quantity(lot, exits) == 0 for lot in lots)
    before = world.store.events("EXIT")
    await world.monitor.lifecycle()
    assert world.store.events("EXIT") == before
    assert world.store.events("SHADOW") == original
    assert world.store.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


async def test_follow_sell_can_exit_prior_signal_buy_executed_after_sell_detection(
    world: SyntheticWorld,
) -> None:
    # BUY detected at0, SELL detected at6; delay10 gives BUY execution10 and SELL16.
    # Both signals are earlier than their own simulated executions. No future data.
    buy = world.trade("BUY", world.origin, 1)
    await world.execute(buy, 10)
    world.selling = True
    sell = world.trade("SELL", world.origin + timedelta(seconds=6), 2)
    await world.execute(sell, 10)
    lots, exits = world.monitor.portfolio()
    followed = [lot for lot in lots if lot.strategy == "COPY_FOLLOW"]
    assert len(followed) == 4
    assert all(remaining_quantity(lot, exits) == 0 for lot in followed)


async def test_follow_sell_does_not_consume_buy_signal_first_detected_later(
    world: SyntheticWorld,
) -> None:
    # A later unrelated BUY signal cannot be assigned retrospectively to an earlier SELL.
    sell = world.trade("SELL", world.origin + timedelta(seconds=6), 2)
    buy = world.trade("BUY", world.origin + timedelta(seconds=7), 1)
    await world.execute(buy, 0)
    world.selling = True
    await world.execute(sell, 10)
    lots, exits = world.monitor.portfolio()
    assert all(remaining_quantity(lot, exits) == lot.quantity for lot in lots)
