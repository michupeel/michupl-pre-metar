"""EXP0014/15 isolated prospective sidecar. Public data; no order submission API.

Consumes the existing raw stream without a duplicate subscription. Expanded EPWA
forecast fields justify one additional noncommercial request per30minutes.
"""

import argparse
import asyncio
import base64
import contextlib
import hashlib
import json
import logging
import logging.handlers
import os
import signal
import sqlite3
import ssl
import time
import zlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import truststore

from premetar.continuous.locking import acquire, alive
from premetar.dashboard.segments import SegmentReader
from premetar.research.battle_controls import ControlTracker
from premetar.research.battle_store import BattleStore, read_battle
from premetar.research.forecast_books import BookTracker
from premetar.research.forecast_monitor import ROOT as ROOT
from premetar.research.forecast_monitor import TRADER, WEATHER, candidate_markets
from premetar.research.limit99 import TERMINAL, Limit99, clock, eligible, number
from premetar.research.realization import evaluate_realization
from premetar.research.trader_store import readonly_connection
from premetar.research.trader_stream import _normalize_message, stream_market

DIRECTORY = ROOT / "data/research/epwa_battle"
CONFIG = ROOT / "configs/experiments/epwa-battle-v1.json"
VARIABLES = "temperature_2m,cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high,relative_humidity_2m,dew_point_2m,wind_speed_10m,wind_direction_10m,precipitation,shortwave_radiation"


def now() -> datetime:
    return datetime.now(UTC)


def source_rows(path: Path, after: int | None) -> tuple[int, list[dict[str, Any]]]:
    conn = readonly_connection(path)
    try:
        conn.execute("PRAGMA busy_timeout=250")
        if after is None:
            maximum = conn.execute("SELECT MAX(id) FROM events").fetchone()[0] or 0
            rows = conn.execute(
                "SELECT id,kind,received_at,payload FROM events WHERE kind='MARKET' ORDER BY id DESC LIMIT 100"
            ).fetchall()
            rows += conn.execute(
                "SELECT id,kind,received_at,payload FROM events WHERE kind='STREAMHEALTH' ORDER BY id DESC LIMIT 1"
            ).fetchall()
            rows.sort(key=lambda r: r[0], reverse=True)
            return maximum, [
                dict(id=r[0], kind=r[1], received_at=r[2], payload=json.loads(r[3]), bootstrap=True)
                for r in reversed(rows)
            ]
        rows = conn.execute(
            "SELECT id,kind,received_at,payload FROM events WHERE id>? ORDER BY id LIMIT 2048",
            (after,),
        ).fetchall()
        return (rows[-1][0] if rows else after), [
            dict(id=r[0], kind=r[1], received_at=r[2], payload=json.loads(r[3])) for r in rows
        ]
    finally:
        conn.close()


def normalize_forecast(raw: dict[str, Any], received: datetime) -> dict[str, Any]:
    units, hourly = raw["hourly_units"], raw["hourly"]
    if units.get("time") != "unixtime" or units.get("temperature_2m") != "°C":
        raise ValueError("Forecast time/unit mismatch")
    times = hourly["time"]
    points = []
    for index, stamp in enumerate(times):
        if isinstance(stamp, bool) or not isinstance(stamp, int):
            raise ValueError("Invalid epoch seconds")
        point: dict[str, Any] = {"valid_time": datetime.fromtimestamp(stamp, UTC).isoformat()}
        for name in VARIABLES.split(","):
            values = hourly.get(name)
            point[name] = (
                values[index] if isinstance(values, list) and len(values) == len(times) else None
            )
        point["temperature_c"] = point["temperature_2m"]
        points.append(point)
    return dict(
        airport="EPWA",
        model="icon_global",
        first_received=received.isoformat(),
        snapshot_id=hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest(),
        points=points,
        daily_api=raw.get("daily"),
        hourly_units=units,
        daily_units=raw.get("daily_units"),
        daily_timezone="Europe/Warsaw",
        daily_semantics="PROVIDER_DAILY_AGGREGATION_NOT_HOURLY_MAX_OR_SETTLEMENT",
        radiation_semantics="PRECEDING_HOUR_MEAN_W_M2",
        precipitation_semantics="PRECEDING_HOUR_SUM_MM",
        run_time=None,
        publication_time=None,
        run_binding="UNVERIFIED",
        hourly_maximum=None,
    )


class Monitor:
    def __init__(self, store: BattleStore, config: dict[str, Any]) -> None:
        self.store, self.config = store, config
        saved, self.cursors = store.restore()
        self.engine = Limit99(config, saved.get("engine"))
        self.controls = ControlTracker(saved.get("controls"))
        self.control_events: list[dict[str, Any]] = []
        self.previous = saved.get("realization")
        self.forecasts = saved.get("forecasts", [])
        self.markets = saved.get("markets", {})
        self.tick_blocks = saved.get("tick_blocks", {})
        self.tracker = BookTracker(5)
        self.stop = asyncio.Event()
        self.raw: dict[str, Any] = {}
        self.last_feed: str | None = None
        self.last_weather = 0.0
        self.last_metrics = 0.0
        self.fallback: asyncio.Task[None] | None = None
        self.started = now()
        days = self.engine.state.setdefault("study_days", [])
        today = self.started.astimezone(ZoneInfo("Europe/Warsaw")).date().isoformat()
        if today not in days:
            days.append(today)
        self.engine.restart(self.started)
        # Preserve prototype events; correct only future accounting, audibly.
        for event in read_battle(store.directory, limit=100000):
            payload = event["payload"]
            old_order = payload.get("order") or {}
            arrival_unknown = event["kind"] == "ORDER_REJECTED" and str(
                payload.get("reason", "")
            ).startswith("ARRIVAL_BOOK")
            role_unknown = event["kind"] == "ORDER_RESTING" and not old_order.get(
                "complementary_post_only_checked"
            )
            if not arrival_unknown and not role_unknown:
                continue
            reason = (
                payload.get("reason")
                if arrival_unknown
                else "PROTOTYPE_COMPLEMENTARY_ROLE_UNVERIFIED"
            )
            key = f"{payload.get('family')}:{payload.get('mode')}:{payload.get('scenario')}:{payload.get('latency_ms')}"
            portfolio = self.engine.state["portfolios"].get(key)
            if not portfolio:
                continue
            for order in portfolio["orders"]:
                if order["id"] == old_order.get("id") and not order.get("execution_unknown"):
                    order.update(execution_unknown=True, state="UNKNOWN", terminal_reason=reason)
                    if order["side"] == "BUY":
                        portfolio["reserved"] = str(
                            number(portfolio["reserved"])
                            + (number(order["quantity"]) - number(order["filled"]))
                            * number(order["limit"])
                        )
                    self.engine.emit(
                        "ACCOUNTING_EXCLUSION",
                        self.started,
                        portfolio,
                        order_id=order["id"],
                        original_event_id=event["id"],
                        reason="MISSING_ARRIVAL_BOOK_IS_UNKNOWN_NOT_EXCHANGE_REJECTION"
                        if arrival_unknown
                        else reason,
                        historical_events_preserved=True,
                    )

    def commit(self, extra: list[dict[str, Any]] | None = None) -> None:
        engine_events = self.engine.drain()
        for event in engine_events:
            self.control_events.extend(
                self.controls.register(
                    event, (self.previous or {}).get("forecast_tmax"), clock(event["at"])
                )
            )
        self.store.commit(
            engine_events + self.control_events + (extra or []),
            dict(
                engine=self.engine.state,
                controls=self.controls.state,
                realization=self.previous,
                forecasts=self.forecasts[-12:],
                markets=self.markets,
                tick_blocks=self.tick_blocks,
            ),
            self.cursors,
            now(),
        )
        self.control_events = []

    def normalized(
        self, kind: str, payload: dict[str, Any], received: datetime, key: str | None = None
    ) -> None:
        if kind == "STREAMHEALTH":
            self.engine.invalidate(
                now(),
                payload.get("connection_id")
                if payload.get("state") in {"SUBSCRIBED", "SUBSCRIPTIONS_CHANGED"}
                else None,
            )
            self.tracker.observe(kind, payload, received)
            return
        tokens = {m["identity"][side] for m in self.markets.values() for side in ("no", "yes")}
        if kind in {"BOOK", "WS_TRADE"} and payload.get("token_id") not in tokens:
            return
        self.tracker.observe(kind, payload, received)
        self.last_feed = received.isoformat()
        at = now()  # Actual decision creation; never backdated to upstream receipt.
        for market in self.markets.values():
            identity = market["identity"]
            if kind == "WS_TRADE" and payload.get("token_id") != identity["no"]:
                continue
            book = self.tracker.view(identity["no"], at)
            book["complementary_book"] = self.tracker.view(identity["yes"], at)
            if identity["no"] in self.tick_blocks:
                book["status"] = "TICK_METADATA_UNVERIFIED"
            coverage = self.engine.state.setdefault(
                "coverage",
                dict(
                    distinct_book_states=0,
                    fresh_no_states=0,
                    eligible_no_ask_states=0,
                    eligible_no_bid_states=0,
                    last_books={},
                ),
            )
            signature = hashlib.sha256(json.dumps(book, sort_keys=True).encode()).hexdigest()
            last = coverage["last_books"].get(identity["condition_id"], {})
            if last.get("signature") != signature:
                coverage["distinct_book_states"] += 1
                if book["status"] == "VALID":
                    coverage["fresh_no_states"] += 1
                    if (
                        identity["day"]
                        == at.astimezone(ZoneInfo("Europe/Warsaw")).date().isoformat()
                        and book.get("best_ask") is not None
                        and eligible(number(book["best_ask"]))
                    ):
                        coverage["eligible_no_ask_states"] += 1
                    if (
                        identity["day"]
                        == at.astimezone(ZoneInfo("Europe/Warsaw")).date().isoformat()
                        and book.get("best_bid") is not None
                        and eligible(number(book["best_bid"]))
                    ):
                        coverage["eligible_no_bid_states"] += 1
                coverage["last_books"][identity["condition_id"]] = dict(
                    signature=signature,
                    status=book["status"],
                    received_at=book.get("received_at"),
                    best_bid=book.get("best_bid"),
                    best_ask=book.get("best_ask"),
                    day=identity["day"],
                )
            if book["status"] not in {"VALID", "NO_FULL_SNAPSHOT"}:
                self.engine.invalidate(at, None, identity["no"])
            trade = dict(payload, received_at=received.isoformat()) if kind == "WS_TRADE" else None
            self.engine.observe(at, market, book, self.previous or {}, trade)

    def ingest(self, event: dict[str, Any]) -> None:
        kind, payload = event["kind"], event["payload"]
        received = clock(event["received_at"])
        if kind == "MARKET":
            identity = payload.get("identity") or {}
            if identity.get("airport") == "EPWA" and identity.get("station_match") is True:
                identity = dict(
                    identity,
                    day=identity.get("day", identity.get("local_date")),
                    outcome_label=identity.get(
                        "outcome_label", str(payload.get("metadata", {}).get("groupItemTitle", ""))
                    ),
                )
                self.markets[identity["condition_id"]] = dict(
                    payload, identity=identity, received_at=received.isoformat()
                )
                block = self.tick_blocks.get(identity["no"])
                if (
                    block
                    and received > clock(block["at"])
                    and str(payload.get("metadata", {}).get("orderPriceMinTickSize"))
                    == str(block.get("new_tick_size"))
                ):
                    self.tick_blocks.pop(identity["no"], None)
                if not event.get("bootstrap"):
                    self.engine.settle(now(), self.markets[identity["condition_id"]])
        elif kind == "STREAMHEALTH":
            self.normalized(kind, payload, received)
        elif kind == "WS_RAW" and not event.get("bootstrap"):
            try:
                text = payload.get("text")
                if text is None and payload.get("encoding") == "zlib+base64":
                    decoder = zlib.decompressobj()
                    data = decoder.decompress(
                        base64.b64decode(payload["compressed_text"]), 4 * 1024 * 1024 + 1
                    )
                    if len(data) > 4 * 1024 * 1024 or decoder.unconsumed_tail:
                        raise ValueError("Frame size bound")
                    text = data.decode()
                if isinstance(text, str):
                    self.inspect_tick(text, received)
                    _normalize_message(text, payload["connection_id"], received, self.normalized)
            except (ValueError, KeyError, TypeError, zlib.error):
                self.engine.invalidate(now(), None)
                self.tracker.observe(
                    "STREAMHEALTH",
                    dict(state="MALFORMED_MESSAGE", connection_id=self.tracker.connection_id),
                    received,
                )

    def inspect_tick(self, text: str, received: datetime) -> None:
        if "tick_size_change" not in text:
            return
        decoded = json.loads(text)
        for message in decoded if isinstance(decoded, list) else [decoded]:
            if not isinstance(message, dict) or message.get("event_type") != "tick_size_change":
                continue
            token = message.get("asset_id")
            if token not in {m["identity"]["no"] for m in self.markets.values()}:
                continue
            self.tick_blocks[token] = dict(
                at=received.isoformat(), new_tick_size=message.get("new_tick_size")
            )
            self.engine.invalidate(now(), None, token)
            self.commit(
                [
                    dict(
                        kind="TICK_CHANGE_BLOCK",
                        at=now().isoformat(),
                        payload=dict(
                            token_id=token,
                            source_event=message,
                            reason="WAIT_FOR_VERIFIED_NEW_METADATA",
                        ),
                    )
                ]
            )

    def realization(self, at: datetime) -> dict[str, Any]:
        day = at.astimezone(ZoneInfo("Europe/Warsaw")).date()
        reader = SegmentReader(WEATHER, ROOT / "data/research/exp0013/observations.sqlite3", TRADER)
        self.raw = reader.load_day(day)
        for forecast in self.raw.get("forecasts", []):
            forecast.setdefault(
                "snapshot_id", f"EXP13:{forecast.get('event_id')}:{forecast.get('received_at')}"
            )
        result = evaluate_realization(
            self.raw.get("metars", []),
            self.raw.get("forecasts", []) + self.forecasts,
            self.raw.get("pws", []),
            at,
            self.previous,
        )
        self.previous = result
        return result

    async def enrich(self, client: httpx.AsyncClient) -> None:
        started = now()
        try:
            response = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params=dict(
                    latitude=52.163,
                    longitude=20.961,
                    models="icon_global",
                    hourly=VARIABLES,
                    daily="temperature_2m_max",
                    timezone="Europe/Warsaw",
                    timeformat="unixtime",
                    temperature_unit="celsius",
                    forecast_days=3,
                    past_days=1,
                ),
            )
            received = now()
            self.commit(
                [
                    dict(
                        kind="FORECAST_RAW",
                        at=received.isoformat(),
                        payload=dict(
                            request_start=started.isoformat(),
                            receive_time=received.isoformat(),
                            status=response.status_code,
                            body=response.text,
                            model="icon_global",
                            endpoint="https://api.open-meteo.com/v1/forecast",
                        ),
                    )
                ]
            )
            response.raise_for_status()
            forecast = normalize_forecast(response.json(), received)
            self.forecasts.append(forecast)
            self.forecasts = self.forecasts[-12:]
            self.commit([dict(kind="FORECAST", at=now().isoformat(), payload=forecast)])
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            self.commit(
                [
                    dict(
                        kind="ERROR",
                        at=now().isoformat(),
                        payload=dict(
                            operation="FORECAST_ENRICHMENT", error_class=type(error).__name__
                        ),
                    )
                ]
            )

    async def source_fallback(self) -> None:
        """Only after the shared EXP0013 owner has exited, never a duplicate feed."""
        lock_path = ROOT / "data/research/exp0013/observer.lock"
        try:
            if lock_path.exists():
                info = json.loads(lock_path.read_text(encoding="utf-8")[1:])
                if alive(int(info["pid"])):
                    if self.fallback:
                        self.fallback.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await self.fallback
                        self.fallback = None
                        self.engine.invalidate(now(), None)
                        self.tracker = BookTracker(5)
                        self.commit(
                            [
                                dict(
                                    kind="SOURCE_HANDOVER",
                                    at=now().isoformat(),
                                    payload=dict(
                                        reason="EXISTING_EXP0013_OWNER_RESUMED",
                                        scope="REUSE_EXISTING_STREAM",
                                    ),
                                )
                            ]
                        )
                    return
        except (OSError, ValueError, KeyError, TypeError):
            return  # Unknown ownership blocks a new external socket.
        if self.fallback is None and self.markets:

            def emit(
                kind: str, payload: dict[str, Any], received: datetime, key: str | None
            ) -> None:
                if kind == "WS_RAW":
                    text = payload.get("text", "")
                    captured = dict(payload)
                    captured.pop("text", None)
                    captured.update(
                        encoding="zlib+base64",
                        compressed_text=base64.b64encode(zlib.compress(text.encode())).decode(),
                    )
                    self.commit(
                        [
                            dict(
                                kind="FALLBACK_WS_RAW",
                                at=now().isoformat(),
                                payload=dict(captured, upstream_receive_time=received.isoformat()),
                            )
                        ]
                    )
                    self.inspect_tick(text, received)
                else:
                    self.normalized(kind, payload, received)
                    self.commit()

            self.fallback = asyncio.create_task(
                stream_market(
                    lambda: sorted(
                        {m["identity"][s] for m in self.markets.values() for s in ("yes", "no")}
                    ),
                    emit,
                    self.stop,
                )
            )
            self.commit(
                [
                    dict(
                        kind="SOURCE_HANDOVER",
                        at=now().isoformat(),
                        payload=dict(
                            reason="EXISTING_EXP0013_OWNER_EXITED",
                            scope="EPWA_ONLY",
                            retention="BOUNDED_SHARED_BATTLE_SEGMENTS",
                        ),
                    )
                ]
            )

    async def fallback_metadata(self, client: httpx.AsyncClient) -> None:
        """Only replaces metadata service after the old source stops; public reads."""
        candidates = await asyncio.to_thread(candidate_markets, TRADER, now())
        for candidate in candidates:
            if candidate["identity"].get("airport") == "EPWA":
                condition = candidate["identity"]["condition_id"]
                if condition not in self.markets:
                    self.ingest(
                        dict(
                            kind="MARKET",
                            received_at=candidate["original_received"],
                            payload=candidate,
                            bootstrap=True,
                        )
                    )
        for condition, market in list(self.markets.items()):
            held = any(
                number(number_pos.get("quantity", "0")) > 0
                for p in self.engine.state["portfolios"].values()
                for c, number_pos in p["positions"].items()
                if c == condition
            )
            if (
                market["identity"].get("day")
                != now().astimezone(ZoneInfo("Europe/Warsaw")).date().isoformat()
                and not held
            ):
                continue
            try:
                response = await client.get(
                    "https://gamma-api.polymarket.com/markets",
                    params={"condition_ids": condition, "closed": "any"},
                )
                received = now()
                self.commit(
                    [
                        dict(
                            kind="MARKET_RAW",
                            at=received.isoformat(),
                            payload=dict(
                                status=response.status_code,
                                body=response.text,
                                condition_id=condition,
                            ),
                        )
                    ]
                )
                response.raise_for_status()
                data = response.json()
                if (
                    not isinstance(data, list)
                    or len(data) != 1
                    or data[0].get("conditionId") != condition
                ):
                    raise ValueError("Market identity mismatch")
                self.ingest(
                    dict(
                        kind="MARKET",
                        received_at=received.isoformat(),
                        payload=dict(identity=market["identity"], metadata=data[0]),
                    )
                )
                self.commit()
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
                self.commit(
                    [
                        dict(
                            kind="ERROR",
                            at=now().isoformat(),
                            payload=dict(
                                operation="FALLBACK_METADATA", error_class=type(error).__name__
                            ),
                        )
                    ]
                )
            await asyncio.sleep(0.1)

    async def run(self, seconds: float | None = None) -> None:
        next_forecast = 0.0
        next_metadata = 0.0
        # Restart gaps are censored, not opportunities replayed into the present.
        # Restore metadata/subscription identity, then demand a NEW full snapshot.
        for path in SegmentReader(
            WEATHER, ROOT / "data/research/exp0013/observations.sqlite3", TRADER
        ).paths():
            cursor, context = await asyncio.to_thread(source_rows, path, None)
            previous_cursor = self.cursors.get(str(path))
            for event in context:
                self.ingest(event)
            self.cursors[str(path)] = cursor
            if previous_cursor is not None and cursor > previous_cursor:
                self.commit(
                    [
                        dict(
                            kind="RESTART_GAP",
                            at=now().isoformat(),
                            payload=dict(
                                source=path.name,
                                previous_cursor=previous_cursor,
                                resumed_cursor=cursor,
                                queue_evidence="INVALIDATED",
                                simulation="NO_REPLAYED_ENTRIES_OR_FILLS",
                            ),
                        )
                    ]
                )
        async with httpx.AsyncClient(
            verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
            timeout=20,
            headers={"User-Agent": "michupl-pre-metar EXP0014 research"},
        ) as client:
            enrichment: asyncio.Task[None] | None = None
            try:
                while not self.stop.is_set():
                    if (DIRECTORY / "stop.request").exists():
                        break
                    tick = time.monotonic()
                    if seconds is not None and (now() - self.started).total_seconds() >= seconds:
                        break
                    if tick >= next_forecast:
                        if enrichment is None or enrichment.done():
                            if enrichment:
                                enrichment.result()
                            enrichment = asyncio.create_task(self.enrich(client))
                        next_forecast = tick + self.config["forecast_enrichment_seconds"]
                    paths = SegmentReader(
                        WEATHER, ROOT / "data/research/exp0013/observations.sqlite3", TRADER
                    ).paths()
                    for path in paths:
                        try:
                            cursor, rows = await asyncio.to_thread(
                                source_rows, path, self.cursors.get(str(path))
                            )
                        except (sqlite3.Error, OSError, ValueError):
                            self.commit(
                                [
                                    dict(
                                        kind="ERROR",
                                        at=now().isoformat(),
                                        payload=dict(operation="LOCAL_FEED_READ", source=path.name),
                                    )
                                ]
                            )
                            continue
                        for row in rows:
                            self.ingest(row)
                        self.cursors[str(path)] = cursor
                    if tick - self.last_weather >= 30:
                        old = self.previous or {}
                        result = await asyncio.to_thread(self.realization, now())
                        changes = [
                            k
                            for k in ("confidence", "state", "trend", "rule_version")
                            if old.get(k) != result.get(k)
                        ]
                        if old.get("cloud", {}).get("status") != result.get("cloud", {}).get(
                            "status"
                        ):
                            changes.append("cloud")
                        if changes:
                            self.commit(
                                [
                                    dict(
                                        kind="CONFIDENCE" if old else "REALIZATION_BOOTSTRAP",
                                        at=now().isoformat(),
                                        payload=dict(
                                            result,
                                            previous_state={k: old.get(k) for k in changes},
                                            changed=changes,
                                            prospective=bool(old),
                                        ),
                                    )
                                ]
                            )
                        self.last_weather = tick
                    at = now()
                    today = at.astimezone(ZoneInfo("Europe/Warsaw")).date().isoformat()
                    if today not in self.engine.state["study_days"]:
                        self.engine.state["study_days"].append(today)
                    for market in list(self.markets.values()):
                        book = self.tracker.view(market["identity"]["no"], at)
                        book["complementary_book"] = self.tracker.view(
                            market["identity"]["yes"], at
                        )
                        if market["identity"]["no"] in self.tick_blocks:
                            book["status"] = "TICK_METADATA_UNVERIFIED"
                        self.control_events.extend(
                            self.controls.observe(
                                market["identity"]["condition_id"],
                                book,
                                at,
                            )
                        )
                        self.engine.observe(
                            at,
                            market,
                            book,
                            self.previous or {},
                        )
                    if tick - self.last_metrics >= 60:
                        self.commit(
                            [
                                dict(
                                    kind="METRIC",
                                    at=at.isoformat(),
                                    payload=dict(
                                        strategies=self.engine.metrics(at),
                                        realization=self.previous,
                                        health=dict(
                                            pid=os.getpid(),
                                            last_feed=self.last_feed,
                                            started_at=self.started.isoformat(),
                                            source="EXISTING_RAW_WS"
                                            if not self.fallback
                                            else "EPWA_FALLBACK_WS",
                                            state="RUNNING",
                                            feed_status="LIVE"
                                            if self.last_feed
                                            and 0
                                            <= (at - clock(self.last_feed)).total_seconds()
                                            <= 30
                                            else "WAITING_OR_STALE",
                                        ),
                                        sample_days=self.engine.state["study_days"],
                                        coverage=self.engine.state.get("coverage", {}),
                                        completed_settlement_days=[
                                            d
                                            for d in self.engine.state["study_days"]
                                            if d < today
                                            and all(
                                                number(pos["quantity"]) == 0
                                                for p in self.engine.state["portfolios"].values()
                                                for pos in p["positions"].values()
                                                if pos["day"] == d
                                            )
                                            and all(
                                                o["state"] in TERMINAL
                                                and not o.get("execution_unknown")
                                                for p in self.engine.state["portfolios"].values()
                                                for o in p["orders"]
                                                if o["day"] == d
                                            )
                                        ],
                                    ),
                                )
                            ]
                        )
                        self.last_metrics = tick
                    else:
                        self.commit()
                    await self.source_fallback()
                    if self.fallback and tick >= next_metadata:
                        await self.fallback_metadata(client)
                        next_metadata = tick + 900
                    if self.fallback and self.fallback.done():
                        self.fallback.result()
                        self.fallback = None
                    try:
                        await asyncio.wait_for(
                            self.stop.wait(), timeout=self.config["poll_local_seconds"]
                        )
                    except TimeoutError:
                        pass
            finally:
                self.stop.set()
                for task in (enrichment, self.fallback):
                    if task:
                        task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await task
                self.commit(
                    [
                        dict(
                            kind="STOP",
                            at=now().isoformat(),
                            payload=dict(reason="CONTROLLED_SHUTDOWN", inventory_preserved=True),
                        )
                    ]
                )


async def watch(seconds: float | None = None) -> None:
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    if (DIRECTORY / "stop.request").exists():
        raise RuntimeError("Research stop.request exists; no new process started")
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    lock_path = DIRECTORY / "monitor.lock"
    lock = acquire(lock_path, uuid4().hex, recover=True)
    store = None
    try:
        store = BattleStore(
            DIRECTORY,
            config["storage_segment_bytes"],
            config["storage_total_bytes"],
            config["min_free_disk_bytes"],
        )
        monitor = Monitor(store, config)
        monitor.commit(
            [
                dict(
                    kind="RUN",
                    at=now().isoformat(),
                    payload=dict(
                        config=config,
                        config_hash=monitor.engine.hash,
                        pid=os.getpid(),
                        baseline="0c8f8ab",
                        prospective=True,
                        source_hashes={
                            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in (
                                Path(__file__),
                                Path(__file__).with_name("limit99.py"),
                                Path(__file__).with_name("realization.py"),
                                Path(__file__).with_name("battle_controls.py"),
                            )
                        },
                    ),
                )
            ]
        )
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, lambda *_: monitor.stop.set())
        await monitor.run(seconds)
    finally:
        if store:
            store.close()
        lock.close()
        lock_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["watch", "status", "report"])
    parser.add_argument("--seconds", type=float)
    args = parser.parse_args()
    if args.seconds is not None and args.seconds <= 0:
        parser.error("Positive bounded smoke duration required")
    if args.command == "watch":
        logs = ROOT / "logs"
        logs.mkdir(exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            logs / "epwa-battle.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
        )
        logging.basicConfig(level=logging.WARNING, handlers=[handler])
        asyncio.run(watch(args.seconds))
    elif args.command == "status":
        events = read_battle(DIRECTORY, limit=30)
        print(json.dumps(dict(events=list(events), limits=events.metadata), indent=2))
    else:
        from premetar.research.battle_reports import generate

        print(json.dumps(generate(), indent=2))


if __name__ == "__main__":
    main()
