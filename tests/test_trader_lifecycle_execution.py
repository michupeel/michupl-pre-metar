from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import httpx
import pytest

from premetar.research.trader_execution import BookSnapshot, Level
from premetar.research.trader_monitor import Monitor
from premetar.research.trader_store import TraderStore


def lot(identity: str, detected: datetime, notional: int = 10) -> dict[str, Any]:
    return {
        "lot_id": identity,
        "token_id": "123",
        "condition_id": "condition",
        "strategy": "COPY_FOLLOW",
        "delay_seconds": 0,
        "notional": notional,
        "quantity": "20",
        "target_buy_quantity": "100",
        "gross_value": "10",
        "fee": "0",
        "net_value": "10",
        "vwap": "0.5",
        "created_at": (detected - timedelta(seconds=5)).isoformat(),
    }


async def test_follow_liquidity_depleted_within_scenario_not_between_scenarios(
    tmp_path: Path,
) -> None:
    detected = datetime.now(UTC) - timedelta(seconds=2)
    store = TraderStore(tmp_path / "test.db")
    for identity, notional in (("first", 10), ("second", 10), ("independent", 25)):
        store.append(
            "SHADOW", lot(identity, detected, notional), detected - timedelta(seconds=4), identity
        )
    later = {
        **lot("future-buy", detected),
        "created_at": (detected + timedelta(seconds=1)).isoformat(),
    }
    store.append("SHADOW", later, detected + timedelta(seconds=1), "future-buy")
    try:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(500))
        ) as client:
            monitor = Monitor(store, client, tmp_path / "absent", 3)
            snapshot = BookSnapshot(
                "123",
                detected + timedelta(seconds=1),
                (Level(D("0.6"), D(25)),),
                (Level(D("0.7"), D(100)),),
            )
            trade = {
                "trade_id": "sell",
                "token_id": "123",
                "size": "200",
                "first_collector_receipt_utc": detected.isoformat(),
            }
            market = {
                "active": True,
                "closed": False,
                "acceptingOrders": True,
                "feeType": "zero_fees",
                "feeSchedule": {"rate": 0},
            }
            await monitor.follow_sell(trade, 0, snapshot, market)
            amounts = {
                event["payload"]["lot_id"]: D(event["payload"]["quantity"])
                for event in store.events("EXIT")
            }
            assert amounts == {"first": D(20), "second": D(5), "independent": D(20)}
    finally:
        store.close()


async def test_closed_held_market_restored_after_restart_and_v2_settled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(UTC)
    path = tmp_path / "research.db"
    initial = TraderStore(path)
    initial.append("SHADOW", lot("held", now), now, "held")
    initial.close()
    store = TraderStore(path)
    try:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(500))
        ) as client:
            monitor = Monitor(store, client, tmp_path / "absent", 3)
            assert monitor.tokens == {}
            assert monitor.held_conditions == {"123": "condition"}

            async def market(condition: str, force: bool = False) -> dict[str, Any]:
                assert condition == "condition"
                return {
                    "closed": True,
                    "umaResolutionStatus": "resolved",
                    "version": "v2",
                    "positionIds": ["123"],
                    "outcomePrices": ["1"],
                    "_captured_at": now.isoformat(),
                }

            monkeypatch.setattr(monitor, "get_market", market)
            await monitor.lifecycle()
            await monitor.lifecycle()
            exits = store.events("EXIT")
            assert len(exits) == 1
            assert exits[0]["payload"]["kind"] == "SETTLEMENT"
            assert D(exits[0]["payload"]["quantity"]) == D(20)
    finally:
        store.close()
