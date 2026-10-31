"""EXP0018 isolated, bounded observer of existing immutable public-data captures.

No network client, source writes, trading, service installation or model calls.
The EXP0017 observer supplies exact identity/receipt/weather semantics unchanged.
"""

import argparse
import contextlib
import json
import os
import re
import signal
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import uuid4

from premetar.continuous.locking import acquire
from premetar.research.battle_store import BattleStore
from premetar.research.entry_reconstruction_books import BookRing
from premetar.research.entry_reconstruction_clocks import known_clock
from premetar.research.entry_reconstruction_controls import match_controls
from premetar.research.entry_reconstruction_features import price_changes, snapshot_features
from premetar.research.entry_timing_monitor import (
    KINDS,
    ROOT,
    TRADER,
    WEATHER,
    Monitor,
    clock,
)
from premetar.research.trader_store import readonly_connection

VERSION = "EXP0018-SNAPSHOT-RECONSTRUCTION-v1"
DIRECTORY = ROOT / "data/research/exp0018/live"
MONTHS = (
    "january february march april may june july august september october november december".split()
)


def settlement_day(slug: str) -> str | None:
    """Explicit date in weather-market slug, not endDate/UTC settlement inference."""
    match = re.search(r"-(" + "|".join(MONTHS) + r")-(\d{1,2})-(\d{4})(?:-|$)", slug)
    if not match:
        return None
    month, day, year = match.groups()
    try:
        return datetime(int(year), MONTHS.index(month) + 1, int(day), tzinfo=UTC).date().isoformat()
    except ValueError:
        return None


def source_rows(path: Path, after: int | None) -> tuple[int, list[dict[str, Any]]]:
    """Short indexed read. RAW bytes are not decoded or copied."""
    connection = readonly_connection(path)
    try:
        connection.execute("PRAGMA busy_timeout=250")
        if after is None:
            return int(
                connection.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0]
            ), []
        kinds = sorted(KINDS | {"WS_DELTA"})
        marks = ",".join("?" for _ in kinds)
        rows = connection.execute(
            f"SELECT id,kind,received_at,CASE WHEN kind IN ({marks}) THEN payload END "
            "FROM events WHERE id>? ORDER BY id LIMIT 1000",
            (*kinds, after),
        ).fetchall()
        decoded = []
        for identity, kind, receipt, text in rows:
            if text is None:
                continue
            try:
                payload = json.loads(text)
                if not isinstance(payload, dict):
                    raise ValueError("Nonobject payload")
            except (ValueError, TypeError):
                kind, payload = "COVERAGE_GAP", {"reason": "LOCAL_SOURCE_JSON_INVALID"}
            decoded.append(dict(id=identity, kind=kind, received_at=receipt, payload=payload))
        return (rows[-1][0] if rows else after), decoded
    finally:
        connection.close()


def window_quality(history: list[dict[str, Any]], cutoff: datetime) -> dict[str, Any]:
    """Snapshots at all horizons do not prove continuity or executable depth."""
    parsed_times = [clock(p["received_at"]) for p in history]
    times = sorted(t for t in parsed_times if t is not None and t <= cutoff)
    result: dict[str, Any] = {"snapshot_count": len(times), "continuous_depth_verified": False}
    for seconds in (10, 60, 300):
        start = cutoff - timedelta(seconds=seconds)
        selected = [t for t in times if t >= start - timedelta(seconds=10)]
        gaps = [(b - a).total_seconds() for a, b in zip(selected, selected[1:], strict=False)]
        result[f"window_{seconds}s"] = (
            "SNAPSHOTS_COVER_HORIZON_NOT_CONTINUITY_PROOF"
            if selected
            and selected[0] <= start
            and selected[-1] >= cutoff - timedelta(seconds=10)
            and max(gaps, default=0) <= 10
            else "PARTIAL_OR_MISSING"
        )
    result["largest_recorded_gap_seconds"] = max(
        ((b - a).total_seconds() for a, b in zip(times, times[1:], strict=False)), default=None
    )
    return result


class Reconstruction(Monitor):
    """Reuse baseline event semantics; only this experiment's journal is written."""

    def __init__(
        self, store: BattleStore, weather: Path = WEATHER, experimental_deltas: bool = False
    ) -> None:
        self.ring = BookRing()
        self.experimental_deltas = experimental_deltas
        super().__init__(store, weather)
        # Never restore pre-crash depth certification, even from an intact checkpoint.
        self.state["books"] = {}
        self.state["experiment"] = VERSION
        self.state.setdefault("control_pending", [])
        self.state.setdefault("control_trade_receipts", [])
        self.state.setdefault("reconstruction_counts", {})
        self.state.setdefault("reconstruction_pending", [])

    def count(self, name: str) -> None:
        counts = self.state["reconstruction_counts"]
        counts[name] = counts.get(name, 0) + 1

    def book(self, token: str, at: datetime) -> dict[str, Any] | None:
        return self.ring.latest(token, at)

    def opportunities(self, at: datetime) -> list[dict[str, Any]]:
        candidates = []
        for condition, market in self.state["markets"].items():
            if (clock(market["metadata_received_at"]) or at + timedelta(days=1)) > at:
                continue
            book = self.book(market["tokens"]["no"], at)
            f = snapshot_features(book)
            if book and f["ask"] is not None and 0.90 <= f["ask"] <= 0.99:
                candidates.append(
                    dict(
                        condition_id=condition,
                        station=market.get("station"),
                        settlement_day=market.get("settlement_day"),
                        received_at=book["received_at"],
                        price=f["ask"],
                        spread=f["spread"],
                        depth=f["ask_depth"],
                    )
                )
        return candidates

    def ingest(self, row: dict[str, Any], at: datetime) -> list[dict[str, Any]]:
        receipt, p, kind = clock(row.get("received_at")), row["payload"], row["kind"]
        if receipt is None or receipt > at:
            self.count("invalid_source_clock")
            return [self.event("SOURCE_TIME_REJECTED", at, dict(source_event_id=row["id"]))]
        if kind == "BOOK":
            valid = self.ring.add(row)
            self.count("book_snapshots" if valid else "invalid_books")
            if not valid:
                self.ring.invalidate(str(p.get("token_id") or ""))
        elif kind == "WS_DELTA":
            if self.experimental_deltas:
                updates = self.ring.delta(row)
                self.count("delta_packets")
                if updates:
                    self.count("delta_packets_with_valid_seed_and_bbo")
                return self.post_windows(receipt, at)
            changes = p.get("price_changes")
            if not isinstance(changes, list) or not changes:
                self.ring.invalidate()
            else:
                for change in changes:
                    token = change.get("asset_id") if isinstance(change, dict) else None
                    self.ring.invalidate(str(token) if token else None)
            self.count("delta_invalidations")
            return []
        elif kind in {"COVERAGE_GAP", "STREAMHEALTH"}:
            # PONG never certifies depth. Subscription changes/reconnect/gaps reset it.
            connection = p.get("connection_id")
            changed = connection is not None and self.state.get(
                "reconstruction_connection"
            ) not in (None, connection)
            if p.get("state") == "SUBSCRIPTIONS_CHANGED" and not changed:
                selected = p.get("tokens")
                if isinstance(selected, list):
                    for token in list(self.ring.histories):
                        if token not in selected:
                            self.ring.invalidate(token)
                else:
                    self.ring.invalidate()
                    self.count("coverage_resets")
            elif (
                kind == "COVERAGE_GAP"
                or changed
                or p.get("state") not in {"CONNECTED", "HEALTHY", "PONG"}
            ):
                self.ring.invalidate()
                self.count("coverage_resets")
            if connection is not None:
                self.state["reconstruction_connection"] = connection
        elif kind == "TRADE":
            self.state["control_trade_receipts"] = (
                self.state["control_trade_receipts"]
                + [
                    dict(
                        condition_id=p.get("condition_id"),
                        execution=p.get("source_trade_timestamp"),
                        receipt=p.get("first_collector_receipt_utc"),
                    )
                ]
            )[-10000:]
        events = super().ingest(row, at)
        if kind == "BOOK":
            events.extend(self.post_windows(receipt, at))
        if kind == "MARKET":
            condition = str(p.get("conditionId") or "")
            if condition in self.state["markets"]:
                self.state["markets"][condition]["settlement_day"] = settlement_day(
                    str(p.get("slug") or "")
                )
        for event in list(events):
            if event["kind"] != "ENTRY_OBSERVED":
                continue
            entry = event["payload"]
            try:
                price = Decimal(str(entry.get("price")))
                if not price.is_finite() or not Decimal("0.90") <= price <= Decimal("0.99"):
                    continue
            except InvalidOperation:
                continue
            source = clock(entry["source_trade_timestamp"])
            detection = clock(entry["original_first_detection"])
            assert source is not None and detection is not None
            # Strictly before earliest possible execution in a one-second source bin.
            cutoff = source - timedelta(microseconds=1)
            market = entry.get("metadata")
            market_known = market and (clock(market["metadata_received_at"]) or at) <= cutoff
            tokens = {
                "no": str(p["token_id"]),
                "yes": market["tokens"]["yes"] if market_known else None,
            }
            windows: dict[str, Any] = {}
            for side, token in tokens.items():
                history = self.ring.window(token, detection) if token else []
                pre = [b for b in history if known_clock(b["received_at"]) <= cutoff]
                latest = self.book(token, cutoff) if token else None
                windows[side] = dict(
                    token_id=token,
                    history=history,
                    pre_execution_quality=window_quality(pre, cutoff),
                    pre_execution=snapshot_features(latest),
                    pre_execution_received_at=latest.get("received_at") if latest else None,
                    pre_execution_source_event_id=latest.get("source_event_id") if latest else None,
                    price_changes=price_changes(pre, cutoff.isoformat()),
                    at_detection=snapshot_features(self.book(token, detection) if token else None),
                )
            data = dict(
                version=VERSION,
                trade_id=entry["trade_id"],
                source_event_id=row["id"],
                source_trade_timestamp=source.isoformat(),
                original_first_detection=detection.isoformat(),
                sidecar_capture_time=at.isoformat(),
                evidence_class="PROSPECTIVE_SOURCE_CAPTURE_RESEARCH_RECONSTRUCTION",
                source_evidence_class=entry["evidence_class"],
                decision_signal_status="NOT_GENERATED_RULE_NOT_PROMOTED",
                pre_execution_cutoff=cutoff.isoformat(),
                price=str(price),
                quantity=entry["quantity"],
                condition_id=p.get("condition_id"),
                station=market.get("station") if market else None,
                market=market,
                metadata_known_pre_execution=bool(market_known),
                books=windows,
                metar_schedule=entry["metar_schedule"],
                weather_at_execution=entry["weather"],
                source_timestamp_precision_seconds=entry["source_timestamp_precision_seconds"],
                order_placement_time=None,
                role=entry.get("role_evidence_available_at_detection"),
                forecast_context="UNKNOWN_NOT_RECONSTRUCTED_FROM_LATER_FORECASTS",
                complementary_path="THEORETICAL_ONLY_NO_FEE_OR_EXECUTABLE_PATH_PROOF",
                fill_feasibility="NOT_IDENTIFIABLE_FROM_SNAPSHOTS_OR_QUOTES",
                book_mode="EXPERIMENTAL_BBO_CHECKED_DELTAS"
                if self.experimental_deltas
                else "FULL_SNAPSHOTS_ONLY",
            )
            self.count("entries")
            if (
                windows["no"]["pre_execution"]["mid"] is not None
                and windows["yes"]["pre_execution"]["mid"] is not None
            ):
                self.count("paired_pre_execution")
            events.append(self.event("ENTRY_RECONSTRUCTION", at, data))
            pending = dict(
                trade_id=entry["trade_id"],
                execution=source.isoformat(),
                tokens=tokens,
                remaining=[10, 60, 300],
            )
            if len(self.state["reconstruction_pending"]) >= 100:
                evicted = self.state["reconstruction_pending"].pop(0)
                events.append(self.event("FOLLOWUP_CAPACITY_CENSORED", at, evicted))
            self.state["reconstruction_pending"].append(pending)
            if market_known:
                f = windows["no"]["at_detection"]
                current = dict(
                    condition_id=p.get("condition_id"),
                    station=market.get("station"),
                    settlement_day=market.get("settlement_day"),
                    received_at=detection.isoformat(),
                    price=f["ask"],
                    spread=f["spread"],
                    depth=f["ask_depth"],
                )
                for control in match_controls(current, self.opportunities(detection)):
                    control.update(
                        entry_trade_id=entry["trade_id"],
                        attribution_deadline=(detection + timedelta(seconds=300)).isoformat(),
                    )
                    self.state["control_pending"].append(control)
                    events.append(self.event("MATCHED_CONTROL_CANDIDATE", at, control))
                self.state["control_pending"] = self.state["control_pending"][-100:]
        return events

    def post_windows(self, receipt: datetime, at: datetime) -> list[dict[str, Any]]:
        events = []
        remaining = []
        for pending in self.state["reconstruction_pending"]:
            execution = known_clock(pending["execution"])
            for seconds in list(pending["remaining"]):
                target = execution + timedelta(seconds=seconds)
                if receipt < target:
                    continue
                books = {
                    side: self.book(token, receipt) if token else None
                    for side, token in pending["tokens"].items()
                }
                books = {
                    side: b if b and known_clock(b["received_at"]) >= target else None
                    for side, b in books.items()
                }
                if not any(books.values()) and receipt < target + timedelta(seconds=10):
                    continue
                events.append(
                    self.event(
                        "ENTRY_POST_WINDOW",
                        at,
                        dict(
                            trade_id=pending["trade_id"],
                            requested_offset_seconds=seconds,
                            source_receipt=receipt.isoformat(),
                            actual_offset_seconds=(receipt - execution).total_seconds(),
                            books=books,
                            status="RECORDED_AFTER_TARGET"
                            if any(books.values())
                            else "MISSING_OR_STALE",
                        ),
                    )
                )
                pending["remaining"].remove(seconds)
            if pending["remaining"]:
                remaining.append(pending)
        self.state["reconstruction_pending"] = remaining
        return events

    def control_outcomes(self, at: datetime) -> list[dict[str, Any]]:
        events = []
        pending = []
        for item in self.state["control_pending"]:
            deadline = clock(item["attribution_deadline"])
            if deadline is None or at < deadline:
                pending.append(item)
                continue
            cutoff = clock(item["matched_at"])
            assert cutoff is not None
            matching = [
                t
                for t in self.state["control_trade_receipts"]
                if t["condition_id"] == item["condition_id"]
                and clock(t["execution"]) is not None
                and abs((known_clock(t["execution"]) - cutoff).total_seconds()) <= 300
            ]
            events.append(
                self.event(
                    "CONTROL_ATTRIBUTION_REVIEW",
                    at,
                    dict(
                        **item,
                        attribution_status="ENTRY_OBSERVED_IN_WINDOW"
                        if matching
                        else "NO_ENTRY_OBSERVED_WITHIN_300S_DELAY_CENSOR_REMAINS",
                        no_entry_proven=False,
                        matched_trade_receipts=matching,
                    ),
                )
            )
        self.state["control_pending"] = pending
        return events

    def cycle(self, source: Path, at: datetime) -> None:
        previous = self.cursors.get("source")
        cursor, rows = source_rows(source, previous)
        events = []
        if previous is None:
            events.append(
                self.event(
                    "CENSORED_STARTUP",
                    at,
                    dict(source_cursor=cursor, source=str(source), version=VERSION),
                )
            )
        else:
            for row in rows:
                receipt = clock(row.get("received_at"))
                if receipt is not None and at < receipt <= at + timedelta(seconds=5):
                    # Source appended during this read: retry next cycle, never lose
                    # an otherwise valid packet to our earlier cycle-start clock.
                    cursor = row["id"] - 1
                    break
                events.extend(self.ingest(row, at))
        events.extend(self.followups(at))
        events.extend(self.control_outcomes(at))
        self.state.update(heartbeat=at.isoformat(), pid=os.getpid())
        self.cursors["source"] = cursor
        self.store.commit(events, self.state, self.cursors, at)


def watch(
    duration: float = 60,
    directory: Path = DIRECTORY,
    source: Path = TRADER,
    weather: Path = WEATHER,
    experimental_deltas: bool = False,
) -> None:
    """Finite shadow observation only; persistent activation requires separate approval."""
    if not 1 <= duration <= 3600:
        raise ValueError("Bounded runs require 1..3600 seconds")
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / "monitor.lock"
    lock = acquire(lock_path, str(uuid4()), recover=True)
    store = None
    stopping = False

    def stop(signum: int, frame: Any) -> None:
        nonlocal stopping
        stopping = True

    previous_handlers = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        store = BattleStore(directory, max_segment_bytes=50_000_000, max_total_bytes=500_000_000)
        observer = Reconstruction(store, weather, experimental_deltas)
        observer.state.pop("shutdown_at", None)
        observer.state["started_at"] = datetime.now(UTC).isoformat()
        at = datetime.now(UTC)
        store.commit(
            [
                observer.event(
                    "START_OR_RESTART_COVERAGE_GAP",
                    at,
                    dict(pid=os.getpid(), duration=duration, version=VERSION),
                )
            ],
            observer.state,
            observer.cursors,
            at,
        )
        started = time.monotonic()
        while (
            not stopping
            and time.monotonic() - started < duration
            and not (directory / "stop.request").exists()
        ):
            try:
                observer.cycle(source, datetime.now(UTC))
            except (sqlite3.Error, ValueError, OSError) as error:
                # Failed source/commit changes must not advance durable cursors.
                observer = Reconstruction(store, weather, experimental_deltas)
                at = datetime.now(UTC)
                store.commit(
                    [
                        observer.event(
                            "CYCLE_FAILED_COVERAGE_GAP", at, dict(error_class=type(error).__name__)
                        )
                    ],
                    observer.state,
                    observer.cursors,
                    at,
                )
            time.sleep(min(1, max(0, duration - (time.monotonic() - started))))
        at = datetime.now(UTC)
        observer.state["shutdown_at"] = at.isoformat()
        store.commit(
            [observer.event("STOP", at, dict(reason="BOUNDED_DURATION_SIGNAL_OR_REQUEST"))],
            observer.state,
            observer.cursors,
            at,
        )
    finally:
        if store:
            store.close()
        lock.close()
        with contextlib.suppress(OSError):
            lock_path.unlink()
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)


def status(directory: Path = DIRECTORY) -> dict[str, Any]:
    """Read-only health; never acquire the live writer or modify its checkpoint."""
    candidates = sorted(directory.glob("battle-*.sqlite3"), reverse=True)[:30]
    best: tuple[int, dict[str, Any], dict[str, Any], str] | None = None
    for path in candidates:
        connection = readonly_connection(path)
        try:
            row = connection.execute(
                "SELECT commit_seq,state,cursors,at FROM checkpoint WHERE singleton=1"
            ).fetchone()
            if row and (best is None or row[0] > best[0]):
                best = (row[0], json.loads(row[1]), json.loads(row[2]), row[3])
        finally:
            connection.close()
    if best is None:
        return dict(status="NOT_STARTED")
    _, state, cursors, at = best
    return dict(
        status="BOUNDED_RUN_STOPPED"
        if state.get("shutdown_at")
        else "LAST_CHECKPOINT_NOT_PROCESS_LIVENESS_PROOF",
        pid=state.get("pid"),
        last_commit=at,
        heartbeat=state.get("heartbeat"),
        shutdown_at=state.get("shutdown_at"),
        started_at=state.get("started_at"),
        counts=state.get("reconstruction_counts"),
        events=state.get("counts"),
        source_cursor=cursors.get("source"),
        segments=len(candidates),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("watch", "status"))
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--directory", type=Path, default=DIRECTORY)
    parser.add_argument("--experimental-deltas", action="store_true")
    args = parser.parse_args()
    if args.command == "watch":
        watch(args.duration, args.directory, experimental_deltas=args.experimental_deltas)
    else:
        print(json.dumps(status(args.directory), indent=2))


if __name__ == "__main__":
    main()
