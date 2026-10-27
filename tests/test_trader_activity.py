"""Synthetic public activity/trade feed races; no real API calls or executions."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from premetar.research.trader_monitor import Monitor
from premetar.research.trader_normalizer import WALLET
from premetar.research.trader_store import TraderStore


def trade(index: int = 1) -> dict[str, Any]:
    return {
        "proxy_wallet": WALLET,
        "side": "BUY",
        "size": 10.0,
        "price": 0.98,
        "timestamp": int(datetime.now(UTC).timestamp()) - 10,
        "token_id": "123456789",
        "condition_id": "0x" + "a" * 64,
        "transaction_hash": "0x" + f"{index:064x}",
        "title": "Synthetic weather market",
        "outcome": "No",
    }


def page(rows: list[dict[str, Any]], cursor: str | None = None) -> dict[str, Any]:
    return {"data": rows, "pagination": {"has_more": cursor is not None, "next_cursor": cursor}}


@pytest.fixture
async def monitor(tmp_path: Path) -> AsyncIterator[Monitor]:
    store = TraderStore(tmp_path / "activity-research.sqlite3")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=page([])))
    ) as client:
        instance = Monitor(store, client, tmp_path / "unavailable-weather.sqlite3", 3)
        try:
            yield instance
        finally:
            instance.stop.set()
            store.close()


@pytest.mark.parametrize("activity_first", [True, False])
async def test_crossfeed_race_keeps_one_first_receipt_and_one_copy_signal(
    monitor: Monitor, activity_first: bool
) -> None:
    original = trade()

    def handler(request: httpx.Request) -> httpx.Response:
        item = (
            {**original, "type": "TRADE", "usdc_size": 9.8}
            if request.url.path == "/v2/activity"
            else original
        )
        return httpx.Response(200, json=page([item]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        monitor.client = client
        monitor.last_poll = datetime.now(UTC) - timedelta(seconds=3)
        monitor.last_activity_poll = datetime.now(UTC) - timedelta(seconds=3)
        first = monitor.poll_activity if activity_first else monitor.poll_trades
        second = monitor.poll_trades if activity_first else monitor.poll_activity
        await first()
        initial = monitor.store.events("TRADE")[0]
        await second()
        await first()
        await second()
    assert monitor.store.events("TRADE") == [initial]
    assert monitor.trade_queue.qsize() == 1
    assert len(monitor.store.events("ENDPOINT_RECEIPT")) == 2
    endpoint = initial["payload"]["detection_endpoint"]
    assert ("activity" in endpoint.lower()) == activity_first
    assert initial["payload"]["evidence_class"] == "PROSPECTIVE_POLL"


async def test_activity_bootstrap_does_not_create_copy_or_live_latency(monitor: Monitor) -> None:
    item = {**trade(), "type": "TRADE"}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=page([item])))
    ) as client:
        monitor.client = client
        await monitor.poll_activity()
    rows = monitor.store.events("TRADE")
    assert len(rows) == 1
    assert rows[0]["payload"]["evidence_class"] == "BOOTSTRAP_HISTORICAL"
    assert monitor.trade_queue.empty()
    assert monitor.store.events("COPY_REQUEST") == []


async def test_activity_pages_retain_filters_and_cursor_direction(monitor: Monitor) -> None:
    requests: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/activity"
        params = dict(request.url.params)
        requests.append(params)
        return httpx.Response(
            200,
            json=page([{**trade(2), "type": "TRADE"}])
            if params.get("cursor")
            else page([{**trade(), "type": "TRADE"}], "next-activity"),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        monitor.client = client
        await monitor.poll_activity()
    assert len(requests) == 2
    assert requests[0]["user"] == WALLET
    assert requests[1]["cursor"] == "next-activity"
    assert "offset" not in requests[0] and "offset" not in requests[1]
    assert {k: v for k, v in requests[1].items() if k != "cursor"} == requests[0]
    assert len(monitor.store.events("TRADE")) == 2


@pytest.mark.parametrize("kind", ["REDEEM", "SPLIT", "MERGE", "REWARD"])
async def test_nontrade_inventory_activity_never_becomes_buy(monitor: Monitor, kind: str) -> None:
    item = {**trade(), "type": kind}
    monitor.last_activity_poll = datetime.now(UTC) - timedelta(seconds=3)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=page([item])))
    ) as client:
        monitor.client = client
        await monitor.poll_activity()
    assert monitor.store.events("TRADE") == []
    assert monitor.trade_queue.empty()
    assert monitor.store.events("COPY_REQUEST") == []
    assert len(monitor.store.events("ACTIVITY")) == 1


async def test_missing_wallet_activity_trade_is_not_copied(monitor: Monitor) -> None:
    item = {**trade(), "type": "TRADE"}
    del item["proxy_wallet"]
    monitor.last_activity_poll = datetime.now(UTC) - timedelta(seconds=3)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=page([item])))
    ) as client:
        monitor.client = client
        await monitor.poll_activity()
    assert monitor.store.events("TRADE") == []
    assert monitor.trade_queue.empty()
    assert monitor.store.events("NORMALIZATION_REJECTION")


async def test_bad_activity_response_does_not_disable_trades_route(monitor: Monitor) -> None:
    original = trade()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"unexpected": "shape"}
            if request.url.path == "/v2/activity"
            else page([original]),
        )

    monitor.last_poll = datetime.now(UTC) - timedelta(seconds=3)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        monitor.client = client
        with pytest.raises(ValueError):
            await monitor.poll_activity()
        await monitor.poll_trades()
    assert len(monitor.store.events("TRADE")) == 1
    assert monitor.trade_queue.qsize() == 1
    assert len(monitor.store.events("RAW")) == 2


async def test_gap_censored_activity_cannot_emit_live_copy(monitor: Monitor) -> None:
    monitor.last_activity_poll = datetime.now(UTC) - timedelta(minutes=2)
    item = {**trade(), "type": "TRADE"}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=page([item])))
    ) as client:
        monitor.client = client
        await monitor.poll_activity()
    assert monitor.store.events("TRADE")[0]["payload"]["evidence_class"] == "GAP_CENSORED"
    assert monitor.trade_queue.empty()
