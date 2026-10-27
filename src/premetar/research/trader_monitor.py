"""Independent public-data collector and displayed-liquidity shadow simulation.

No account authentication, signing, private keys or order submission exists here.
HTTP POST is used ONLY on the public read-only /books batch endpoint.
"""

import asyncio
import hashlib
import json
import logging
import os
import time
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import truststore

from premetar.continuous.locking import acquire
from premetar.research.trader_execution import (
    BookSnapshot,
    FeePolicy,
    Level,
    simulate_buy,
    simulate_sell,
)
from premetar.research.trader_normalizer import WALLET, normalize_trade, parse_page
from premetar.research.trader_portfolio import (
    ExitRecord,
    ShadowLot,
    follow_exit_plans,
    remaining_quantity,
    settlement_plans,
    take_profit_plans,
)
from premetar.research.trader_store import TraderStore
from premetar.research.trader_weather import weather_context

DATA = "https://data-api.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DELAYS = (0, 1, 3, 5, 10, 30)
NOTIONALS = (10, 25, 50, 100)
STRATEGIES = ("COPY_HOLD", "COPY_FOLLOW", "COPY_TAKE_PROFIT")


def now() -> datetime:
    return datetime.now(UTC)


def json_safe(payload: Any) -> Any:
    return json.loads(json.dumps(payload, default=str))


def verified_fee(market: dict[str, Any]) -> FeePolicy | None:
    """Explicit current zero schedule only; never infer fees from legacy base_fee."""
    schedule = market.get("feeSchedule")
    if isinstance(schedule, dict) and schedule.get("rate") is not None:
        if Decimal(str(schedule["rate"])) == 0 and market.get("feeType") == "zero_fees":
            return FeePolicy(
                Decimal(0), 1, "Captured Gamma feeType=zero_fees and feeSchedule.rate=0", False
            )
    return None


def open_market(market: dict[str, Any]) -> bool | None:
    if market.get("closed") is True or market.get("acceptingOrders") is False:
        return False
    if (
        market.get("active") is True
        and market.get("closed") is False
        and market.get("acceptingOrders") is True
    ):
        return True
    return None


def market_tokens(market: dict[str, Any]) -> list[str]:
    """Current API version selects token field; do not silently mix token identities."""
    field = "positionIds" if market.get("version") == "v2" else "clobTokenIds"
    values = market.get(field) or []
    parsed = json.loads(values) if isinstance(values, str) else values
    if not isinstance(parsed, list) or any(not str(value).isdigit() for value in parsed):
        raise ValueError("INVALID_MARKET_TOKENS")
    return [str(value) for value in parsed]


def parse_book(payload: Any, token: str, received: datetime) -> BookSnapshot:
    if not isinstance(payload, dict) or str(payload.get("asset_id")) != token:
        raise ValueError("WRONG_BOOK_TOKEN")
    if not isinstance(payload.get("asks"), list) or not isinstance(payload.get("bids"), list):
        raise ValueError("INCOMPLETE_BOOK")
    sides = [
        tuple(Level(Decimal(str(v["price"])), Decimal(str(v["size"]))) for v in payload[side])
        for side in ("bids", "asks")
    ]
    return BookSnapshot(token, received, sides[0], sides[1])


def deplete_bids(book: BookSnapshot, quantity: Decimal) -> BookSnapshot:
    """Do not spend the same visible bid twice inside one hypothetical cohort."""
    remaining = quantity
    levels = []
    for level in sorted(book.bids, key=lambda v: v.price, reverse=True):
        used = min(remaining, level.size)
        remaining -= used
        if level.size > used:
            levels.append(Level(level.price, level.size - used))
    return BookSnapshot(book.token_id, book.received_at, tuple(levels), book.asks, book.complete)


class Monitor:
    def __init__(
        self, store: TraderStore, client: httpx.AsyncClient, weather: Path, poll: float
    ) -> None:
        self.store, self.client, self.weather, self.poll = store, client, weather, poll
        self.run_id = uuid4().hex
        self.stop = asyncio.Event()
        self.requests = asyncio.Semaphore(4)
        self.copy_slots = asyncio.Semaphore(8)
        self.tokens: dict[str, str] = {}
        self.held_conditions: dict[str, str] = {}
        self.markets: dict[str, dict[str, Any]] = {}
        self.tasks: set[asyncio.Task[None]] = set()
        self.last_poll: datetime | None = None
        self.last_activity_poll: datetime | None = None
        self.started = now()
        self.backoff: dict[str, datetime] = {}
        self.request_count = 0
        self.trade_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=128)
        for event in self.store.events("SHADOW", 100000):
            row = event["payload"]
            if row.get("condition_id"):
                self.held_conditions[row["token_id"]] = row["condition_id"]

    def emit(
        self, kind: str, payload: dict[str, Any], received: datetime, key: str | None = None
    ) -> bool:
        if kind in {"ERROR", "COPY_MISSED", "RATE_LIMIT", "RUN", "STOP"}:
            logging.getLogger("premetar.trader").info(
                "%s %s", kind, json.dumps(json_safe(payload), sort_keys=True)
            )
        return self.store.append(kind, json_safe(payload), received, key)

    async def request(
        self, url: str, params: dict[str, Any] | None = None, body: Any = None
    ) -> tuple[Any, datetime]:
        if body is not None and url != CLOB + "/books":
            raise ValueError("ONLY_PUBLIC_READ_ONLY_BATCH_POST_ALLOWED")
        origin = httpx.URL(url).host
        until = self.backoff.get(origin)
        if until and until > now():
            raise RuntimeError("PROVIDER_BACKOFF")
        async with self.requests:
            start, tick = now(), time.perf_counter_ns()
            response = await (
                self.client.get(url, params=params)
                if body is None
                else self.client.post(url, json=body)
            )
            received = now()
            self.request_count += 1
            # Raw body durable before JSON decoding or business logic.
            self.emit(
                "RAW",
                {
                    "url": url,
                    "params": params,
                    "body": response.text,
                    "http_status": response.status_code,
                    "request_start": start.isoformat(),
                    "request_end": received.isoformat(),
                    "monotonic_duration_ns": time.perf_counter_ns() - tick,
                    "sha256": hashlib.sha256(response.content).hexdigest(),
                    "run_id": self.run_id,
                    "response_date": response.headers.get("Date"),
                    "request_body": body,
                },
                received,
            )
            if response.status_code in (429, 503):
                try:
                    delay = max(1.0, float(response.headers.get("Retry-After", "30")))
                except ValueError:
                    delay = 60.0
                self.backoff[origin] = received + timedelta(seconds=delay)
                self.emit(
                    "RATE_LIMIT",
                    {
                        "origin": origin,
                        "status": response.status_code,
                        "retry_at": self.backoff[origin].isoformat(),
                    },
                    received,
                )
            response.raise_for_status()
            if len(response.content) > 8_000_000:
                raise ValueError("PAYLOAD_TOO_LARGE")
            return response.json(), received

    async def pause(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self.stop.wait(), max(0.001, seconds))
        except TimeoutError:
            pass

    async def loop(self, name: str, function: Any, interval: float) -> None:
        failures = 0
        while not self.stop.is_set():
            tick = time.monotonic()
            try:
                await function()
                failures = 0
            except Exception as exc:
                failures += 1
                self.emit(
                    "ERROR",
                    {"operation": name, "error_class": type(exc).__name__, "consecutive": failures},
                    now(),
                )
            await self.pause(
                max(interval, min(60, 2 ** min(failures, 6))) - (time.monotonic() - tick)
            )

    async def get_market(self, condition: str, force: bool = False) -> dict[str, Any]:
        if condition in self.markets and not force:
            return self.markets[condition]
        payload, received = await self.request(
            GAMMA + "/markets", {"condition_ids": condition, "closed": "any"}
        )
        if (
            not isinstance(payload, list)
            or len(payload) != 1
            or payload[0].get("conditionId") != condition
        ):
            raise ValueError("MARKET_IDENTITY_UNVERIFIED")
        market: dict[str, Any] = payload[0]
        market["_captured_at"] = received.isoformat()
        self.markets[condition] = market
        self.emit("MARKET", market, received)
        tokens = market_tokens(market)
        for token in json.loads(tokens) if isinstance(tokens, str) else tokens:
            if open_market(market) is True and len(self.tokens) < 256:
                self.tokens[str(token)] = condition
        return market

    async def discover(self) -> None:
        # Prioritize target's actual recent instruments before general weather universe.
        # Backfill ingestion order is not source recency. Drop expired subscriptions
        # and rebuild from current open metadata each discovery cycle.
        recent = [
            json.loads(row[0])
            for row in self.store.connection.execute(
                "SELECT payload FROM events WHERE kind='TRADE' ORDER BY json_extract(payload,'$.source_trade_timestamp') DESC LIMIT 300"
            )
        ]
        self.tokens.clear()
        conditions = list(dict.fromkeys(event["condition_id"] for event in recent))[:60]
        for condition in conditions:
            try:
                await self.get_market(condition, force=True)
            except (ValueError, httpx.HTTPError, RuntimeError):
                continue
            await self.pause(0.1)
        # Tag is verified via /tags/slug/weather. Filter daily-temperature contracts.
        tag, _ = await self.request(GAMMA + "/tags/slug/weather")
        tag_id = tag["id"]
        pages = 0
        for offset in range(0, 1000, 100):
            rows, received = await self.request(
                GAMMA + "/markets",
                {"tag_id": tag_id, "closed": "false", "limit": 100, "offset": offset},
            )
            if not isinstance(rows, list):
                raise ValueError("INVALID_MARKET_PAGE")
            pages += 1
            for market in rows:
                if not str(market.get("slug", "")).startswith(
                    ("highest-temperature-in-", "lowest-temperature-in-")
                ):
                    continue
                condition = market.get("conditionId")
                if not condition:
                    continue
                market["_captured_at"] = received.isoformat()
                self.markets[condition] = market
                self.emit("MARKET", market, received)
                tokens = market_tokens(market)
                for token in json.loads(tokens) if isinstance(tokens, str) else tokens:
                    if open_market(market) is True and len(self.tokens) < 256:
                        self.tokens[str(token)] = condition
            if len(rows) < 100:
                break
            await self.pause(0.2)
        self.emit(
            "DISCOVERY",
            {
                "pages": pages,
                "tokens": len(self.tokens),
                "token_limit": 256,
                "coverage": "BOUNDED_RECORDED_UNIVERSE_NOT_ALL_MARKETS",
            },
            now(),
        )

    async def poll_trades(self) -> None:
        previous = self.last_poll
        start = (
            int((previous - timedelta(minutes=10)).timestamp())
            if previous
            else int((now() - timedelta(days=7)).timestamp())
        )
        params: dict[str, Any] = {
            "user": WALLET,
            "taker_only": "false",
            "limit": 100,
            "start": start,
        }
        cursor: str | None = None
        seen_cursors: set[str] = set()
        first_receipt: datetime | None = None
        for _page in range(20):
            request = {**params, **({"cursor": cursor} if cursor else {})}
            payload, received = await self.request(DATA + "/v2/trades", request)
            first_receipt = first_receipt or received
            rows, cursor = parse_page(payload)
            evidence = (
                "BOOTSTRAP_HISTORICAL"
                if previous is None
                else "GAP_CENSORED"
                if (received - previous).total_seconds() > max(30, self.poll * 5)
                else "PROSPECTIVE_POLL"
            )
            for row in reversed(rows):
                await self.record_trade(row, received, evidence, previous, "TRADES_V2")
            if cursor is None:
                self.last_poll = first_receipt
                return
            if cursor in seen_cursors:
                raise ValueError("CURSOR_LOOP")
            seen_cursors.add(cursor)
            await self.pause(0.1)
        self.emit(
            "COVERAGE_GAP", {"reason": "TRADE_PAGE_BUDGET", "start": start, "pages": 20}, now()
        )
        # Do not falsely certify complete coverage after truncation.
        self.last_poll = None

    async def record_trade(
        self,
        row: dict[str, Any],
        received: datetime,
        evidence: str,
        previous: datetime | None,
        endpoint: str,
    ) -> None:
        try:
            trade = normalize_trade(row, received, evidence)
        except ValueError as exc:
            self.emit("NORMALIZATION_REJECTION", {"reason": str(exc), "row": row}, received)
            return
        trade.update(
            last_successful_poll=previous.isoformat() if previous else None,
            run_id=self.run_id,
            detection_endpoint=endpoint,
        )
        self.emit(
            "ENDPOINT_RECEIPT",
            {
                "trade_id": trade["trade_id"],
                "endpoint": endpoint,
                "source_trade_timestamp": trade["source_trade_timestamp"],
                "first_endpoint_receipt": received.isoformat(),
                "evidence_class": trade["evidence_class"],
            },
            received,
            f"{endpoint}:{trade['trade_id']}",
        )
        # Feeds expose no common log ID and may partition/round the same execution
        # differently. Preserve rows, but never copy one transaction/token/side twice.
        group = hashlib.sha256(
            json.dumps(
                [WALLET, trade["transaction_hash"].lower(), trade["token_id"], trade["side"]]
            ).encode()
        ).hexdigest()
        first_group = self.emit(
            "EXECUTION_GROUP",
            {
                "trade_id": trade["trade_id"],
                "evidence_class": trade["evidence_class"],
                "group_key": group,
            },
            received,
            group,
        )
        new_row = self.emit("TRADE", trade, received, trade["trade_id"])
        if new_row and trade["evidence_class"] == "PROSPECTIVE_POLL":
            if first_group:
                await self.trade_queue.put(trade)
            else:
                self.emit(
                    "COPY_SUPPRESSED",
                    {
                        "trade_id": trade["trade_id"],
                        "group_key": group,
                        "reason": "SAME_TRANSACTION_TOKEN_SIDE_ALREADY_OBSERVED",
                    },
                    received,
                    trade["trade_id"],
                )

    async def poll_activity(self) -> None:
        """Race the other documented wallet feed; never infer wallet from market WS."""
        previous = self.last_activity_poll
        start = (
            int((previous - timedelta(hours=1)).timestamp())
            if previous
            else int((now() - timedelta(days=1)).timestamp())
        )
        params: dict[str, Any] = {
            "user": WALLET,
            "limit": 1000,
            "start": start,
            "sort_by": "TIMESTAMP",
            "sort_direction": "DESC",
        }
        cursor: str | None = None
        cursors: set[str] = set()
        first_receipt: datetime | None = None
        for _page in range(5):
            payload, received = await self.request(
                DATA + "/v2/activity", {**params, **({"cursor": cursor} if cursor else {})}
            )
            first_receipt = first_receipt or received
            rows, cursor = parse_page(payload)
            evidence = (
                "BOOTSTRAP_HISTORICAL"
                if previous is None
                else "GAP_CENSORED"
                if (received - previous).total_seconds() > max(30, self.poll * 5)
                else "PROSPECTIVE_POLL"
            )
            for row in reversed(rows):
                if str(row.get("proxy_wallet", "")).lower() != WALLET:
                    self.emit(
                        "NORMALIZATION_REJECTION",
                        {"reason": "WRONG_OR_MISSING_WALLET", "source": "ACTIVITY_V2"},
                        received,
                    )
                    continue
                digest = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
                self.emit(
                    "ACTIVITY",
                    {
                        "source_record": row,
                        "evidence_class": evidence,
                        "first_collector_receipt_utc": received.isoformat(),
                        "source_publication_timestamp": None,
                    },
                    received,
                    digest,
                )
                if row.get("type") == "TRADE":
                    await self.record_trade(row, received, evidence, previous, "ACTIVITY_V2")
            if cursor is None:
                self.last_activity_poll = first_receipt
                return
            if cursor in cursors:
                raise ValueError("ACTIVITY_CURSOR_LOOP")
            cursors.add(cursor)
            await self.pause(0.1)
        self.emit("COVERAGE_GAP", {"reason": "ACTIVITY_PAGE_BUDGET", "pages": 5}, now())
        self.last_activity_poll = None

    def spawn(self, coroutine: Any) -> None:
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        task.add_done_callback(self.task_completed)

    def task_completed(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled() and (exc := task.exception()) is not None:
            self.emit(
                "ERROR", {"operation": "TRADE_TASK", "error_class": type(exc).__name__}, now()
            )

    async def on_trade(self, trade: dict[str, Any]) -> None:
        detected = datetime.fromisoformat(trade["first_collector_receipt_utc"])
        context = await asyncio.to_thread(weather_context, self.weather, trade, detected)
        self.emit("WEATHER", context, now(), trade["trade_id"])
        if trade["evidence_class"] != "PROSPECTIVE_POLL":
            return
        # Immutable requests precede execution. A missed deadline is never backdated.
        for delay in DELAYS:
            key = f"{trade['trade_id']}:{delay}"
            payload = {
                "trade": trade,
                "delay_seconds": delay,
                "due_at": (detected + timedelta(seconds=delay)).isoformat(),
            }
            if self.emit("COPY_REQUEST", payload, now(), key):
                if len(self.tasks) >= 240:
                    self.emit(
                        "COPY_MISSED",
                        {"request_key": key, "reason": "BOUNDED_JOB_CAPACITY"},
                        now(),
                        key,
                    )
                else:
                    self.spawn(self.copy_trade(payload, key))

    async def trade_worker(self) -> None:
        while not self.stop.is_set():
            trade = await self.trade_queue.get()
            try:
                await self.on_trade(trade)
            except Exception as exc:
                self.emit(
                    "ERROR",
                    {
                        "operation": "TRADE_CONTEXT",
                        "trade_id": trade["trade_id"],
                        "error_class": type(exc).__name__,
                    },
                    now(),
                )
            finally:
                self.trade_queue.task_done()

    async def book(self, token: str) -> tuple[BookSnapshot, dict[str, Any]]:
        payload, received = await self.request(CLOB + "/book", {"token_id": token})
        parsed = parse_book(payload, token, received)
        self.emit(
            "BOOK",
            {
                "token_id": token,
                "bids": payload["bids"],
                "asks": payload["asks"],
                "complete": True,
                "source": "REST_POST_DEADLINE",
                "source_timestamp": payload.get("timestamp"),
            },
            received,
        )
        return parsed, payload

    async def copy_trade(self, request: dict[str, Any], key: str) -> None:
        trade, delay = request["trade"], request["delay_seconds"]
        due = datetime.fromisoformat(request["due_at"])
        await self.pause((due - now()).total_seconds())
        if self.stop.is_set():
            return
        async with self.copy_slots:
            if (now() - due).total_seconds() > 5:
                self.emit(
                    "COPY_MISSED", {"request_key": key, "reason": "DEADLINE_MISSED"}, now(), key
                )
                return
            try:
                market = await self.get_market(trade["condition_id"], force=True)
                if trade["token_id"] not in market_tokens(market):
                    raise ValueError("TOKEN_NOT_IN_VERIFIED_MARKET")
                snapshot, raw = await self.book(trade["token_id"])
                if trade["side"] == "SELL":
                    await self.follow_sell(trade, delay, snapshot, market)
                    return
                best_bid = max((level.price for level in snapshot.bids), default=None)
                best_ask = min((level.price for level in snapshot.asks), default=None)
                for notional in NOTIONALS:
                    result = simulate_buy(
                        snapshot,
                        Decimal(notional),
                        detected_at=datetime.fromisoformat(trade["first_collector_receipt_utc"]),
                        due_at=due,
                        decision_at=now(),
                        fee_policy=verified_fee(market),
                        market_open=open_market(market),
                    )
                    for strategy in STRATEGIES:
                        lot_id = f"{key}:{notional}:{strategy}"
                        record = {
                            **asdict(result),
                            "lot_id": lot_id,
                            "trade_id": trade["trade_id"],
                            "token_id": trade["token_id"],
                            "condition_id": trade["condition_id"],
                            "strategy": strategy,
                            "delay_seconds": delay,
                            "notional": notional,
                            "side": "BUY",
                            "original_price": trade["price"],
                            "target_buy_quantity": trade["size"],
                            "due_at": due.isoformat(),
                            "created_at": now().isoformat(),
                            "target_trade_detected_at": trade["first_collector_receipt_utc"],
                            "detection_endpoint": trade.get("detection_endpoint", "TRADES_V2"),
                            "book_hash": raw.get("hash"),
                            "market_captured_at": market["_captured_at"],
                            "best_bid": best_bid,
                            "best_ask": best_ask,
                            "spread": best_ask - best_bid
                            if best_ask is not None and best_bid is not None
                            else None,
                            "displayed_depth_impact": result.vwap - best_ask
                            if result.vwap is not None and best_ask is not None
                            else None,
                            "actual_detection_to_book_seconds": (
                                snapshot.received_at
                                - datetime.fromisoformat(trade["first_collector_receipt_utc"])
                            ).total_seconds(),
                            "fee_schedule": market.get("feeSchedule"),
                            "fee_status": "VERIFIED_ZERO"
                            if verified_fee(market) is not None
                            else "UNKNOWN",
                            "price_difference": str(result.vwap - Decimal(trade["price"]))
                            if result.vwap is not None
                            else None,
                            "book_assumption": "DISPLAYED_DEPTH_AT_ACTUAL_POST_DEADLINE_RECEIPT_NOT_GUARANTEED_FILL",
                            "rules_status": "CAPTURED_RAW_NOT_INDEPENDENTLY_VERIFIED_FOR_IMPOSSIBILITY",
                        }
                        self.emit("SHADOW", record, now(), lot_id)
                        self.held_conditions[trade["token_id"]] = trade["condition_id"]
                self.emit("COPY_COMPLETE", {"request_key": key}, now(), key)
            except Exception as exc:
                self.emit(
                    "COPY_MISSED", {"request_key": key, "reason": type(exc).__name__}, now(), key
                )

    def portfolio(self) -> tuple[list[ShadowLot], list[ExitRecord]]:
        lots = []
        for event in self.store.events("SHADOW", 100000):
            row = event["payload"]
            if Decimal(str(row.get("quantity", 0))) <= 0:
                continue
            lots.append(
                ShadowLot(
                    row["lot_id"],
                    row["token_id"],
                    row["strategy"],
                    int(row["delay_seconds"]),
                    Decimal(str(row["notional"])),
                    Decimal(str(row["quantity"])),
                    Decimal(row["target_buy_quantity"]),
                    Decimal(str(row["gross_value"])),
                    Decimal(str(row["fee"])) if row["fee"] is not None else None,
                    Decimal(str(row["net_value"])) if row["net_value"] is not None else None,
                    Decimal(str(row["vwap"])),
                )
            )
        exits = [
            ExitRecord(
                r["payload"]["lot_id"],
                Decimal(str(r["payload"]["quantity"])),
                Decimal(str(r["payload"]["gross_value"])),
                Decimal(str(r["payload"]["fee"])) if r["payload"]["fee"] is not None else None,
                Decimal(str(r["payload"]["net_value"]))
                if r["payload"]["net_value"] is not None
                else None,
                r["payload"]["kind"],
            )
            for r in self.store.events("EXIT", 100000)
        ]
        return lots, exits

    async def follow_sell(
        self, trade: dict[str, Any], delay: int, snapshot: BookSnapshot, market: dict[str, Any]
    ) -> None:
        lots, exits = self.portfolio()
        # Source BUY detection precedes SELL detection; delayed copy fills may occur between them.
        detected = datetime.fromisoformat(trade["first_collector_receipt_utc"])
        prior_lots = {
            event["payload"]["lot_id"]
            for event in self.store.events("SHADOW", 100000)
            if datetime.fromisoformat(
                event["payload"].get(
                    "target_trade_detected_at",
                    event["payload"].get("created_at", event["received_at"]),
                )
            )
            <= detected
        }
        plans = follow_exit_plans(
            [lot for lot in lots if lot.delay_seconds == delay and lot.lot_id in prior_lots],
            exits,
            token_id=trade["token_id"],
            target_sell_quantity=Decimal(trade["size"]),
        )
        books: dict[Decimal, BookSnapshot] = {}
        for plan in plans:
            cohort = next(lot.notional for lot in lots if lot.lot_id == plan.lot_id)
            available = books.get(cohort, snapshot)
            result = simulate_sell(
                available,
                plan.quantity,
                holdings=plan.quantity,
                detected_at=datetime.fromisoformat(trade["first_collector_receipt_utc"]),
                due_at=datetime.fromisoformat(trade["first_collector_receipt_utc"])
                + timedelta(seconds=delay),
                decision_at=now(),
                fee_policy=verified_fee(market),
                market_open=open_market(market),
            )
            self.emit(
                "EXIT",
                {
                    **asdict(result),
                    "lot_id": plan.lot_id,
                    "kind": "COPY_FOLLOW",
                    "source_trade_id": trade["trade_id"],
                },
                now(),
                f"follow:{trade['trade_id']}:{plan.lot_id}",
            )
            books[cohort] = deplete_bids(available, result.quantity)
        self.emit(
            "COPY_COMPLETE",
            {"trade_id": trade["trade_id"], "delay_seconds": delay},
            now(),
            f"{trade['trade_id']}:{delay}",
        )

    async def lifecycle(self) -> None:
        lots, exits = self.portfolio()
        active = {lot.token_id for lot in lots if remaining_quantity(lot, exits) > 0}
        for token in active:
            condition = self.held_conditions.get(token) or self.tokens.get(token)
            if condition is None:
                continue
            market = await self.get_market(condition, force=True)
            if market.get("closed") is True and market.get("umaResolutionStatus") == "resolved":
                tokens, prices = market_tokens(market), market.get("outcomePrices")
                prices = json.loads(prices) if isinstance(prices, str) else prices
                if isinstance(tokens, list) and isinstance(prices, list) and token in tokens:
                    payout = Decimal(str(prices[tokens.index(token)]))
                    lots, exits = self.portfolio()
                    for plan in settlement_plans(
                        lots, exits, token_id=token, payout=payout, verified_resolution=True
                    ):
                        self.emit(
                            "EXIT",
                            {
                                "lot_id": plan.lot_id,
                                "quantity": str(plan.quantity),
                                "gross_value": str(plan.quantity * payout),
                                "fee": "0",
                                "net_value": str(plan.quantity * payout),
                                "kind": "SETTLEMENT",
                                "market_captured_at": market["_captured_at"],
                            },
                            now(),
                            f"settled:{plan.lot_id}",
                        )
                continue
            if not any(
                lot.token_id == token and lot.strategy == "COPY_TAKE_PROFIT" for lot in lots
            ):
                continue
            snapshot, _ = await self.book(token)
            lots, exits = self.portfolio()
            best = max((v.price for v in snapshot.bids), default=Decimal(0))
            books: dict[tuple[int, Decimal], BookSnapshot] = {}
            for plan in take_profit_plans(lots, exits, token_id=token, best_bid=best):
                assert plan.limit_price is not None
                lot = next(item for item in lots if item.lot_id == plan.lot_id)
                cohort = (lot.delay_seconds, lot.notional)
                available = books.get(cohort, snapshot)
                eligible = BookSnapshot(
                    token,
                    snapshot.received_at,
                    tuple(v for v in available.bids if v.price >= plan.limit_price),
                    snapshot.asks,
                )
                result = simulate_sell(
                    eligible,
                    plan.quantity,
                    holdings=plan.quantity,
                    detected_at=self.started,
                    due_at=self.started,
                    decision_at=now(),
                    fee_policy=verified_fee(market),
                    market_open=open_market(market),
                )
                self.emit(
                    "EXIT",
                    {**asdict(result), "lot_id": plan.lot_id, "kind": "COPY_TAKE_PROFIT"},
                    now(),
                )
                books[cohort] = deplete_bids(available, result.quantity)
            await self.pause(0.1)

    async def health(self) -> None:
        self.emit(
            "HEALTH",
            {
                "run_id": self.run_id,
                "pid": os.getpid(),
                "state": "RUNNING",
                "last_trade_poll": self.last_poll.isoformat() if self.last_poll else None,
                "last_activity_poll": self.last_activity_poll.isoformat()
                if self.last_activity_poll
                else None,
                "uptime_seconds": (now() - self.started).total_seconds(),
                "tokens": len(self.tokens),
                "requests": self.request_count,
                "pending_jobs": len(self.tasks),
                "trade_queue_depth": self.trade_queue.qsize(),
                "clock_synchronization": "UNKNOWN_NOT_CHANGED",
                "database_bytes": self.store.path.stat().st_size,
                "storage_warning": self.store.path.stat().st_size > 25_000_000_000,
            },
            now(),
        )

    async def check_stop(self) -> None:
        path = self.store.path.with_suffix(".trader.stop")
        if await asyncio.to_thread(path.exists):
            await asyncio.to_thread(path.unlink, missing_ok=True)
            self.stop.set()

    async def service_status(self) -> None:
        payload, received = await self.request(DATA + "/v2/status")
        self.emit("DATA_SERVICE_STATUS", payload, received)
        # A positive exact-row match supports API-attributed taker. Absence proves nothing.
        payload, received = await self.request(
            DATA + "/v2/trades", {"user": WALLET, "taker_only": "true", "limit": 100}
        )
        rows, _ = parse_page(payload)
        for row in rows:
            trade = normalize_trade(row, received, "ROLE_PROBE_ONLY")
            self.emit(
                "ROLE_EVIDENCE",
                {
                    "trade_id": trade["trade_id"],
                    "role": "API_ATTRIBUTED_TAKER",
                    "evidence": "Exact row present in documented taker_only=true feed; not chain verification",
                    "transaction_hash": trade["transaction_hash"],
                },
                received,
                trade["trade_id"],
            )

    async def historical_page(self) -> None:
        """Bounded resumable full-history discovery, never a live copy signal."""
        previous = self.store.events("BACKFILL_STATE", 1)
        state: dict[str, Any] = (
            previous[-1]["payload"]
            if previous
            else {
                "cursor": None,
                "end": int(self.started.timestamp()),
                "pages": 0,
                "complete": False,
            }
        )
        if state["complete"] or state["pages"] >= 200:
            return
        params: dict[str, Any] = {
            "user": WALLET,
            "taker_only": "false",
            "limit": 1000,
            "start": 1,
            "end": state["end"],
        }
        if state["cursor"]:
            params["cursor"] = state["cursor"]
        payload, received = await self.request(DATA + "/v2/trades", params)
        rows, cursor = parse_page(payload)
        if cursor is not None and cursor == state["cursor"]:
            raise ValueError("BACKFILL_CURSOR_LOOP")
        for row in rows:
            try:
                trade = normalize_trade(row, received, "HISTORICAL_BACKFILL")
            except ValueError as exc:
                self.emit(
                    "NORMALIZATION_REJECTION", {"reason": str(exc), "source": "BACKFILL"}, received
                )
                continue
            self.emit("TRADE", trade, received, trade["trade_id"])
        self.emit(
            "BACKFILL_STATE",
            {
                "cursor": cursor,
                "end": state["end"],
                "pages": state["pages"] + 1,
                "complete": cursor is None,
                "page_rows": len(rows),
                "page_limit": 200,
            },
            received,
        )


async def run_monitor(
    database: Path,
    weather_database: Path,
    duration: float | None = None,
    poll_interval: float = 3.0,
) -> None:
    if await asyncio.to_thread(database.resolve) == await asyncio.to_thread(
        weather_database.resolve
    ):
        raise ValueError("Research storage must be separate from weather DB")
    if poll_interval < 2 or (duration is not None and duration <= 0):
        raise ValueError("Invalid monitoring bounds")
    database.parent.mkdir(parents=True, exist_ok=True)
    log_path = database.parent / "trader-monitor.log"
    logger = logging.getLogger("premetar.trader")
    handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    lock_path = database.with_suffix(".trader.lock")
    lock = acquire(lock_path, "EXP0011-" + uuid4().hex, recover=True)
    store = TraderStore(database)
    truststore.inject_into_ssl()
    try:
        async with httpx.AsyncClient(
            timeout=12, follow_redirects=False, limits=httpx.Limits(max_connections=8)
        ) as client:
            monitor = Monitor(store, client, weather_database, poll_interval)
            profile, received = await monitor.request(
                GAMMA + "/public-profile", {"address": WALLET}
            )
            if (
                str(profile.get("proxyWallet", "")).lower() != WALLET
                or profile.get("name") != "HighTempTation"
            ):
                raise ValueError("TARGET_PROFILE_MISMATCH_STOPPED")
            monitor.emit("PROFILE_VERIFIED", profile, received)
            monitor.emit(
                "RUN",
                {
                    "run_id": monitor.run_id,
                    "pid": os.getpid(),
                    "started_at": monitor.started.isoformat(),
                    "protocol": "EXP0011-v1",
                    "detector_version": "DUAL_PUBLIC_FEEDS-v2",
                    "wallet": WALLET,
                    "poll_interval": poll_interval,
                    "weather_database": str(weather_database),
                    "delays": DELAYS,
                    "notionals": NOTIONALS,
                    "strategies": STRATEGIES,
                    "code_sha256": {
                        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in Path(__file__).parent.glob("trader_*.py")
                    },
                },
                now(),
            )
            # Restart never executes old due jobs with fresh books as if received in time.
            completed = {
                event["key"]
                for kind in ("COPY_COMPLETE", "COPY_MISSED")
                for event in store.events(kind, 100000)
            }
            for event in store.events("COPY_REQUEST", 100000):
                if event["key"] not in completed:
                    monitor.emit(
                        "COPY_MISSED",
                        {"request_key": event["key"], "reason": "PROCESS_RESTART_INTERRUPTED"},
                        now(),
                        event["key"],
                    )
            await monitor.poll_trades()
            from premetar.research.trader_stream import stream_market

            jobs = [
                asyncio.create_task(monitor.loop("TRADES", monitor.poll_trades, poll_interval)),
                asyncio.create_task(monitor.loop("ACTIVITY", monitor.poll_activity, poll_interval)),
                asyncio.create_task(monitor.loop("DISCOVERY", monitor.discover, 600)),
                asyncio.create_task(monitor.loop("LIFECYCLE", monitor.lifecycle, 10)),
                asyncio.create_task(monitor.loop("HEALTH", monitor.health, 10)),
                asyncio.create_task(monitor.loop("STOP_REQUEST", monitor.check_stop, 1)),
                asyncio.create_task(monitor.loop("SERVICE_STATUS", monitor.service_status, 60)),
                asyncio.create_task(
                    monitor.loop("HISTORICAL_BACKFILL", monitor.historical_page, 10)
                ),
                asyncio.create_task(
                    stream_market(
                        lambda: list(monitor.tokens), cast(Any, monitor.emit), monitor.stop
                    )
                ),
                asyncio.create_task(monitor.trade_worker()),
            ]
            try:
                if duration is None:
                    await monitor.stop.wait()
                else:
                    await monitor.pause(duration)
            finally:
                monitor.stop.set()
                for task in [*jobs, *monitor.tasks]:
                    task.cancel()
                await asyncio.gather(*jobs, *monitor.tasks, return_exceptions=True)
                monitor.emit(
                    "STOP", {"run_id": monitor.run_id, "reason": "BOUNDED_OR_GRACEFUL_STOP"}, now()
                )
    finally:
        store.close()
        lock.close()
        lock_path.unlink(missing_ok=True)
        logger.removeHandler(handler)
        handler.close()
