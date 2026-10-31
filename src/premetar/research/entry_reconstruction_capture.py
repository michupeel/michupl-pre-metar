"""Bounded EXP0018 paired-book capture, isolated from all existing collectors.

One public socket; metadata/wallet observations are reused read-only. No new HTTP
polling, authentication, orders, service changes or runtime LLM. Frozen watchlist.
"""

import argparse
import asyncio
import contextlib
import hashlib
import json
import shutil
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import uuid4

from premetar.continuous.locking import acquire
from premetar.research.battle_store import BattleStore, StorageLimit
from premetar.research.entry_reconstruction import (
    DIRECTORY,
    Reconstruction,
    settlement_day,
    source_rows,
)
from premetar.research.entry_timing_monitor import TRADER, WEATHER, clock, market_reference
from premetar.research.trader_store import TraderStore, readonly_connection
from premetar.research.trader_stream import stream_market

POLICY = "EXP0018-FROZEN-PAIRS-NO090099-HASH-v1"


def select_watchlist(
    markets: list[dict[str, Any]], at: datetime, limit: int = 16
) -> list[dict[str, Any]]:
    if not 1 <= limit <= 32 or at.utcoffset() is None:
        raise ValueError("Invalid frozen watchlist constraints")
    eligible: dict[str, dict[str, Any]] = {}
    for row in markets:
        p, receipt = row["payload"], clock(row["received_at"])
        if receipt is None or not 0 <= (at - receipt).total_seconds() <= 600:
            continue
        if (
            p.get("closed") is not False
            or p.get("active") is not True
            or p.get("acceptingOrders") is not True
        ):
            continue
        if not str(p.get("slug") or "").startswith(
            ("highest-temperature-in-", "lowest-temperature-in-")
        ):
            continue
        reference = market_reference(p, receipt.isoformat())
        if not reference or not reference.get("station") or not reference.get("condition_id"):
            continue
        try:
            outcomes = p.get("outcomes")
            outcomes = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
            prices = p.get("outcomePrices")
            prices = json.loads(prices) if isinstance(prices, str) else prices
            if (
                not isinstance(prices, list)
                or not isinstance(outcomes, list)
                or len(prices) != len(outcomes)
            ):
                continue
            prices_by_side = {
                str(s).lower(): Decimal(str(v)) for s, v in zip(outcomes, prices, strict=True)
            }
            no_price = prices_by_side["no"]
            if not no_price.is_finite() or not Decimal(".90") <= no_price <= Decimal(".99"):
                continue
        except (ValueError, TypeError, KeyError, InvalidOperation):
            continue
        condition = reference["condition_id"]
        eligible[condition] = dict(
            reference,
            metadata_payload=p,
            metadata_source_event_id=row["id"],
            settlement_day=settlement_day(str(p.get("slug") or "")),
            discovery_no_mark=str(no_price),
            mark_status="DISCOVERY_FILTER_NOT_EXECUTABLE_PRICE",
            rank_hash=hashlib.sha256((POLICY + condition).encode()).hexdigest(),
        )
    return sorted(eligible.values(), key=lambda m: (m["rank_hash"], m["condition_id"]))[:limit]


def metadata_rows(source: Path, at: datetime) -> tuple[int, list[dict[str, Any]]]:
    c = readonly_connection(source)
    try:
        maximum = int(c.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0])
        # Bounded kind/id index query; discovery may be incomplete, never all markets.
        rows = c.execute(
            "SELECT id,received_at,payload FROM events WHERE kind='MARKET' AND id<=? ORDER BY id DESC LIMIT 5000",
            (maximum,),
        ).fetchall()
        rows.reverse()
        return maximum, [
            dict(id=i, received_at=t, payload=json.loads(p))
            for i, t, p in rows
            if (clock(t) or at + timedelta(days=1)) <= at
        ]
    finally:
        c.close()


async def capture(
    duration: float = 60,
    directory: Path = DIRECTORY,
    source: Path = TRADER,
    weather: Path = WEATHER,
) -> dict[str, Any]:
    if not 1 <= duration <= 3600:
        raise ValueError("Only bounded 1..3600 second shadow capture authorized")
    if source.resolve() == (directory / "source.sqlite3").resolve():  # noqa: ASYNC240 -- startup before tasks
        raise ValueError("Capture cannot replace its source")
    directory.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 -- bounded startup before tasks
    lock_path = directory / "monitor.lock"
    lock = acquire(lock_path, str(uuid4()), recover=True)
    journal = None
    raw = None
    try:
        at = datetime.now(UTC)
        cursor, metadata = metadata_rows(source, at)
        selected = select_watchlist(metadata, at)
        if not selected:
            raise ValueError("No eligible frozen paired watchlist in bounded recent metadata")
        capture_id = uuid4().hex
        captures = directory / "books"
        captures.mkdir(exist_ok=True)
        path = captures / f"{at.strftime('%Y%m%dT%H%M%SZ')}-{capture_id}.sqlite3"
        raw = TraderStore(path)
        journal = BattleStore(directory, max_segment_bytes=50_000_000, max_total_bytes=500_000_000)
        monitor = Reconstruction(journal, weather, experimental_deltas=True)
        baseline_counts = dict(monitor.state["reconstruction_counts"])
        # A new socket has a different coverage epoch. Never fill its missing past.
        monitor.state.pop("shutdown_at", None)
        monitor.state["started_at"] = at.isoformat()
        monitor.state["capture_id"] = capture_id
        # Start wallet tail now, never replay older trades as observed in this run.
        monitor.cursors["source"] = cursor
        monitor.state["markets"] = {m["condition_id"]: m for m in selected}
        tokens = sorted({t for m in selected for t in m["tokens"].values()})
        manifest = dict(
            policy=POLICY,
            capture_id=capture_id,
            created_at=at.isoformat(),
            duration=duration,
            source_max_id=cursor,
            source=str(source),
            books_database=str(path),
            markets=selected,
            tokens=tokens,
            coverage="FROZEN_SUBSET_NOT_ALL_WEATHER_MARKETS",
            approval="BOUNDED_SHADOW_ONLY",
        )
        raw.append("RUN", manifest, at, capture_id)
        journal.commit(
            [monitor.event("FROZEN_WATCHLIST", at, manifest)], monitor.state, monitor.cursors, at
        )
        stop = asyncio.Event()
        error_class = None
        counts: dict[str, int] = {}

        def emit(kind: str, payload: dict[str, Any], received: datetime, key: str | None) -> None:
            nonlocal error_class
            # This callback is in the same loop/thread as both independent writers.
            # Existing stream commits WS_RAW before normalization invokes us again.
            if error_class:
                return
            try:
                total = sum(p.stat().st_size for p in captures.glob("*.sqlite3*"))
                if (
                    total >= 500_000_000
                    or path.stat().st_size + Path(str(path) + "-wal").stat().st_size >= 100_000_000
                    or shutil.disk_usage(directory).free < 1_000_000_000
                ):
                    raise StorageLimit("Bounded paired capture budget exhausted")
                raw.append(kind, payload, received, key)
                identity = int(raw.connection.execute("SELECT last_insert_rowid()").fetchone()[0])
                counts[kind] = counts.get(kind, 0) + 1
                if kind == "STREAMHEALTH":
                    state = "STREAM_STATE_" + str(payload.get("state") or "UNKNOWN")
                    counts[state] = counts.get(state, 0) + 1
                if kind in {"BOOK", "WS_DELTA", "STREAMHEALTH", "COVERAGE_GAP"}:
                    row = dict(
                        id=identity,
                        kind=kind,
                        received_at=received.isoformat(),
                        payload=dict(payload, capture_database=str(path), capture_id=capture_id),
                    )
                    events = monitor.ingest(row, received)
                    # Raw/public packet is already committed; derived state may lag.
                    if events:
                        journal.commit(events, monitor.state, monitor.cursors, received)
            except (OSError, ValueError, sqlite3.Error, StorageLimit) as error:
                error_class = type(error).__name__
                stop.set()

        async def tail() -> None:
            nonlocal error_class
            while not stop.is_set():
                try:
                    next_cursor, rows = source_rows(source, monitor.cursors["source"])
                    events = []
                    for row in rows:
                        # Own frozen socket alone supplies books and exact metadata.
                        if row["kind"] in {"TRADE", "ROLE_EVIDENCE", "ENDPOINT_RECEIPT"}:
                            events.extend(monitor.ingest(row, datetime.now(UTC)))
                    monitor.cursors["source"] = next_cursor
                    current = datetime.now(UTC)
                    monitor.state.update(heartbeat=current.isoformat())
                    journal.commit(events, monitor.state, monitor.cursors, current)
                except (OSError, ValueError, sqlite3.Error, StorageLimit) as error:
                    error_class = type(error).__name__
                    stop.set()
                try:
                    await asyncio.wait_for(stop.wait(), 1)
                except TimeoutError:
                    pass

        started = time.monotonic()
        worker = asyncio.create_task(stream_market(lambda: tokens, emit, stop))
        wallet = asyncio.create_task(tail())
        try:
            await asyncio.wait_for(stop.wait(), duration)
        except TimeoutError:
            pass
        finally:
            stop.set()
            await asyncio.gather(worker, wallet, return_exceptions=False)
        ended = datetime.now(UTC)
        if error_class:
            monitor.state, monitor.cursors = journal.restore()
        result = dict(
            capture_id=capture_id,
            policy=POLICY,
            started_at=at.isoformat(),
            ended_at=ended.isoformat(),
            actual_duration_seconds=time.monotonic() - started,
            contracts=len(selected),
            tokens=len(tokens),
            counts=counts,
            reconstruction_counts={
                k: v - baseline_counts.get(k, 0)
                for k, v in monitor.state["reconstruction_counts"].items()
            },
            error_class=error_class,
            operational_status="FAILED"
            if error_class
            else "DEGRADED_RECONNECTS"
            if counts.get("STREAM_STATE_RECONNECTING")
            else "BOUNDED_CAPTURE_COMPLETED",
            source_max_id_start=cursor,
            source_max_id_end=monitor.cursors["source"],
            books_database=str(path),
            integrity=raw.connection.execute("PRAGMA integrity_check").fetchone()[0],
            persistent_activation="NOT_AUTHORIZED_NOT_INSTALLED",
        )
        raw.append("STOP", result, ended)
        monitor.state["shutdown_at"] = ended.isoformat()
        journal.commit(
            [monitor.event("BOUNDED_CAPTURE_STOP", ended, result)],
            monitor.state,
            monitor.cursors,
            ended,
        )
        return result
    finally:
        if raw:
            raw.close()
        if journal:
            journal.close()
        lock.close()
        with contextlib.suppress(OSError):
            lock_path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--directory", type=Path, default=DIRECTORY)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(capture(args.duration, args.directory)), indent=2))


if __name__ == "__main__":
    main()
