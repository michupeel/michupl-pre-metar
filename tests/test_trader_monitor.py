"""Deterministic HTTP fixtures for EXP0011; no live APIs or weather writes.

Trade fixtures use the field shape captured in data/trader/probe/trades.json.
Amounts, clocks and identifiers are synthetic and never research observations.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from premetar.research import trader_monitor as module
from premetar.research.trader_execution import simulate_buy
from premetar.research.trader_monitor import Monitor, open_market, parse_book, verified_fee
from premetar.research.trader_normalizer import WALLET
from premetar.research.trader_portfolio import ExitRecord, ShadowLot
from premetar.research.trader_store import TraderStore, read_events

CONDITION = "0x" + "a" * 64
TOKEN = "12345678901234567890"


def row(index: int = 1) -> dict[str, Any]:
    return {
        "proxy_wallet": WALLET,
        "side": "BUY",
        "token_id": TOKEN,
        "condition_id": CONDITION,
        "size": 9.0,
        "price": 0.98,
        "timestamp": 1793087526,
        "transaction_hash": "0x" + f"{index:064x}",
        "title": "Synthetic temperature test",
        "outcome": "No",
    }


def page(rows: list[dict[str, Any]], cursor: str | None = None) -> dict[str, Any]:
    return {"data": rows, "pagination": {"has_more": cursor is not None, "next_cursor": cursor}}


def market() -> dict[str, Any]:
    return {
        "conditionId": CONDITION,
        "active": True,
        "closed": False,
        "acceptingOrders": True,
        "clobTokenIds": '["12345678901234567890"]',
        "feeType": "zero_fees",
        "feeSchedule": {"rate": 0, "exponent": 1, "takerOnly": True},
    }


@pytest.fixture
async def monitor(tmp_path: Path) -> AsyncIterator[Monitor]:
    def unexpected(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"Unexpected external request {request.method} {request.url.path}")

    store = TraderStore(tmp_path / "research.sqlite3")
    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as client:
        instance = Monitor(store, client, tmp_path / "absent-weather.sqlite3", 3)
        try:
            yield instance
        finally:
            instance.stop.set()
            for task in list(instance.tasks):
                task.cancel()
            await asyncio.gather(*list(instance.tasks), return_exceptions=True)
            store.close()


def test_verified_zero_curve_does_not_confuse_base_fee_with_effective_rate() -> None:
    payload = {**market(), "feesEnabled": True, "takerBaseFee": 1000, "base_fee": 1000}
    fee = verified_fee(payload)
    assert fee is not None
    assert fee.per_share(Decimal("0.98")) == 0
    assert verified_fee({"base_fee": 1000, "feesEnabled": True}) is None
    assert verified_fee({"feeType": "zero_fees"}) is None
    assert verified_fee({"feeSchedule": {"rate": 0.05}}) is None


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({}, None),
        ({"active": True}, None),
        ({"closed": True}, False),
        ({"acceptingOrders": False}, False),
        ({"active": True, "closed": False, "acceptingOrders": True}, True),
    ],
)
def test_market_open_requires_positive_state_evidence(
    payload: dict[str, Any], expected: bool | None
) -> None:
    assert open_market(payload) is expected


@pytest.mark.parametrize("payload", [None, [], {}, {"asset_id": "wrong", "bids": [], "asks": []}])
def test_book_wrong_token_never_relabelled(payload: object) -> None:
    with pytest.raises(ValueError, match="WRONG_BOOK_TOKEN"):
        parse_book(payload, TOKEN, datetime.now(UTC))


@pytest.mark.parametrize(
    "payload",
    [
        {"asset_id": TOKEN},
        {"asset_id": TOKEN, "bids": [], "asks": None},
        {"asset_id": TOKEN, "bids": {}, "asks": []},
    ],
)
def test_missing_depth_is_not_assumed_empty_or_complete(payload: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="INCOMPLETE_BOOK"):
        parse_book(payload, TOKEN, datetime.now(UTC))


def test_future_book_cannot_fill_at_an_earlier_decision() -> None:
    decision = datetime(2026, 10, 27, 8, 0, tzinfo=UTC)
    snapshot = parse_book(
        {
            "asset_id": TOKEN,
            "bids": [{"price": "0.90", "size": "100"}],
            "asks": [{"price": "0.98", "size": "100"}],
        },
        TOKEN,
        decision + timedelta(seconds=1),
    )
    result = simulate_buy(
        snapshot,
        Decimal(10),
        detected_at=decision - timedelta(seconds=2),
        due_at=decision - timedelta(seconds=1),
        decision_at=decision,
        market_open=True,
    )
    assert result.status == "UNKNOWN"
    assert result.reason == "FUTURE_BOOK"
    assert result.quantity == 0


@pytest.mark.parametrize(
    "payload",
    [
        [],
        [{"conditionId": "0x" + "b" * 64}],
        [{"conditionId": CONDITION}, {"conditionId": CONDITION}],
    ],
)
async def test_market_identity_mismatch_rejected(monitor: Monitor, payload: object) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as client:
        monitor.client = client
        with pytest.raises(ValueError, match="MARKET_IDENTITY_UNVERIFIED"):
            await monitor.get_market(CONDITION)
    assert monitor.store.events("MARKET") == []
    assert len(monitor.store.events("RAW")) == 1


async def test_targeted_market_lookup_includes_closed_for_settlement(monitor: Monitor) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["condition_ids"] == CONDITION
        assert request.url.params["closed"] == "any"
        return httpx.Response(200, json=[market()])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        monitor.client = client
        result = await monitor.get_market(CONDITION)
    assert result["conditionId"] == CONDITION


async def test_settlement_refreshes_holdings_after_network_await(
    monitor: Monitor, monkeypatch: pytest.MonkeyPatch
) -> None:
    lot = ShadowLot(
        "original-lot",
        TOKEN,
        "COPY_FOLLOW",
        0,
        Decimal(10),
        Decimal(10),
        Decimal(9),
        Decimal(9),
        Decimal(0),
        Decimal(9),
        Decimal("0.9"),
    )
    complete_exit = ExitRecord(
        "original-lot", Decimal(10), Decimal(10), Decimal(0), Decimal(10), "COPY_FOLLOW"
    )
    exit_arrived = False
    reads = 0

    def portfolio() -> tuple[list[ShadowLot], list[ExitRecord]]:
        nonlocal reads
        reads += 1
        return [lot], [complete_exit] if exit_arrived else []

    async def fetched(_: str, force: bool = False) -> dict[str, Any]:
        nonlocal exit_arrived
        await asyncio.sleep(0)
        exit_arrived = True
        return {
            "closed": True,
            "umaResolutionStatus": "resolved",
            "clobTokenIds": f'["{TOKEN}"]',
            "outcomePrices": '["1"]',
            "_captured_at": datetime.now(UTC).isoformat(),
        }

    monkeypatch.setattr(monitor, "portfolio", portfolio)
    monkeypatch.setattr(monitor, "get_market", fetched)
    monitor.tokens[TOKEN] = CONDITION
    await monitor.lifecycle()
    assert reads >= 2
    assert monitor.store.events("EXIT") == []


async def test_bootstrap_pagination_retains_filters_and_never_creates_copy_requests(
    monitor: Monitor,
) -> None:
    queries: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/markets":
            return httpx.Response(200, json=[market()])
        assert request.url.path == "/v2/trades"
        params = dict(request.url.params)
        queries.append(params)
        return httpx.Response(
            200, json=page([row(2)]) if params.get("cursor") else page([row()], "opaque-next")
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        monitor.client = client
        await monitor.poll_trades()
        if monitor.tasks:
            await asyncio.gather(*list(monitor.tasks))
    assert len(queries) == 2
    assert queries[0]["taker_only"] == "false"
    assert queries[1]["cursor"] == "opaque-next"
    assert "offset" not in queries[0] and "offset" not in queries[1]
    assert {k: v for k, v in queries[1].items() if k != "cursor"} == queries[0]
    trades = monitor.store.events("TRADE")
    assert len(trades) == 2
    assert {item["payload"]["evidence_class"] for item in trades} == {"BOOTSTRAP_HISTORICAL"}
    assert monitor.store.events("COPY_REQUEST") == []


async def test_duplicate_poll_preserves_first_receipt_and_never_rearms_bootstrap(
    monitor: Monitor,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=[market()] if request.url.path == "/markets" else page([row()])
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        monitor.client = client
        await monitor.poll_trades()
        first = monitor.store.events("TRADE")[0]
        await monitor.poll_trades()
        if monitor.tasks:
            await asyncio.gather(*list(monitor.tasks))
    assert monitor.store.events("TRADE") == [first]
    assert monitor.store.events("COPY_REQUEST") == []


@pytest.mark.parametrize("status", [429, 503])
async def test_busy_response_is_raw_durable_then_backoff(monitor: Monitor, status: int) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"code": "rate_limited"}, headers={"Retry-After": "30"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        monitor.client = client
        with pytest.raises(httpx.HTTPStatusError):
            await monitor.request(module.DATA + "/v2/trades")
        events = monitor.store.events()
        assert [item["kind"] for item in events] == ["RAW", "RATE_LIMIT"]
        assert events[0]["payload"]["http_status"] == status
        assert monitor.backoff["data-api.polymarket.com"] > datetime.now(UTC)
        with pytest.raises(RuntimeError, match="PROVIDER_BACKOFF"):
            await monitor.request(module.DATA + "/v2/trades")
    assert calls == 1


async def test_malformed_json_keeps_raw_before_parse_failure(monitor: Monitor) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"{broken"))
    ) as client:
        monitor.client = client
        with pytest.raises(ValueError):
            await monitor.request(module.DATA + "/v2/trades")
    assert monitor.store.events("RAW")[0]["payload"]["body"] == "{broken"
    assert monitor.store.events("TRADE") == []


async def test_book_receipt_is_local_receive_not_upstream_timestamp(monitor: Monitor) -> None:
    source_clock = "1000"
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "asset_id": TOKEN,
                    "bids": [],
                    "asks": [],
                    "timestamp": source_clock,
                },
            )
        )
    ) as client:
        monitor.client = client
        before = datetime.now(UTC)
        snapshot, _ = await monitor.book(TOKEN)
        after = datetime.now(UTC)
    assert before <= snapshot.received_at <= after
    stored = monitor.store.events("BOOK")[0]
    assert stored["payload"]["source_timestamp"] == source_clock
    assert datetime.fromisoformat(stored["received_at"]) == snapshot.received_at


def install_transport(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    original = httpx.AsyncClient

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        return original(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", factory)
    monkeypatch.setattr(module.truststore, "inject_into_ssl", lambda: None)


async def test_profile_mismatch_stops_before_any_trade_or_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json={"proxyWallet": WALLET, "name": "DifferentTrader"})

    install_transport(monkeypatch, handler)
    database = tmp_path / "research.sqlite3"
    with pytest.raises(ValueError, match="TARGET_PROFILE_MISMATCH_STOPPED"):
        await module.run_monitor(database, tmp_path / "weather.sqlite3", 0.01, 3)
    assert paths == ["/public-profile"]
    assert read_events(database, "TRADE") == []
    assert read_events(database, "RUN") == []
    assert not database.with_suffix(".trader.lock").exists()


async def test_restart_marks_old_pending_request_missed_without_reexecution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "research.sqlite3"
    store = TraderStore(database)
    store.append(
        "COPY_REQUEST", {"due_at": "2026-10-20T00:00:00+00:00"}, datetime.now(UTC), "old-request"
    )
    store.close()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/public-profile":
            return httpx.Response(200, json={"proxyWallet": WALLET, "name": "HighTempTation"})
        assert request.url.path == "/v2/trades"
        return httpx.Response(200, json=page([]))

    install_transport(monkeypatch, handler)

    async def quiet(_: Monitor) -> None:
        return None

    async def no_stream(*args: Any) -> None:
        await args[2].wait()

    from premetar.research import trader_stream

    monkeypatch.setattr(Monitor, "discover", quiet)
    monkeypatch.setattr(Monitor, "lifecycle", quiet)
    monkeypatch.setattr(Monitor, "service_status", quiet)
    monkeypatch.setattr(trader_stream, "stream_market", no_stream)
    await module.run_monitor(database, tmp_path / "weather.sqlite3", 0.01, 3)
    await module.run_monitor(database, tmp_path / "weather.sqlite3", 0.01, 3)
    missed = read_events(database, "COPY_MISSED")
    assert len(missed) == 1
    assert missed[0]["payload"]["reason"] == "PROCESS_RESTART_INTERRUPTED"
    assert read_events(database, "SHADOW") == []
    assert len(read_events(database, "COPY_REQUEST")) == 1
