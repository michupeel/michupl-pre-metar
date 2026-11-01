"""Raw-first public CLOB market stream, independent of wallet attribution."""

import asyncio
import base64
import contextlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from websockets.asyncio.client import ClientConnection, connect

MARKET_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
Emit = Callable[[str, dict[str, Any], datetime, str | None], None]


def _normalize_message(text: str, connection_id: str, received: datetime, emit: Emit) -> None:
    """Raw is already durable; incremental data never becomes full executable depth."""
    if text in {"PING", "PONG"}:
        return
    decoded: Any = json.loads(text)
    messages = decoded if isinstance(decoded, list) else [decoded]
    for message in messages:
        if not isinstance(message, dict):
            continue
        event = message.get("event_type")
        common = {
            "connection_id": connection_id,
            "source": "CLOB_MARKET_WS",
            "source_timestamp": message.get("timestamp"),
        }
        if event == "book":
            bids, asks = message.get("bids"), message.get("asks")
            if not isinstance(bids, list) or not isinstance(asks, list):
                raise ValueError("Incomplete full-book schema")
            if not all(
                isinstance(level, dict) and "price" in level and "size" in level
                for level in bids + asks
            ):
                raise ValueError("Invalid book level schema")
            token = message.get("asset_id")
            if not isinstance(token, str) or not token:
                raise ValueError("Missing book token")
            emit(
                "BOOK",
                {
                    **common,
                    "source": "WS_FULL_SNAPSHOT",
                    "token_id": token,
                    "market": message.get("market"),
                    "bids": bids,
                    "asks": asks,
                    "complete": True,
                    "hash": message.get("hash"),
                },
                received,
                None,
            )
        elif event == "last_trade_price":
            emit(
                "WS_TRADE",
                {
                    **common,
                    "token_id": message.get("asset_id"),
                    "market": message.get("market"),
                    "price": message.get("price"),
                    "size": message.get("size"),
                    "side": message.get("side"),
                    "wallet_attribution": "UNAVAILABLE",
                    "order_role": "UNKNOWN",
                    "transaction_hash": message.get("transaction_hash"),
                },
                received,
                None,
            )
        elif event == "price_change":
            emit(
                "WS_DELTA",
                {
                    **common,
                    "market": message.get("market"),
                    "price_changes": message.get("price_changes"),
                    "complete": False,
                },
                received,
                None,
            )


async def _ping(socket: ClientConnection, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=10)
        except TimeoutError:
            await socket.send("PING")


async def _pause(stop: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)


async def _stream_market(
    tokens: Callable[[], list[str]], emit: Emit, stop: asyncio.Event, stable_seconds: float = 0
) -> None:
    """Reconnect conservatively; bounded websockets queue applies backpressure without dropping."""
    backoff = 3.0
    run_start = time.monotonic()
    while not stop.is_set():
        selected = sorted(set(tokens()))
        if not selected:
            await _pause(stop, 1)
            continue
        connection_id = uuid4().hex
        connected_at = None
        ping_task: asyncio.Task[None] | None = None
        try:
            async with connect(
                MARKET_URL,
                max_queue=256,
                max_size=4 * 1024 * 1024,
                open_timeout=10,
                close_timeout=1,
                ping_interval=None,
            ) as socket:
                await socket.send(json.dumps({"assets_ids": selected, "type": "market"}))
                emit(
                    "STREAMHEALTH",
                    {
                        "state": "SUBSCRIBED",
                        "connection_id": connection_id,
                        "tokens": selected,
                        "monotonic_elapsed_seconds": time.monotonic() - run_start,
                    },
                    datetime.now(UTC),
                    None,
                )
                ping_task = asyncio.create_task(_ping(socket, stop))
                connected_at = time.monotonic()
                if stable_seconds == 0:
                    backoff = 3.0
                while not stop.is_set():
                    latest = sorted(set(tokens()))
                    if latest != selected:
                        removed, added = (
                            sorted(set(selected) - set(latest)),
                            sorted(set(latest) - set(selected)),
                        )
                        if removed:
                            await socket.send(
                                json.dumps({"assets_ids": removed, "operation": "unsubscribe"})
                            )
                        if added:
                            await socket.send(
                                json.dumps({"assets_ids": added, "operation": "subscribe"})
                            )
                        selected = latest
                        emit(
                            "STREAMHEALTH",
                            {
                                "state": "SUBSCRIPTIONS_CHANGED",
                                "connection_id": connection_id,
                                "tokens": selected,
                            },
                            datetime.now(UTC),
                            None,
                        )
                    if ping_task.done():
                        ping_task.result()
                    try:
                        message = await asyncio.wait_for(socket.recv(), timeout=0.5)
                    except TimeoutError:
                        continue
                    received = datetime.now(UTC)
                    raw: dict[str, Any] = {
                        "connection_id": connection_id,
                        "source": MARKET_URL,
                        "monotonic_elapsed_seconds": time.monotonic() - run_start,
                    }
                    if isinstance(message, bytes):
                        raw["base64"] = base64.b64encode(message).decode("ascii")
                    else:
                        raw["text"] = message
                    emit("WS_RAW", raw, received, None)
                    try:
                        text = message.decode("utf-8") if isinstance(message, bytes) else message
                        _normalize_message(text, connection_id, received, emit)
                    except (ValueError, UnicodeError) as error:
                        emit(
                            "STREAMHEALTH",
                            {
                                "state": "MALFORMED_MESSAGE",
                                "connection_id": connection_id,
                                "error_class": type(error).__name__,
                            },
                            received,
                            None,
                        )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            session_seconds = time.monotonic() - connected_at if connected_at is not None else None
            if stable_seconds and session_seconds is not None and session_seconds >= stable_seconds:
                backoff = 3.0
            emit(
                "STREAMHEALTH",
                {
                    "state": "RECONNECTING",
                    "connection_id": connection_id,
                    "error_class": type(error).__name__,
                    "backoff_seconds": backoff,
                    "session_seconds": session_seconds,
                    "received_close_code": getattr(getattr(error, "rcvd", None), "code", None),
                    "sent_close_code": getattr(getattr(error, "sent", None), "code", None),
                },
                datetime.now(UTC),
                None,
            )
            await _pause(stop, backoff)
            backoff = min(60, backoff * 2)
        finally:
            if ping_task is not None:
                ping_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await ping_task


async def stream_market(
    tokens: Callable[[], list[str]], emit: Emit, stop: asyncio.Event, *, stable_seconds: float = 0
) -> None:
    """Interrupt even a pending handshake when shutdown is requested."""
    worker = asyncio.create_task(_stream_market(tokens, emit, stop, stable_seconds))
    stopping = asyncio.create_task(stop.wait())
    try:
        done, _ = await asyncio.wait({worker, stopping}, return_when=asyncio.FIRST_COMPLETED)
        if worker in done:
            worker.result()
    finally:
        stopping.cancel()
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stopping
        with contextlib.suppress(asyncio.CancelledError, TimeoutError):
            await asyncio.wait_for(worker, timeout=1.5)
        emit("STREAMHEALTH", {"state": "STOPPED"}, datetime.now(UTC), None)
