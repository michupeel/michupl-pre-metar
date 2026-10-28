"""EXP0013 independent observation sidecar. Public reads only; never submits orders.

Run from repository: uv run python -m premetar.research.forecast_monitor watch
The existing weather and wallet processes are never controlled by this module.
"""

import argparse
import asyncio
import base64
import contextlib
import hashlib
import json
import os
import sqlite3
import ssl
import time
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import truststore

from premetar.continuous.locking import acquire
from premetar.model import icao_round_temperature
from premetar.research.forecast_books import BookTracker
from premetar.research.forecast_windows import TIMEZONES, parse_forecast, windows
from premetar.research.trader_monitor import market_tokens, open_market, verified_fee
from premetar.research.trader_store import TraderStore, read_status, readonly_connection
from premetar.research.trader_stream import stream_market
from premetar.research.trader_weather import weather_context
from premetar.sources import STATIONS, next_report

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data/research/exp0013"
DB = DATA / "observations.sqlite3"
WEATHER = ROOT / "data/continuous-v1.sqlite3"
TRADER = ROOT / "data/trader/monitor.sqlite3"
VERSION = "EXP0013-v1.1"
CITIES = {"warsaw": "EPWA", "amsterdam": "EHAM", "munich": "EDDM", "london": "EGLL"}


def now() -> datetime:
    return datetime.now(UTC)


def clock(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Naive timestamp")
    return parsed.astimezone(UTC)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def forecast_at(
    forecast: dict[str, Any] | None, at: datetime, valid_at: datetime | None = None
) -> dict[str, Any] | None:
    """Last hourly valid value, no interpolation and no later first receipt."""
    if forecast is None or clock(forecast["first_received"]) > at:
        return None
    valid = valid_at or at
    eligible = [
        p
        for p in forecast["points"]
        if 0 <= (valid - clock(p["valid_time"])).total_seconds() < 3600
    ]
    return max(eligible, key=lambda p: p["valid_time"], default=None)


def decision_targets(airport: str, at: datetime) -> list[datetime]:
    future = next_report(STATIONS[airport], at)
    previous = next_report(STATIONS[airport], at - timedelta(minutes=30))
    return [future] + ([previous] if timedelta(0) <= at - previous <= timedelta(seconds=90) else [])


def market_identity(market: dict[str, Any], at: datetime) -> dict[str, Any] | None:
    # Reuse audited explicit rule parsing; city alone never certifies station identity.
    from scripts.research.hightemptation_metadata import market_identity as parse_slug
    from scripts.research.hightemptation_metadata import station_from_rules

    kind, city, day = parse_slug(str(market.get("slug", "")))
    airport = CITIES.get(city)
    if airport is None or day is None or kind != "TMAX" or open_market(market) is not True:
        return None
    local_date = at.astimezone(ZoneInfo(TIMEZONES[airport])).date()
    if not local_date <= day <= local_date + timedelta(days=1):
        return None
    station, evidence = station_from_rules(market)
    tokens = market_tokens(market)
    raw_outcomes = market.get("outcomes")
    outcomes = json.loads(raw_outcomes) if isinstance(raw_outcomes, str) else raw_outcomes
    if len(tokens) != 2 or not isinstance(outcomes, list) or set(outcomes) != {"Yes", "No"}:
        return None
    return dict(
        airport=airport,
        city=city,
        local_date=str(day),
        station=station,
        station_match=station == airport,
        station_evidence=evidence,
        yes=tokens[outcomes.index("Yes")],
        no=tokens[outcomes.index("No")],
        condition_id=market["conditionId"],
        slug=market["slug"],
        settlement_policy="CAPTURED_RULES_NOT_IMPLEMENTED_AS_RESOLUTION_ORACLE",
    )


def candidate_markets(path: Path, at: datetime) -> list[dict[str, Any]]:
    """Short, bounded read of existing metadata; no production writes/long transaction."""
    conn = readonly_connection(path)
    try:
        records = conn.execute(
            "SELECT received_at,payload FROM events WHERE kind='MARKET' ORDER BY id DESC LIMIT 5000"
        ).fetchall()
    finally:
        conn.close()
    seen: set[str] = set()
    result = []
    for received, encoded in records:
        row = json.loads(encoded)
        condition = row.get("conditionId")
        if not condition or condition in seen:
            continue
        seen.add(condition)
        if clock(received) > at:
            continue
        identity = market_identity(row, at)
        if identity:
            result.append({"metadata": row, "identity": identity, "original_received": received})
    # Keep entire two-token instruments; bounded coverage is explicitly disclosed.
    return sorted(
        result,
        key=lambda x: (
            x["identity"]["local_date"],
            x["identity"]["airport"] != "EPWA",
            x["identity"]["slug"],
        ),
    )[:64]


def backup_weather(source: Path, target: Path) -> dict[str, Any]:
    """Supported backup from pinned read-only WAL snapshot; bounded read lifetime."""
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = readonly_connection(source)
    output = sqlite3.connect(target)
    tick = time.monotonic()
    pinned = now()
    try:
        conn.execute("BEGIN")
        conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()

        def budget(status: int, remaining: int, total: int) -> None:
            if time.monotonic() - tick > 15:
                raise TimeoutError("Snapshot budget exceeded")

        conn.backup(output, pages=4096, progress=budget)
        integrity = output.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        output.close()
        conn.close()
    if integrity != "ok":
        raise ValueError("Snapshot integrity failed")
    with target.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    return dict(
        pinned_at=pinned.isoformat(),
        snapshot=str(target),
        integrity=integrity,
        sha256=sha,
        duration_seconds=time.monotonic() - tick,
    )


class Observer:
    def __init__(self, store: TraderStore, client: httpx.AsyncClient) -> None:
        self.store, self.client = store, client
        self.stop = asyncio.Event()
        self.run_id = uuid4().hex
        self.started = now()
        self.calibration_data: dict[str, Any] = {}
        self.tracker = BookTracker()
        self.markets: list[dict[str, Any]] = []
        self.forecasts: dict[str, dict[str, Any]] = {}
        self.declared_windows: dict[str, dict[str, Any]] = {}
        self.next_http: dict[str, datetime] = {}
        self.drop_until: dict[str, datetime] = {}
        self.depth_recheck: dict[str, datetime] = {}
        for event in self.store.events("FORECAST", 200):
            self.forecasts[event["payload"]["airport"]] = event["payload"]
        for event in self.store.events("WINDOW", 10000):
            window = event["payload"]
            if clock(window["end"]) > self.started:
                self.declared_windows[window["window_id"]] = window

    def emit(
        self, kind: str, payload: dict[str, Any], received: datetime, key: str | None = None
    ) -> None:
        if (
            sum(
                p.stat().st_size
                for p in (self.store.path, Path(str(self.store.path) + "-wal"))
                if p.exists()
            )
            > 2_000_000_000
        ):
            self.stop.set()
            return
        if kind == "WS_RAW" and isinstance(payload.get("text"), str):
            text = payload["text"]
            payload = {k: v for k, v in payload.items() if k != "text"}
            payload.update(
                encoding="zlib+base64",
                raw_sha256=hashlib.sha256(text.encode()).hexdigest(),
                compressed_text=base64.b64encode(zlib.compress(text.encode())).decode(),
            )
        # All deltas remain losslessly present in durable WS_RAW, before parsing.
        # Avoid storing a second full JSON projection of every high-rate delta.
        if kind != "WS_DELTA":
            self.store.append(kind, payload, received, key)

    def signal(self, kind: str, inputs: dict[str, Any], key: str) -> None:
        created = now()
        market_context = []
        for market in self.markets:
            identity = market["identity"]
            if identity["airport"] == inputs.get("airport"):
                market_context.append(
                    dict(
                        identity=identity,
                        books={
                            side: self.tracker.view(identity[side], created)
                            for side in ("yes", "no")
                        },
                        weather_market_comparable=identity["station_match"],
                    )
                )
        self.emit(
            "SIGNAL",
            dict(
                kind=kind,
                version=VERSION,
                created_at=created.isoformat(),
                run_id=self.run_id,
                inputs=inputs,
                market_context=market_context,
                trading_instruction=False,
            ),
            created,
            key,
        )

    async def get(self, url: str, params: dict[str, Any] | None = None) -> tuple[Any, datetime]:
        host = httpx.URL(url).host
        if self.next_http.get(host, datetime.min.replace(tzinfo=UTC)) > now():
            raise RuntimeError("HOST_BACKOFF")
        started, tick = now(), time.monotonic()
        response = await self.client.get(url, params=params)
        received = now()
        self.emit(
            "RAW",
            dict(
                url=url,
                params=params,
                request_start=started.isoformat(),
                request_end=received.isoformat(),
                duration_seconds=time.monotonic() - tick,
                status=response.status_code,
                body=response.text,
                body_sha256=hashlib.sha256(response.content).hexdigest(),
            ),
            received,
        )
        if response.status_code == 429:
            try:
                delay = float(response.headers.get("Retry-After", "60"))
            except ValueError:
                delay = 60
            self.next_http[host] = received + timedelta(seconds=max(60, min(86400, delay)))
        response.raise_for_status()
        return response.json(), received

    async def forecasts_once(self) -> None:
        conn = readonly_connection(WEATHER)
        try:
            airports = [
                json.loads(r[0])
                for r in conn.execute("SELECT data_json FROM pws_airports ORDER BY icao")
            ]
        finally:
            conn.close()
        # Explicit model instead of stitched best_match; do not claim exact run binding.
        meta, meta_received = None, None
        try:
            meta, meta_received = await self.get(
                "https://api.open-meteo.com/data/dwd_icon/static/meta.json"
            )
        except (httpx.HTTPError, ValueError, RuntimeError) as error:
            self.emit(
                "ERROR",
                dict(operation="OPTIONAL_MODEL_METADATA", error_class=type(error).__name__),
                now(),
            )
        payload, received = await self.get(
            "https://api.open-meteo.com/v1/forecast",
            dict(
                latitude=",".join(str(a["latitude"]) for a in airports),
                longitude=",".join(str(a["longitude"]) for a in airports),
                hourly="temperature_2m",
                models="icon_global",
                timezone="UTC",
                timeformat="unixtime",
                temperature_unit="celsius",
                past_days=1,
                forecast_days=3,
            ),
        )
        if not isinstance(payload, list) or len(payload) != len(airports):
            raise ValueError("BATCH_LOCATION_MISMATCH")
        for airport, raw in zip(airports, payload, strict=True):
            forecast = parse_forecast(raw, airport["icao"], received)
            forecast.update(
                model="icon_global",
                candidate_model_metadata=meta,
                metadata_received=meta_received.isoformat() if meta_received else None,
                run_binding="UNVERIFIED_CANDIDATE_ONLY",
            )
            prior = self.forecasts.get(airport["icao"])
            old = {p["valid_time"]: p["temperature_c"] for p in prior["points"]} if prior else {}
            revisions = [
                dict(
                    **point,
                    previous_temperature_c=old[point["valid_time"]],
                    delta_c=point["temperature_c"] - old[point["valid_time"]],
                )
                for point in forecast["points"]
                if point["valid_time"] in old and point["temperature_c"] != old[point["valid_time"]]
            ]
            self.emit(
                "FORECAST", forecast, received, digest([airport["icao"], received.isoformat()])
            )
            self.forecasts[airport["icao"]] = forecast
            if revisions:
                self.emit(
                    "REVISION",
                    dict(
                        airport=airport["icao"],
                        previous_received=prior["first_received"] if prior else None,
                        revisions=revisions,
                    ),
                    received,
                )
                if any(
                    abs(r["delta_c"]) >= 0.5 and clock(r["valid_time"]) > received
                    for r in revisions
                ):
                    self.signal(
                        "FORECAST_REVISION",
                        dict(
                            airport=airport["icao"],
                            revisions=revisions,
                            forecast_received=received.isoformat(),
                        ),
                        digest(revisions + [received.isoformat()]),
                    )
            for window in windows(forecast, now()):
                self.declared_windows[window["window_id"]] = window
                self.emit("WINDOW", window, now(), window["window_id"])
            self.signal(
                "FORECAST_TRANSITION_PENDING",
                dict(
                    airport=airport["icao"],
                    forecast_received=received.isoformat(),
                    windows_frozen=len(windows(forecast, now())),
                ),
                digest([airport["icao"], received.isoformat(), "forecast"]),
            )

    async def markets_once(self) -> None:
        cached = await asyncio.to_thread(candidate_markets, TRADER, now())
        refreshed = []
        for candidate in cached:
            condition = candidate["identity"]["condition_id"]
            try:
                data, received = await self.get(
                    "https://gamma-api.polymarket.com/markets",
                    {"condition_ids": condition, "closed": "any"},
                )
                if (
                    not isinstance(data, list)
                    or len(data) != 1
                    or data[0].get("conditionId") != condition
                ):
                    raise ValueError("MARKET_MISMATCH")
                identity = market_identity(data[0], received)
                if identity is None:
                    continue
                candidate = dict(
                    metadata=data[0], identity=identity, original_received=received.isoformat()
                )
                self.emit("MARKET", candidate, received)
                refreshed.append(candidate)
            except (httpx.HTTPError, ValueError, RuntimeError) as error:
                self.emit(
                    "ERROR",
                    dict(operation="MARKET", condition=condition, error_class=type(error).__name__),
                    now(),
                )
            await asyncio.sleep(0.1)
        self.markets = refreshed
        self.emit(
            "COVERAGE",
            dict(
                markets=len(refreshed),
                tokens=len(self.tokens()),
                coverage="BOUNDED_EXISTING_MONITOR_UNIVERSE_NOT_ALL_LISTED_MARKETS",
                identities=[m["identity"] for m in refreshed],
            ),
            now(),
        )

    def tokens(self) -> list[str]:
        at = now()
        return [
            m["identity"][side]
            for m in self.markets
            for side in ("yes", "no")
            if self.drop_until.get(m["identity"][side], at) <= at
        ]

    def stream_emit(
        self, kind: str, payload: dict[str, Any], received: datetime, key: str | None
    ) -> None:
        self.emit(kind, payload, received, key)
        changes = self.tracker.observe(kind, payload, received)
        for token, reason in list(self.tracker.invalid.items()):
            if (
                reason == "INVALID_DEPTH_REQUIRES_SNAPSHOT"
                and (
                    received - self.depth_recheck.get(token, datetime.min.replace(tzinfo=UTC))
                ).total_seconds()
                >= 60
            ):
                self.depth_recheck[token] = received
                self.drop_until[token] = received + timedelta(seconds=1)
                self.emit(
                    "DEPTH_RECOVERY",
                    dict(
                        token=token,
                        reason=reason,
                        action="UNSUBSCRIBE_THEN_RESUBSCRIBE_REQUESTS_NEW_FULL_SNAPSHOT",
                        minimum_retry_seconds=60,
                    ),
                    received,
                )
        for change in changes:
            self.signal("ORDERBOOK_REPRICING_DETECTED", change, digest([self.run_id, change]))

    async def weather_once(self) -> None:
        at = now()
        for city, airport in CITIES.items():
            context = await asyncio.to_thread(
                weather_context, WEATHER, {"slug": city, "trade_id": VERSION}, at
            )
            self.emit("WEATHER_CONTEXT", context, now())
            point = forecast_at(self.forecasts.get(airport), at)
            reports = context.get("metar", [])
            for report in reports:
                received = clock(report["collector_receive_time"])
                prior_forecast = self.prior_forecast(airport, received)
                self.signal(
                    "METAR_CONTEXT_DISCOVERED"
                    if received < self.started
                    else "METAR_UPDATE_RECEIVED",
                    dict(
                        airport=airport,
                        report=report,
                        forecast=forecast_at(prior_forecast, received, clock(report["event_time"])),
                        prior_available_forecast_received=prior_forecast["first_received"]
                        if prior_forecast
                        else None,
                        startup_censored=received < self.started,
                        notification_semantics="POLL_DISCOVERY_AFTER_ORIGINAL_FIRST_RECEIPT",
                    ),
                    digest([VERSION, airport, report["id"]]),
                )
            for reading in context.get("pws", []):
                raw = reading["temperature_c"]
                calibrated = reading.get("stored_causal_corrected_temperature_c")
                # Stored parameters may use another minimum/window. Do not silently certify CAL2.
                self.signal(
                    "PWS_MEASUREMENT_RECEIVED",
                    dict(
                        airport=airport,
                        reading=reading,
                        raw_integer=icao_round_temperature(raw),
                        stored_corrected_c=calibrated,
                        calibration_status="STORED_CAUSAL_CONTEXT_ONLY_CAL2_NOT_CERTIFIED",
                        forecast=point,
                        disagreement_raw_c=None if point is None else raw - point["temperature_c"],
                    ),
                    digest([VERSION, airport, reading["id"]]),
                )
                for target in decision_targets(airport, at):
                    self.calibrated_signal(airport, reading, reports, at, point, target)
        for airport in STATIONS:
            nominal = next_report(STATIONS[airport], at)
            start = nominal - timedelta(minutes=3)
            if start > at:
                w = dict(
                    kind="SCHEDULED_METAR",
                    airport=airport,
                    event_time=nominal.isoformat(),
                    start=start.isoformat(),
                    end=(nominal + timedelta(minutes=3)).isoformat(),
                    created_at=at.isoformat(),
                    window_id=digest([airport, nominal.isoformat(), VERSION]),
                    version=VERSION,
                )
                self.declared_windows[w["window_id"]] = w
                self.emit("WINDOW", w, at, w["window_id"])

    def prior_forecast(self, airport: str, cutoff: datetime) -> dict[str, Any] | None:
        for event in reversed(self.store.events("FORECAST", 1000)):
            row: dict[str, Any] = event["payload"]
            if row["airport"] == airport and clock(row["first_received"]) <= cutoff:
                return row
        return None

    async def calibration_once(self) -> None:
        from scripts.research.forecast_weather_context import load_snapshot

        cache = DATA / "calibration_cache.sqlite3"
        # SQLite backup replaces its own cache transactionally, preserving WAL
        # correctness; never file-copy/rename a database with sidecars.
        evidence = await asyncio.to_thread(backup_weather, WEATHER, cache)
        self.calibration_data = await asyncio.to_thread(
            load_snapshot, cache, clock(evidence["pinned_at"])
        )
        self.emit("CALIBRATION_CACHE", evidence, now())

    def calibrated_signal(
        self,
        airport: str,
        reading: dict[str, Any],
        reports: list[dict[str, Any]],
        at: datetime,
        forecast: dict[str, Any] | None,
        target: datetime | None = None,
    ) -> None:
        from scripts.research.early_metar_data import calibration

        sensor = self.calibration_data.get(airport, {}).get("sensors", {}).get(reading["sensor_id"])
        if not sensor:
            return
        target = target or next_report(STATIONS[airport], at)
        # weather_context excludes future-event reports; independently check early
        # targets across all providers before making a prospective signal.
        conn = readonly_connection(WEATHER)
        try:
            known = conn.execute(
                "SELECT MIN(rr.collector_receive_time) FROM observations o JOIN report_receipts rr ON rr.observation_id=o.id WHERE o.station_icao=? AND o.product_type='METAR' AND julianday(o.event_time)=julianday(?)",
                (airport, target.isoformat()),
            ).fetchone()[0]
        finally:
            conn.close()
        if known and clock(known) <= at:
            return
        params = calibration(sensor, "CAL-2", target, at)
        if params is None:
            return
        previous = max(
            (
                r
                for r in reports
                if r.get("product_type") == "METAR"
                and r["temperature_c"] is not None
                and clock(r["event_time"]) < target
            ),
            key=lambda r: r["event_time"],
            default=None,
        )
        if previous is None:
            return
        corrected = reading["temperature_c"] - params["offset_c"]
        predicted = icao_round_temperature(corrected)
        old = icao_round_temperature(previous["temperature_c"])
        kind = (
            "PWS_CONFIRMS_UPWARD_TRANSITION"
            if predicted > old
            else "PWS_CONFIRMS_DOWNWARD_TRANSITION"
            if predicted < old
            else "PWS_CONFIRMS_UNCHANGED"
        )
        inputs = dict(
            airport=airport,
            sensor_id=reading["sensor_id"],
            reading=reading,
            calibration=params,
            target=target.isoformat(),
            predicted_metar_integer=predicted,
            previous_metar_integer=old,
            calibrated_temperature_c=corrected,
            boundary_distance_c=0.5 - abs(corrected - predicted),
            previous_report=previous,
            forecast=forecast,
            experiment="EXP_A" if at < target else "EXP_B",
            availability_cutoff=at.isoformat(),
            calibration_semantics="CAUSAL_QUANTIZED_REFERENCE_MIDPOINT_ESTIMATE",
        )
        self.signal(
            kind, inputs, digest([VERSION, airport, reading["id"], "CAL2", target.isoformat()])
        )
        if forecast and predicted != icao_round_temperature(forecast["temperature_c"]):
            self.signal(
                "PWS_DISAGREES_WITH_FORECAST",
                inputs,
                digest([VERSION, airport, reading["id"], "disagree", target.isoformat()]),
            )

    async def diagnostics_once(self) -> None:
        at = now()
        if (DATA / "stop.request").exists():
            self.stop.set()
        self.declared_windows = {
            key: w for key, w in self.declared_windows.items() if clock(w["end"]) > at
        }
        for market in self.markets:
            ident = market["identity"]
            active = [
                w["window_id"]
                for w in self.declared_windows.values()
                if ident["station_match"]
                and w["airport"] == ident["airport"]
                and clock(w["start"]) <= at < clock(w["end"])
            ]
            books = {side: self.tracker.view(ident[side], at) for side in ("yes", "no")}
            opportunities = self.tracker.opportunities(
                ident["yes"], ident["no"], at, ident["condition_id"]
            )
            fee = verified_fee(market["metadata"])
            self.emit(
                "BOOK_SAMPLE",
                dict(
                    identity=ident,
                    books=books,
                    opportunities=opportunities,
                    window_ids=active,
                    period=("WINDOW" if active else "CONTROL")
                    if ident["station_match"]
                    else "STATION_MISMATCH_NOT_COMPARABLE",
                    fee_status="VERIFIED_ZERO_CURRENT" if fee else "UNKNOWN",
                    economic_status="NO_EXECUTION_SIMULATION_RULE_FROZEN",
                    captured_at=at.isoformat(),
                ),
                at,
            )
        self.emit(
            "HEALTH",
            dict(
                state="RUNNING",
                run_id=self.run_id,
                pid=os.getpid(),
                tokens=len(self.tokens()),
                markets=len(self.markets),
                forecasts=list(self.forecasts),
                frozen_windows=len(self.declared_windows),
                clock="UNKNOWN_NOT_CHANGED",
            ),
            at,
        )

    async def outcomes_once(self) -> None:
        """Append separate initial/corrected outcomes, never rewrite a signal."""
        conn = readonly_connection(WEATHER)
        try:
            for event in self.store.events("SIGNAL", 5000):
                signal = event["payload"]
                inputs = signal.get("inputs", {})
                if signal.get("version") != VERSION or "predicted_metar_integer" not in inputs:
                    continue
                records = conn.execute(
                    "SELECT o.identity,o.event_time,o.temperature_c,o.data_json,MIN(rr.collector_receive_time) first_received FROM observations o JOIN report_receipts rr ON rr.observation_id=o.id WHERE o.station_icao=? AND o.product_type='METAR' AND julianday(o.event_time)=julianday(?) GROUP BY o.identity ORDER BY first_received",
                    (inputs["airport"], inputs["target"]),
                ).fetchall()
                if not records:
                    continue
                closure = min(clock(row[4]) for row in records)
                created = clock(signal["created_at"])
                for identity, nominal, temperature, encoded, received in records:
                    if temperature is None or clock(received) > now():
                        continue
                    self.emit(
                        "OUTCOME",
                        dict(
                            signal_id=event["id"],
                            report_identity=identity,
                            report_nominal=nominal,
                            report_first_received=received,
                            target_first_received=closure.isoformat(),
                            correction=bool(json.loads(encoded).get("cor")),
                            prospective_valid=created < closure,
                            status="AVAILABLE"
                            if created < closure
                            else "EXCLUDED_ALREADY_RECEIVED",
                            exact_match=inputs["predicted_metar_integer"] == temperature,
                            persistence_match=inputs["previous_metar_integer"] == temperature,
                            observed_temperature_c=temperature,
                            experiment="EXP_A" if created < clock(nominal) else "EXP_B",
                            lead_seconds=(closure - created).total_seconds(),
                        ),
                        now(),
                        digest([event["id"], identity]),
                    )
        finally:
            conn.close()

    async def loop(self, name: str, operation: Any, interval: float) -> None:
        while not self.stop.is_set():
            tick = time.monotonic()
            try:
                await operation()
            except Exception as error:
                self.emit("ERROR", dict(operation=name, error_class=type(error).__name__), now())
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self.stop.wait(), timeout=max(1, interval - (time.monotonic() - tick))
                )


async def watch(duration: float = 86400, database: Path = DB) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    if (DATA / "stop.request").exists():
        raise RuntimeError("Research stop.request exists; no process started")
    lock_path = DATA / "observer.lock"
    lock = acquire(lock_path, uuid4().hex, recover=True)
    database = await asyncio.to_thread(database.resolve)
    if database.parent != DATA or database.suffix != ".sqlite3":
        lock.close()
        lock_path.unlink(missing_ok=True)
        raise ValueError("Research database segment must be inside EXP0013 directory")
    store = TraderStore(database)
    stop: asyncio.Event | None = None
    tasks: list[asyncio.Task[Any]] = []
    try:
        async with httpx.AsyncClient(
            timeout=20,
            verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
            headers={"User-Agent": "michupl-pre-metar EXP0013 noncommercial research"},
        ) as client:
            observer = Observer(store, client)
            stop = observer.stop
            observer.emit(
                "RUN",
                dict(
                    run_id=observer.run_id,
                    pid=os.getpid(),
                    version=VERSION,
                    started_at=now().isoformat(),
                    max_duration_seconds=duration,
                    existing_weather_db_mode="READ_ONLY",
                    existing_trader_db_mode="READ_ONLY",
                    protocol_sha256=hashlib.sha256(
                        (ROOT / "docs/research/EXP0013_PROTOCOL.md").read_bytes()
                    ).hexdigest(),
                ),
                now(),
            )
            tasks = [
                asyncio.create_task(observer.loop("FORECAST", observer.forecasts_once, 1800)),
                asyncio.create_task(observer.loop("MARKETS", observer.markets_once, 600)),
                asyncio.create_task(observer.loop("WEATHER", observer.weather_once, 30)),
                asyncio.create_task(
                    observer.loop("CALIBRATION_CACHE", observer.calibration_once, 3600)
                ),
                asyncio.create_task(observer.loop("DIAGNOSTICS", observer.diagnostics_once, 5)),
                asyncio.create_task(observer.loop("OUTCOMES", observer.outcomes_once, 60)),
                asyncio.create_task(
                    stream_market(observer.tokens, observer.stream_emit, observer.stop)
                ),
            ]
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(observer.stop.wait(), timeout=duration)
    finally:
        if stop:
            stop.set()
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=10)
            for task in pending:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        store.append(
            "STOP", dict(reason="BOUNDED_DURATION_OR_SHUTDOWN", stopped_at=now().isoformat()), now()
        )
        store.close()
        lock.close()
        lock_path.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["watch", "status", "snapshot"])
    parser.add_argument("--duration", type=float, default=86400)
    parser.add_argument(
        "--database",
        type=Path,
        default=DB,
        help="Append-only EXP0013 segment; same global instance lock",
    )
    args = parser.parse_args()
    if args.command == "status":
        print(json.dumps(read_status(args.database), indent=2))
    elif args.command == "snapshot":
        result = backup_weather(WEATHER, DATA / f"weather_{now():%Y%m%dT%H%M%S}.sqlite3")
        print(json.dumps(result, indent=2))
    elif args.duration < 1 or args.duration > 604800:
        parser.error("Duration must be between1second and7days")
    else:
        asyncio.run(watch(args.duration, args.database))
