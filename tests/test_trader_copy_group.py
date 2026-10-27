"""Different public projections cannot trigger two copies of one source action."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from premetar.research.trader_monitor import Monitor
from premetar.research.trader_normalizer import WALLET
from premetar.research.trader_store import TraderStore


@pytest.mark.asyncio
async def test_feed_partition_or_rounding_difference_preserves_rows_not_duplicate_copies(
    tmp_path: Path,
) -> None:
    store = TraderStore(tmp_path / "research.sqlite3")
    async with httpx.AsyncClient() as client:
        monitor = Monitor(store, client, tmp_path / "weather.sqlite3", 3)
        received = datetime(2026, 10, 27, 9, 22, 33, tzinfo=UTC)
        row = {
            "proxy_wallet": WALLET,
            "side": "BUY",
            "token_id": "123",
            "condition_id": "0xcondition",
            "transaction_hash": "0xtx",
            "price": 0.98,
            "size": 38.35,
            "timestamp": int((received - timedelta(seconds=3)).timestamp()),
        }
        await monitor.record_trade(
            row, received, "PROSPECTIVE_POLL", received - timedelta(seconds=3), "TRADES_V2"
        )
        await monitor.record_trade(
            {**row, "price": 0.9800001},
            received + timedelta(seconds=1),
            "PROSPECTIVE_POLL",
            received,
            "ACTIVITY_V2",
        )
        assert len(store.events("TRADE")) == 2
        assert len(store.events("EXECUTION_GROUP")) == 1
        assert len(store.events("COPY_SUPPRESSED")) == 1
        assert monitor.trade_queue.qsize() == 1
    store.close()


@pytest.mark.asyncio
async def test_historical_group_cannot_reappear_as_new_signal(tmp_path: Path) -> None:
    store = TraderStore(tmp_path / "research.sqlite3")
    async with httpx.AsyncClient() as client:
        monitor = Monitor(store, client, tmp_path / "weather.sqlite3", 3)
        received = datetime(2026, 10, 27, 9, 22, 33, tzinfo=UTC)
        row = {
            "proxy_wallet": WALLET,
            "side": "BUY",
            "token_id": "123",
            "condition_id": "0xcondition",
            "transaction_hash": "0xtx",
            "price": 0.98,
            "size": 38.35,
            "timestamp": int((received - timedelta(seconds=3)).timestamp()),
        }
        await monitor.record_trade(row, received, "BOOTSTRAP_HISTORICAL", None, "TRADES_V2")
        await monitor.record_trade(
            {**row, "size": 38.350001},
            received + timedelta(seconds=1),
            "PROSPECTIVE_POLL",
            received,
            "ACTIVITY_V2",
        )
        assert monitor.trade_queue.empty()
    store.close()
