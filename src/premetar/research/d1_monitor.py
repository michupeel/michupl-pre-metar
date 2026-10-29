"""EXP0016 public-data sidecar; no order API or automatic calibration promotion."""

import argparse
import asyncio
import base64
import contextlib
import hashlib
import json
import os
import re
import signal
import sqlite3
import ssl
import time
import zlib
from datetime import UTC, date, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import truststore

from premetar.continuous.locking import acquire
from premetar.dashboard.segments import SegmentReader
from premetar.research.battle_store import BattleStore, EventRecords
from premetar.research.d1_forecasts import MODEL_SPECS, consensus, normalize_model
from premetar.research.d1_strategy import (
    STRATEGIES,
    default_config,
    evaluate_candidate,
    parse_outcome,
)
from premetar.research.forecast_books import BookTracker
from premetar.research.forecast_monitor import ROOT as ROOT
from premetar.research.forecast_monitor import TRADER, WEATHER
from premetar.research.trader_monitor import market_tokens
from premetar.research.trader_stream import _normalize_message, stream_market

DIRECTORY = ROOT / "data/research/epwa_d1"
ZONE = ZoneInfo("Europe/Warsaw")
MONTHS = (
    "january february march april may june july august september october november december".split()
)


def now() -> datetime:
    return datetime.now(UTC)


def expired(deadline: float) -> int:
    return int(time.monotonic() > deadline)


def clock(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timezone required")
    return result.astimezone(UTC)


def normalize_market(raw: dict[str, Any], at: datetime) -> dict[str, Any] | None:
    match = re.match(
        r"^highest-temperature-in-warsaw-on-([a-z]+)-(\d{1,2})-(\d{4})(?:-|$)",
        str(raw.get("slug", "")),
    )
    if not match or match[1] not in MONTHS:
        return None
    try:
        day = date(int(match[3]), MONTHS.index(match[1]) + 1, int(match[2]))
        outcomes = raw.get("outcomes", [])
        outcomes = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
        tokens = market_tokens(raw)
        if len(tokens) != 2 or not isinstance(outcomes, list) or set(outcomes) != {"Yes", "No"}:
            return None
        local_day = at.astimezone(ZONE).date()
        if not local_day <= day <= local_day + timedelta(days=1):
            return None
    except (ValueError, TypeError):
        return None
    explicit_epwa = "Airport (EPWA)" in str(raw.get("description", "")) and "ids=EPWA" in str(
        raw.get("resolutionSource", "")
    )
    identity = dict(
        airport="EPWA",
        local_date=day.isoformat(),
        station="EPWA" if explicit_epwa else None,
        station_match=explicit_epwa,
        condition_id=raw.get("conditionId"),
        yes=tokens[outcomes.index("Yes")],
        no=tokens[outcomes.index("No")],
    )
    description = str(raw.get("description", ""))
    lower = description.lower()
    # Explicit captured rule clauses; never certify a contract from city alone.
    verified = bool(
        identity.get("station_match")
        and "local time" in lower
        and "hourly temperature remark" in lower
        and "routine" in lower
        and "speci" in lower
        and "does not count" in lower
        and "half rounded up to the next higher" in lower
        and "aviationweather.gov/api/data/metar?ids=EPWA" in description
    )
    outcome = parse_outcome(str(raw.get("groupItemTitle", "")))
    identity = dict(
        identity,
        settlement_date=identity["local_date"],
        outcome=outcome,
        tokens={"YES": identity["yes"], "NO": identity["no"]},
    )
    return dict(
        airport="EPWA",
        timezone=ZONE.key,
        settlement_date=identity["local_date"],
        condition_id=identity["condition_id"],
        title=raw.get("question"),
        outcome=outcome,
        tokens={"YES": identity["yes"], "NO": identity["no"]},
        identity=identity,
        metadata=raw,
        received_at=at.isoformat(),
        rules_status="VERIFIED_CAPTURED_NOAA_RULE_CLAUSES" if verified else "UNVERIFIED",
        rules=dict(
            verified=verified,
            reference_station=identity.get("station"),
            timezone=ZONE.key,
            settlement_source=raw.get("resolutionSource"),
            daily_maximum_definition="ROUTINE_T_REMARK_TENTHS_BODY_FALLBACK_SPECI_EXCLUDED",
            rounding="HALF_TOWARD_WARMER",
            description_sha256=hashlib.sha256(description.encode()).hexdigest(),
        ),
    )


def tail(path: Path, after: int | None) -> tuple[int, list[dict[str, Any]]]:
    """Short read, bounded VM work; startup skips historical books entirely."""
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.25) as conn:
        conn.execute("PRAGMA query_only=ON")
        conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        deadline = time.monotonic() + 0.15
        column = "received_at" if "epwa_battle" not in str(path) else "at"
        if after is None:
            maximum = conn.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0]
            rows = conn.execute(
                f"SELECT id,kind,{column},payload FROM events WHERE kind='STREAMHEALTH' ORDER BY id DESC LIMIT 1"
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT id,kind,{column},payload FROM events WHERE id>? ORDER BY id LIMIT 2048",
                (after,),
            ).fetchall()
            maximum = rows[-1][0] if rows else after
        return maximum, [
            dict(id=r[0], kind=r[1], received_at=r[2], payload=json.loads(r[3])) for r in rows
        ]


def airport_coordinates() -> tuple[float, float]:
    with sqlite3.connect(
        WEATHER.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.25
    ) as connection:
        connection.execute("PRAGMA query_only=ON")
        row = connection.execute("SELECT data_json FROM pws_airports WHERE icao='EPWA'").fetchone()
    if not row:
        raise ValueError("Verified EPWA metadata unavailable")
    airport = json.loads(row[0])
    return float(airport["latitude"]), float(airport["longitude"])


def read_state(directory: Path, at: datetime) -> EventRecords:
    """Thin dashboard projection: never decode the raw WS archive on refresh."""
    forecasts: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    paths = sorted(
        p
        for p in directory.glob("battle-*.sqlite3")
        if re.fullmatch(r"battle-[0-9]{6}\.sqlite3", p.name) and not p.is_symlink()
    )[-30:]
    errors = {}
    for path in reversed(paths):
        try:
            with sqlite3.connect(
                path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.25
            ) as connection:
                deadline = time.monotonic() + 0.25
                connection.execute("PRAGMA query_only=ON")
                connection.set_progress_handler(partial(expired, deadline), 1000)
                for kind, limit, rows in [
                    ("D1_SNAPSHOT", 1, snapshots),
                    ("D1_FORECAST", 50, forecasts),
                ]:
                    if kind == "D1_SNAPSHOT" and rows:
                        continue
                    if kind == "D1_FORECAST" and len(rows) >= 20:
                        continue
                    records = connection.execute(
                        "SELECT id,kind,at,payload FROM events WHERE kind=? AND at<=? ORDER BY id DESC LIMIT ?",
                        (kind, at.isoformat(timespec="microseconds"), limit),
                    ).fetchall()
                    rows.extend(
                        dict(id=r[0], kind=r[1], at=r[2], payload=json.loads(r[3])) for r in records
                    )
        except (sqlite3.Error, OSError, ValueError) as error:
            errors[path.name] = type(error).__name__
        if snapshots and len(forecasts) >= 20:
            break
    return EventRecords(
        sorted(forecasts + snapshots, key=lambda e: (e["at"], e["id"])),
        dict(
            projection="LATEST_SNAPSHOT_AND_AT_MOST50_FORECASTS_PER_SEGMENT_NO_RAW",
            segments_available=len(paths),
            errors=errors,
            truncated=False,
        ),
    )


def view(at: datetime, directory: Path = DIRECTORY) -> dict[str, Any]:
    """Only immutable evidence already committed at the requested instant."""
    at = clock(at.isoformat())
    records = read_state(directory, at)
    snapshot = next((e for e in reversed(records) if e["kind"] == "D1_SNAPSHOT"), None)
    target = (at.astimezone(ZONE).date() + timedelta(days=1)).isoformat()
    forecasts = [e["payload"] for e in records if e["kind"] == "D1_FORECAST"]
    combined = consensus(forecasts, target, at)
    result = dict(snapshot["payload"]) if snapshot else {}
    # A prior-day snapshot cannot masquerade as tomorrow's current book.
    combined.update(
        min_c=combined.get("range_min_c"),
        max_c=combined.get("range_max_c"),
        families=combined.get("family_count"),
    )
    models = combined.get("models", [])
    for row in models:
        row["tmax_time"] = next(iter(row.get("peak_times_utc", [])), None)
        row["status"] = "AVAILABLE_RUN_UNIDENTIFIED" if row.get("complete") else "INCOMPLETE_DAY"
        older = sorted(
            [
                f
                for f in forecasts
                if f["model"] == row["model"]
                and clock(f["first_received"]) < clock(row["first_received"])
            ],
            key=lambda f: f["first_received"],
        )
        prior = (
            next(
                (
                    d.get("daily_tmax_c")
                    for d in older[-1].get("days", [])
                    if d["settlement_date"] == target
                ),
                None,
            )
            if older
            else None
        )
        row["revision_c"] = (
            row["daily_tmax_c"] - prior
            if prior is not None and row.get("daily_tmax_c") is not None
            else None
        )
    result.update(
        asof=at.isoformat(),
        settlement_date=target,
        consensus=combined,
        forecasts=models,
        evidence_at=snapshot["at"] if snapshot else None,
        limits=records.metadata,
    )
    if not snapshot or result.get("decision_day") != at.astimezone(ZONE).date().isoformat():
        result.update(markets=[], health=dict(state="NO_PROSPECTIVE_DATA_AT_CURSOR"))
    elif (at - clock(snapshot["at"])).total_seconds() > 90:
        result["health"] = dict(result.get("health", {}), state="STALE")
    result.setdefault("markets", [])
    result["markets"] = [m for m in result["markets"] if m.get("settlement_date") == target]
    for market in result["markets"]:
        for side in ("yes_book", "no_book"):
            book = market.get(side, {})
            receipt = book.get("received_at")
            if receipt and (at - clock(receipt)).total_seconds() > 5:
                book["status_at_evidence"] = book["status"]
                book["status"] = "STALE_BOOK"
    result["health"] = dict(
        result.get("health", {}), last_metric_at=snapshot["at"] if snapshot else None
    )
    result["strategies"] = [
        dict(
            version=s,
            status="SIGNAL_ONLY / CALIBRATION_PENDING",
            submitted_orders=0,
            supported_buy_fills=0,
            open_positions=0,
            capital_usd=100,
            exposure_usd=0,
            net_pnl=None,
        )
        for s in STRATEGIES
    ]
    result["limitations"] = [
        "No audited historical EPWA settlement/horizon pairs or promoted probability certificate; EV and trading are blocked.",
        "First collector receipt verified; original forecast initialization/publication unknown. Repeated API fetches are not independent model runs.",
        "Decision-time depth is conditional, not a fill or arrival-book proof. Maker queues/complementary paths not certified.",
        "D0/D1 observations retained; independent resolved prospective days required before strategy comparison.",
    ]
    return result


class D1Monitor:
    def __init__(self, store: BattleStore) -> None:
        self.store = store
        self.state, _ = store.restore()
        self.markets: dict[str, dict[str, Any]] = self.state.get("markets", {})
        self.forecasts: list[dict[str, Any]] = self.state.get("forecasts", [])
        self.stop = asyncio.Event()
        self.own = BookTracker(5)
        self.sources: dict[str, BookTracker] = {}
        self.cursors: dict[str, int] = {}
        self.last_raw: dict[str, datetime] = {}
        self.errors: dict[str, int] = self.state.get("errors", {})
        self.start = time.monotonic()
        self.drop_until: dict[str, float] = {}
        self.rechecked: dict[str, float] = {}

    def emit(self, kind: str, payload: dict[str, Any], at: datetime | None = None) -> None:
        self.state.update(markets=self.markets, forecasts=self.forecasts[-30:], errors=self.errors)
        self.store.commit(
            [dict(kind=kind, at=(at or now()).isoformat(), payload=payload)], self.state, {}, now()
        )

    async def get(
        self, client: httpx.AsyncClient, url: str, params: dict[str, Any]
    ) -> tuple[Any, datetime]:
        started, mono = now(), time.monotonic()
        response = await client.get(url, params=params)
        received = now()
        text = response.text
        for offset in range(0, len(text), 200000):
            self.emit(
                "D1_HTTP_RAW",
                dict(
                    url=url,
                    params=params,
                    request_start=started.isoformat(),
                    received_at=received.isoformat(),
                    duration_ms=(time.monotonic() - mono) * 1000,
                    status=response.status_code,
                    offset=offset,
                    total_chars=len(text),
                    text=text[offset : offset + 200000],
                ),
                received,
            )
        if not text:
            self.emit(
                "D1_HTTP_RAW",
                dict(
                    url=url,
                    params=params,
                    status=response.status_code,
                    text="",
                    received_at=received.isoformat(),
                ),
                received,
            )
        response.raise_for_status()
        return response.json(), received

    async def discover(self, client: httpx.AsyncClient) -> None:
        for offset in (0, 1):
            day = now().astimezone(ZONE).date() + timedelta(days=offset)
            slug = f"highest-temperature-in-warsaw-on-{MONTHS[day.month - 1]}-{day.day}-{day.year}"
            raw, received = await self.get(
                client, "https://gamma-api.polymarket.com/events", {"slug": slug}
            )
            if not isinstance(raw, list):
                raise ValueError("Unexpected event schema")
            accepted = []
            for event in raw:
                if not isinstance(event, dict):
                    raise ValueError("Unexpected event record")
                if event.get("slug") != slug:
                    continue
                items = event.get("markets", [])
                if not isinstance(items, list):
                    raise ValueError("Unexpected market array")
                for item in items[:40]:
                    if not isinstance(item, dict):
                        raise ValueError("Unexpected market record")
                    market = normalize_market(item, received)
                    if market and market["settlement_date"] == day.isoformat():
                        self.markets[market["condition_id"]] = market
                        self.emit("D1_MARKET", market, received)
                        accepted.append(market["condition_id"])
            self.emit(
                "D1_DISCOVERY",
                dict(
                    settlement_date=day.isoformat(),
                    slug=slug,
                    markets=len(accepted),
                    condition_ids=accepted,
                ),
                received,
            )
        earliest = now().astimezone(ZONE).date().isoformat()
        self.markets = {k: v for k, v in self.markets.items() if v["settlement_date"] >= earliest}

    async def forecast(self, client: httpx.AsyncClient) -> None:
        latitude, longitude = await asyncio.to_thread(airport_coordinates)
        raw, received = await self.get(
            client,
            "https://api.open-meteo.com/v1/forecast",
            dict(
                latitude=latitude,
                longitude=longitude,
                models=",".join(MODEL_SPECS),
                hourly="temperature_2m",
                daily="temperature_2m_max",
                timezone=ZONE.key,
                timeformat="unixtime",
                forecast_days=2,
            ),
        )
        if not isinstance(raw, dict):
            raise ValueError("Unexpected multi-model forecast object")
        for model in MODEL_SPECS:
            try:
                normalized = normalize_model(raw, model, received)
                normalized["snapshot_id"] = hashlib.sha256(
                    json.dumps([model, received.isoformat(), raw], sort_keys=True).encode()
                ).hexdigest()
                self.forecasts.append(normalized)
                self.emit("D1_FORECAST", normalized, received)
            except (ValueError, TypeError, KeyError):
                self.emit(
                    "D1_MODEL_ERROR", dict(model=model, error="NORMALIZATION_FAILED"), received
                )
        self.forecasts = self.forecasts[-30:]

    def paths(self) -> list[Path]:
        shared = SegmentReader(
            WEATHER, ROOT / "data/research/exp0013/observations.sqlite3", TRADER
        ).paths()[-2:]
        return [
            p
            for p in shared
            + [TRADER]
            + sorted((ROOT / "data/research/epwa_battle").glob("battle-*.sqlite3"))[-1:]
            if p.is_file()
        ]

    def normalize(
        self, tracker: BookTracker, kind: str, payload: dict[str, Any], received: datetime
    ) -> None:
        # Some shared sidecars retain raw frames but not health records. Infer
        # subscription only for instruments actually present in that wire frame.
        if kind in {"BOOK", "WS_TRADE", "WS_DELTA"}:
            tokens = (
                {str(payload["token_id"])}
                if payload.get("token_id")
                else {
                    str(c["asset_id"])
                    for c in payload.get("price_changes", [])
                    if c.get("asset_id")
                }
            )
            connection = payload.get("connection_id")
            if tracker.connection_id != connection:
                tracker.observe(
                    "STREAMHEALTH",
                    dict(state="SUBSCRIBED", connection_id=connection, tokens=sorted(tokens)),
                    received,
                )
            elif not tokens.issubset(tracker.tokens):
                tracker.observe(
                    "STREAMHEALTH",
                    dict(
                        state="SUBSCRIPTIONS_CHANGED",
                        connection_id=connection,
                        tokens=sorted(tokens | tracker.tokens),
                    ),
                    received,
                )
        tracker.observe(kind, payload, received)

    async def reuse(self) -> None:
        for path in self.paths():
            key = str(path)
            try:
                cursor, events = await asyncio.to_thread(tail, path, self.cursors.get(key))
                tracker = self.sources.setdefault(key, BookTracker(5))
                for event in events:
                    try:
                        kind, payload = event["kind"], event["payload"]
                        received = clock(payload.get("upstream_receive_time", event["received_at"]))
                        if kind == "STREAMHEALTH":
                            tracker.observe(kind, payload, received)
                        elif kind in {"WS_RAW", "FALLBACK_WS_RAW"}:
                            self.last_raw[key] = received
                            text = payload.get("text")
                            if text is None and payload.get("encoding") == "zlib+base64":
                                dec = zlib.decompressobj()
                                data = dec.decompress(
                                    base64.b64decode(payload["compressed_text"]),
                                    4 * 1024 * 1024 + 1,
                                )
                                if len(data) > 4 * 1024 * 1024 or dec.unconsumed_tail:
                                    raise ValueError("Frame bound")
                                text = data.decode()
                            if isinstance(text, str):
                                _normalize_message(
                                    text,
                                    payload["connection_id"],
                                    received,
                                    partial(self.shared_emit, tracker),
                                )
                    except (ValueError, TypeError, KeyError, zlib.error):
                        tracker.observe(
                            "STREAMHEALTH",
                            dict(state="MALFORMED_MESSAGE", connection_id=tracker.connection_id),
                            now(),
                        )
                        self.last_raw.pop(key, None)
                        self.emit(
                            "D1_SOURCE_GAP",
                            dict(
                                source=path.name,
                                source_event_id=event["id"],
                                reason="MALFORMED_CAPTURE_EXCLUDED",
                            ),
                        )
                    self.cursors[key] = event["id"]
                self.cursors[key] = cursor
            except (sqlite3.Error, OSError, ValueError, TypeError, KeyError, zlib.error):
                self.errors["SOURCE_READ"] = self.errors.get("SOURCE_READ", 0) + 1

    def shared_emit(
        self,
        tracker: BookTracker,
        kind: str,
        payload: dict[str, Any],
        received: datetime,
        key: str | None,
    ) -> None:
        self.normalize(tracker, kind, payload, received)

    def missing_tokens(self) -> list[str]:
        wanted = {
            t
            for m in self.markets.values()
            if m.get("metadata", {}).get("closed") is not True
            for t in m["tokens"].values()
        }
        covered = {
            token
            for key, tracker in self.sources.items()
            if (now() - self.last_raw.get(key, datetime.min.replace(tzinfo=UTC))).total_seconds()
            < 30
            for token in tracker.tokens
        }
        return sorted(t for t in wanted - covered if self.drop_until.get(t, 0) <= time.monotonic())[
            :160
        ]

    def own_emit(
        self, kind: str, payload: dict[str, Any], received: datetime, key: str | None
    ) -> None:
        if kind == "WS_RAW":
            raw = dict(payload)
            if "text" in raw:
                raw.update(
                    encoding="zlib+base64",
                    compressed_text=base64.b64encode(
                        zlib.compress(raw.pop("text").encode())
                    ).decode(),
                )
            self.emit("D1_WS_RAW", raw, received)
        else:
            # An unsubscribe can race an already queued full frame. It cannot
            # invalidate unrelated instruments still subscribed on this socket.
            if kind in {"BOOK", "WS_TRADE"} and payload.get("token_id") not in self.own.tokens:
                return
            if kind == "WS_DELTA":
                changes = [
                    c
                    for c in payload.get("price_changes", [])
                    if c.get("asset_id") in self.own.tokens
                ]
                if not changes:
                    return
                payload = dict(payload, price_changes=changes)
            self.own.observe(kind, payload, received)
            if kind == "STREAMHEALTH":
                self.emit("D1_STREAMHEALTH", payload, received)

    def book(self, token: str, at: datetime) -> dict[str, Any]:
        candidates = [t.view(token, at) for t in [self.own, *self.sources.values()]]
        valid = [b for b in candidates if b["status"] == "VALID"]
        return max(valid, key=lambda b: b["received_at"]) if valid else self.own.view(token, at)

    def snapshot(self) -> None:
        at = now()
        target = (at.astimezone(ZONE).date() + timedelta(days=1)).isoformat()
        combined = consensus(self.forecasts, target, at)
        markets = []
        for market in self.markets.values():
            books = {side: self.book(token, at) for side, token in market["tokens"].items()}
            probability = dict(
                status="CALIBRATION_PENDING",
                yes_probability=None,
                no_probability=None,
                sample_size=0,
                reason="NO_AUDITED_SETTLEMENT_HORIZON_PAIRS_OR_PROMOTION",
            )
            candidate = evaluate_candidate(market, books, probability, at)
            entry = dict(
                market,
                yes_book=books["YES"],
                no_book=books["NO"],
                probability=probability,
                candidate=candidate,
            )
            markets.append(entry)
            self.emit("D1_CANDIDATE", entry, at)
        self.emit(
            "D1_SNAPSHOT",
            dict(
                decision_day=at.astimezone(ZONE).date().isoformat(),
                settlement_date=target,
                markets=markets,
                consensus=combined,
                health=dict(
                    state="RUNNING",
                    pid=os.getpid(),
                    uptime_seconds=time.monotonic() - self.start,
                    own_tokens=len(self.missing_tokens()),
                    source_files=len(self.sources),
                    errors=self.errors,
                ),
                independent_completed_days=0,
            ),
            at,
        )

    async def run(self, seconds: float | None) -> None:
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        async with httpx.AsyncClient(
            timeout=30, verify=context, headers={"User-Agent": "michupl-pre-metar/EXP0016-research"}
        ) as client:
            # Subscribe before any candidate evaluation; fresh full depth is mandatory.
            await self.reuse()
            for label, operation in [("DISCOVERY", self.discover), ("FORECAST", self.forecast)]:
                try:
                    await operation(client)
                except (httpx.HTTPError, ValueError, KeyError, TypeError):
                    self.errors[label] = self.errors.get(label, 0) + 1
                    self.emit(
                        "D1_ERROR", dict(operation=label, error="STARTUP_PUBLIC_SOURCE_FAILURE")
                    )
            streaming = asyncio.create_task(
                stream_market(self.missing_tokens, self.own_emit, self.stop)
            )
            next_discovery, next_forecast, next_snapshot = (
                time.monotonic() + 900,
                time.monotonic() + 1800,
                0.0,
            )
            try:
                while not self.stop.is_set() and (
                    seconds is None or time.monotonic() - self.start < seconds
                ):
                    if (DIRECTORY / "stop.request").exists():
                        break
                    await self.reuse()
                    for token, reason in list(self.own.invalid.items()):
                        if (
                            reason == "INVALID_DEPTH_REQUIRES_SNAPSHOT"
                            and time.monotonic() - self.rechecked.get(token, 0) >= 60
                        ):
                            self.rechecked[token] = time.monotonic()
                            self.drop_until[token] = time.monotonic() + 2
                            self.emit(
                                "D1_DEPTH_RECOVERY",
                                dict(
                                    token=token,
                                    reason=reason,
                                    action="UNSUBSCRIBE_RESUBSCRIBE_FULL_SNAPSHOT",
                                    minimum_retry_seconds=60,
                                ),
                            )
                    for label, due, operation in [
                        ("DISCOVERY", next_discovery, self.discover),
                        ("FORECAST", next_forecast, self.forecast),
                    ]:
                        if time.monotonic() >= due:
                            try:
                                await operation(client)
                            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                                self.errors[label] = self.errors.get(label, 0) + 1
                                self.emit(
                                    "D1_ERROR", dict(operation=label, error="PUBLIC_SOURCE_FAILURE")
                                )
                            if label == "DISCOVERY":
                                next_discovery = time.monotonic() + 900
                            else:
                                next_forecast = time.monotonic() + 1800
                    if time.monotonic() >= next_snapshot:
                        self.snapshot()
                        next_snapshot = time.monotonic() + 30
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(self.stop.wait(), timeout=1)
            finally:
                self.stop.set()
                await streaming


async def watch(seconds: float | None = None) -> None:
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    if (DIRECTORY / "stop.request").exists():
        raise RuntimeError("Own stop marker exists")
    lock_path = DIRECTORY / "monitor.lock"
    lock = acquire(lock_path, uuid4().hex, recover=True)
    store = BattleStore(DIRECTORY)
    try:
        monitor = D1Monitor(store)
        config = default_config()
        source_hashes = {
            name: hashlib.sha256(
                await asyncio.to_thread(Path(__file__).with_name(name).read_bytes)
            ).hexdigest()
            for name in ("d1_monitor.py", "d1_forecasts.py", "d1_strategy.py")
        }
        monitor.emit(
            "D1_RUN",
            dict(
                pid=os.getpid(),
                baseline="d1b93aa",
                source_sha256=hashlib.sha256(
                    await asyncio.to_thread(Path(__file__).read_bytes)
                ).hexdigest(),
                source_hashes=source_hashes,
                config=config,
                config_sha256=hashlib.sha256(
                    json.dumps(config, sort_keys=True).encode()
                ).hexdigest(),
                shadow_only=True,
            ),
        )
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, lambda *_: monitor.stop.set())
        await monitor.run(seconds)
        monitor.emit("D1_STOP", dict(reason="BOUNDED_OR_GRACEFUL_STOP"))
    finally:
        store.close()
        lock.close()
        lock_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["watch", "status", "report"])
    parser.add_argument("--seconds", type=float)
    parser.add_argument("--at")
    args = parser.parse_args()
    if args.command == "watch":
        asyncio.run(watch(args.seconds))
    elif args.command == "report":
        from premetar.research.d1_reports import generate

        print(json.dumps(generate(clock(args.at) if args.at else now()), indent=2))
    else:
        print(json.dumps(view(clock(args.at) if args.at else now()), indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
