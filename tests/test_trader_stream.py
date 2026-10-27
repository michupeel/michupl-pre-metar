import asyncio
import json
from datetime import datetime
from typing import Any

import pytest

from premetar.research import trader_stream


class FakeSocket:
    def __init__(self, messages: list[str | bytes], stop: asyncio.Event) -> None:
        self.messages = messages
        self.stop = stop
        self.sent: list[str] = []

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def recv(self) -> str | bytes:
        if self.messages:
            return self.messages.pop(0)
        self.stop.set()
        await asyncio.sleep(0)
        return "PONG"

    async def __aenter__(self) -> "FakeSocket":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None


@pytest.mark.asyncio
async def test_raw_before_full_snapshot_no_wallet_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = asyncio.Event()
    socket = FakeSocket(
        [
            json.dumps(
                {
                    "event_type": "book",
                    "asset_id": "123",
                    "market": "0xabc",
                    "timestamp": "1234",
                    "bids": [{"price": "0.4", "size": "10"}],
                    "asks": [{"price": "0.6", "size": "20"}],
                }
            ),
            json.dumps({"event_type": "last_trade_price", "asset_id": "123", "price": "0.6"}),
            json.dumps({"event_type": "price_change", "market": "0xabc", "price_changes": []}),
        ],
        stop,
    )
    options: dict[str, Any] = {}

    def connect(url: str, **kwargs: Any) -> FakeSocket:
        assert url == trader_stream.MARKET_URL
        options.update(kwargs)
        return socket

    monkeypatch.setattr(trader_stream, "connect", connect)
    events: list[tuple[str, dict[str, Any], datetime]] = []

    def emit(kind: str, payload: dict[str, Any], received: datetime, key: str | None) -> None:
        assert received.tzinfo is not None
        events.append((kind, payload, received))

    await trader_stream.stream_market(lambda: ["123"], emit, stop)
    kinds = [event[0] for event in events]
    assert kinds.index("WS_RAW") < kinds.index("BOOK")
    assert kinds.count("BOOK") == 1
    assert kinds.count("WS_DELTA") == 1
    trade = next(event[1] for event in events if event[0] == "WS_TRADE")
    assert trade["wallet_attribution"] == "UNAVAILABLE"
    assert trade["order_role"] == "UNKNOWN"
    assert options["max_queue"] == 256
    assert options["max_size"] == 4 * 1024 * 1024
    assert json.loads(socket.sent[0]) == {"assets_ids": ["123"], "type": "market"}


@pytest.mark.asyncio
async def test_malformed_and_binary_preserved_without_depth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = asyncio.Event()
    socket = FakeSocket(
        ["not json", b"\xff", '{"event_type":"book","asset_id":"1","bids":[]}'], stop
    )
    monkeypatch.setattr(trader_stream, "connect", lambda *args, **kwargs: socket)
    events: list[tuple[str, dict[str, Any]]] = []
    await trader_stream.stream_market(
        lambda: ["1"], lambda kind, payload, received, key: events.append((kind, payload)), stop
    )
    assert sum(kind == "WS_RAW" for kind, payload in events) == 4
    assert not any(kind == "BOOK" for kind, payload in events)
    assert any("base64" in payload for kind, payload in events if kind == "WS_RAW")
    assert sum(payload.get("state") == "MALFORMED_MESSAGE" for kind, payload in events) == 3


@pytest.mark.asyncio
async def test_stop_while_idle_finishes_quickly() -> None:
    stop = asyncio.Event()
    task = asyncio.create_task(trader_stream.stream_market(lambda: [], lambda *args: None, stop))
    await asyncio.sleep(0.01)
    stop.set()
    await asyncio.wait_for(task, timeout=0.25)


@pytest.mark.asyncio
async def test_connection_error_isolated_and_stop_interrupts_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = asyncio.Event()
    events: list[dict[str, Any]] = []

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise ConnectionError("secret detail must not be recorded")

    monkeypatch.setattr(trader_stream, "connect", fail)

    def emit(kind: str, payload: dict[str, Any], received: datetime, key: str | None) -> None:
        events.append(payload)
        if payload.get("state") == "RECONNECTING":
            stop.set()

    await trader_stream.stream_market(lambda: ["1"], emit, stop)
    assert events[0]["error_class"] == "ConnectionError"
    assert "secret" not in json.dumps(events)


@pytest.mark.asyncio
async def test_shutdown_cancels_pending_handshake(monkeypatch: pytest.MonkeyPatch) -> None:
    stop = asyncio.Event()
    cancelled = asyncio.Event()

    class SlowHandshake:
        async def __aenter__(self) -> Any:
            try:
                await asyncio.sleep(60)
            finally:
                cancelled.set()

        async def __aexit__(self, *args: Any) -> None:
            return None

    monkeypatch.setattr(trader_stream, "connect", lambda *args, **kwargs: SlowHandshake())
    task = asyncio.create_task(trader_stream.stream_market(lambda: ["1"], lambda *args: None, stop))
    await asyncio.sleep(0.01)
    stop.set()
    await asyncio.wait_for(task, timeout=0.5)
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_token_changes_resubscribe_without_inventing_book(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = asyncio.Event()
    subscribed = ["1"]
    socket = FakeSocket(["PONG"], stop)
    monkeypatch.setattr(trader_stream, "connect", lambda *args, **kwargs: socket)
    events: list[str] = []

    def emit(kind: str, payload: dict[str, Any], received: datetime, key: str | None) -> None:
        events.append(kind)
        if payload.get("state") == "SUBSCRIBED":
            subscribed[:] = ["2"]

    await trader_stream.stream_market(lambda: subscribed, emit, stop)
    assert json.loads(socket.sent[1]) == {"assets_ids": ["1"], "operation": "unsubscribe"}
    assert json.loads(socket.sent[2]) == {"assets_ids": ["2"], "operation": "subscribe"}
    assert "BOOK" not in events
