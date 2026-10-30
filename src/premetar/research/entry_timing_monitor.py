"""EXP0017 read-only local-feed observer; never connects to an exchange.

Source receipt, execution clock and sidecar capture are separate. A startup tail
is censored. This process does not mutate or restart its source collectors.
"""

import argparse
import contextlib
import hashlib
import json
import logging
import logging.handlers
import os
import re
import signal
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from premetar.continuous.locking import acquire, alive
from premetar.research.battle_store import BattleStore, read_battle
from premetar.research.trader_normalizer import WALLET
from premetar.research.trader_store import readonly_connection
from premetar.sources import STATIONS

ROOT = Path(__file__).resolve().parents[3]
DIRECTORY = ROOT / "data/research/exp0017/live"
TRADER = ROOT / "data/trader/monitor.sqlite3"
WEATHER = ROOT / "data/continuous-v1.sqlite3"
VERSION = "EXP0017-LOCAL-FEED-v1.1"
KINDS = {
    "MARKET",
    "BOOK",
    "TRADE",
    "WS_TRADE",
    "COVERAGE_GAP",
    "STREAMHEALTH",
    "ROLE_EVIDENCE",
    "ENDPOINT_RECEIPT",
}
HORIZONS = (1, 5, 30, 60, 300)


def clock(value: Any) -> datetime | None:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.astimezone(UTC) if result.tzinfo and result.utcoffset() is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def schedule_context(station: str | None, at: datetime) -> dict[str, Any]:
    if station not in STATIONS:
        return dict(status="UNKNOWN", nearest_nominal_time=None, signed_offset_seconds=None)
    configured = STATIONS[station]
    hour = at.replace(minute=0, second=0, microsecond=0)
    candidates = [
        hour + timedelta(hours=h, minutes=m) for h in (-1, 0, 1) for m in configured.routine_minutes
    ]
    nearest = min(candidates, key=lambda t: (abs((at - t).total_seconds()), t))
    return dict(
        status="CURRENT_CONFIG_DECLARED_NOT_HISTORICAL_PUBLICATION",
        nearest_nominal_time=nearest.isoformat(),
        signed_offset_seconds=(at - nearest).total_seconds(),
        routine_minutes=list(configured.routine_minutes),
        public_release_time=None,
    )


def top_levels(value: Any, reverse: bool) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("MALFORMED_DEPTH")
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("MALFORMED_DEPTH")
        try:
            price, size = Decimal(str(item["price"])), Decimal(str(item["size"]))
        except (KeyError, InvalidOperation) as error:
            raise ValueError("MALFORMED_DEPTH") from error
        if not price.is_finite() or not size.is_finite() or not 0 < price < 1 or size <= 0:
            raise ValueError("MALFORMED_DEPTH")
    return sorted(value, key=lambda item: Decimal(str(item["price"])), reverse=reverse)[:5]


def publish_live(
    directory: Path,
    state: dict[str, Any],
    cursors: dict[str, Any],
    *,
    status_value: str = "RUNNING",
    target: Path | None = None,
    at: datetime | None = None,
) -> bool:
    """Atomic, bounded display projection of ALREADY COMMITTED journal state.

    Non-default research directories never publish to the production dashboard.
    An explicit target exists for isolated tests/export tools, not a CLI option.
    """
    if status_value not in {"RUNNING", "STOPPED"}:
        raise ValueError("Unsupported live display status")
    if target is None:
        if directory.resolve() != DIRECTORY.resolve():
            return False
        target = ROOT / "src/premetar/dashboard/static/entry_timing_live.json"
    published = at or datetime.now(UTC)
    if published.tzinfo is None or published.utcoffset() is None:
        raise ValueError("Publication requires timezone-aware UTC clock")
    fields = (
        "trade_id",
        "source_event_id",
        "source_trade_timestamp",
        "original_first_detection",
        "sidecar_capture_time",
        "price",
        "quantity",
        "station",
        "transaction_hash",
        "nearest_nominal_time",
        "signed_offset_seconds",
        "weather_status",
        "evidence_class",
    )
    entries = [
        {key: row.get(key) for key in fields}
        for row in state.get("latest_entries", [])[-10:]
        if isinstance(row, dict) and row.get("evidence_class") == "PROSPECTIVE_POLL"
    ]
    payload = dict(
        version=VERSION,
        published_at=published.astimezone(UTC).isoformat(),
        last_heartbeat=state.get("heartbeat"),
        pid=state.get("pid"),
        status=status_value,
        counts=dict(state.get("counts", {})),
        latest_entries=entries,
        source_cursor=dict(cursors),
        startup_and_gap_policy="CENSORED_NOT_GENUINE_ENTRIES",
        entry_cache_scope="LAST_TEN_GENUINE_ENTRIES_CAPTURED_BY_THIS_VERSION",
        semantics="MUTABLE_DISPLAY_PROJECTION_IMMUTABLE_JOURNAL_IS_EVIDENCE",
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + f".{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink()
    return True


def source_rows(path: Path, after: int | None) -> tuple[int, list[dict[str, Any]]]:
    """Index-tail reads only; irrelevant RAW bodies never enter this process."""
    conn = readonly_connection(path)
    try:
        conn.execute("PRAGMA busy_timeout=250")
        if after is None:
            return int(conn.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0]), []
        names = ",".join("?" for _ in KINDS)
        rows = conn.execute(
            f"SELECT id,kind,received_at,CASE WHEN kind IN ({names}) THEN payload END "
            "FROM events WHERE id>? ORDER BY id LIMIT 1000",
            (*sorted(KINDS), after),
        ).fetchall()
        return (rows[-1][0] if rows else after), [
            dict(id=r[0], kind=r[1], received_at=r[2], payload=json.loads(r[3]))
            for r in rows
            if r[3] is not None
        ]
    finally:
        conn.close()


def market_reference(market: dict[str, Any], received: str) -> dict[str, Any] | None:
    """Only the exact token mapping and explicit original station code are used."""
    try:
        tokens = (
            market.get("positionIds")
            if market.get("version") == "v2"
            else market.get("clobTokenIds")
        )
        tokens = json.loads(tokens) if isinstance(tokens, str) else tokens
        outcomes = market.get("outcomes")
        outcomes = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
        if (
            not isinstance(tokens, list)
            or not isinstance(outcomes, list)
            or len(tokens) != len(outcomes)
        ):
            return None
        if len(tokens) != 2 or {str(v).lower() for v in outcomes} != {"yes", "no"}:
            return None
        by_side = {
            str(side).lower(): str(token) for side, token in zip(outcomes, tokens, strict=True)
        }
        if by_side["yes"] == by_side["no"]:
            return None
    except (ValueError, TypeError):
        return None
    source = str(market.get("resolutionSource") or "")
    description = str(market.get("description") or "")
    candidates: set[str] = set()
    for url in re.findall(r"https?://[^\s\"<>]+", source + " " + description):
        parsed = urlsplit(url.rstrip(".,)"))
        for key in ("site", "ids"):
            candidates.update(
                v.upper()
                for v in parse_qs(parsed.query).get(key, [])
                if re.fullmatch(r"[A-Za-z][A-Za-z0-9]{3}", v)
            )
        if (parsed.hostname or "").endswith(
            "wunderground.com"
        ) and "/history/daily/" in parsed.path:
            value = parsed.path.rstrip("/").split("/")[-1]
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9]{3}", value):
                candidates.add(value.upper())
    candidates.update(re.findall(r"Airport\s*\(([A-Z][A-Z0-9]{3})\)", description))
    return dict(
        condition_id=str(market.get("conditionId") or ""),
        tokens=by_side,
        station=next(iter(candidates)) if len(candidates) == 1 else None,
        station_status="EXPLICIT_CAPTURED_RULE_REFERENCE"
        if len(candidates) == 1
        else "UNKNOWN_OR_CONFLICTING",
        resolution_source=source,
        metadata_received_at=received,
        description_sha256=hashlib.sha256(description.encode()).hexdigest(),
        market_end_date=market.get("endDate"),
        settlement_boundary=None,
        boundary_status="NOT_INFERRED_FROM_MARKET_END_DATE",
    )


def weather_before(path: Path, station: str | None, at: datetime) -> dict[str, Any]:
    result: dict[str, Any] = dict(
        status="UNKNOWN", pws="UNKNOWN", forecast="UNKNOWN", station=station
    )
    if not station or not path.is_file():
        return result
    conn = readonly_connection(path)
    try:
        conn.execute("PRAGMA busy_timeout=250")
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id,station_icao,event_time,collector_receive_time,temperature_c,raw_text,source,"
            "startup_censored,coverage_gap,evidence_class FROM observations WHERE "
            "id>(SELECT COALESCE(MAX(id),0)-3000 FROM observations) AND station_icao=? "
            "AND product_type='METAR' ORDER BY id DESC LIMIT 100",
            (station,),
        ).fetchall()
        eligible = []
        for raw in rows:
            row = dict(raw)
            event, receipt = clock(row["event_time"]), clock(row["collector_receive_time"])
            if (
                event
                and receipt
                and event <= at
                and receipt <= at
                and not row["startup_censored"]
                and not row["coverage_gap"]
                and not str(row["raw_text"]).startswith("SPECI")
                and "HISTORICAL" not in str(row["evidence_class"])
            ):
                eligible.append(row)
        if eligible:
            first_by_report: dict[tuple[str, str], dict[str, Any]] = {}
            for row in eligible:
                key = (str(row["event_time"]), str(row["raw_text"]))
                previous = first_by_report.get(key)
                if previous is None or str(row["collector_receive_time"]) < str(
                    previous["collector_receive_time"]
                ):
                    first_by_report[key] = row
            # Latest known nominal/version; preserve its first captured TAC receipt.
            latest = max(
                first_by_report.values(),
                key=lambda r: (str(r["event_time"]), str(r["collector_receive_time"])),
            )
            result.update(status="RECORDED_AVAILABLE_BEFORE_EXECUTION_BOUNDED_WINDOW", metar=latest)
            result["receipt_scope"] = "EARLIEST_SAME_TAC_WITHIN_BOUNDED_QUERY"
        result["coverage"] = "LAST_3000_SOURCE_ROWS_ONLY_NOT_COMPLETE_HISTORY"
        return result
    except (sqlite3.Error, ValueError, TypeError) as error:
        result.update(status="UNKNOWN", error_class=type(error).__name__)
        return result
    finally:
        conn.close()


class Monitor:
    def __init__(self, store: BattleStore, weather: Path = WEATHER) -> None:
        self.store, self.weather = store, weather
        self.state, self.cursors = store.restore()
        self.upgraded_from = self.state.get("version")
        for name, default in (
            ("markets", {}),
            ("books", {}),
            ("seen", []),
            ("pending", []),
            ("counts", {}),
            ("role_evidence", {}),
            ("endpoint_receipts", {}),
            ("latest_entries", []),
        ):
            self.state.setdefault(name, default)
        if self.upgraded_from not in (None, VERSION):
            self.state["books"] = {}
        self.state["version"] = VERSION
        self.last_publish_monotonic = 0.0
        # Older observer versions persisted the evidence but not its UI cache.
        # Recover original entry fields, never reconstruct a past weather state.
        if not self.state["latest_entries"]:
            recovered = []
            for path in sorted(store.directory.glob("battle-*.sqlite3"), reverse=True)[:30]:
                connection = readonly_connection(path)
                try:
                    encoded = connection.execute(
                        "SELECT payload FROM events WHERE kind='ENTRY_OBSERVED' ORDER BY id DESC LIMIT 10"
                    ).fetchall()
                finally:
                    connection.close()
                for (value,) in encoded:
                    entry = json.loads(value)
                    # Prototype entries omitted this redundant field. Recover it
                    # only from an exact, already recorded endpoint evidence join.
                    if not entry.get("evidence_class"):
                        for proof in entry.get("endpoint_receipts_known_at_capture", []):
                            original = proof.get("original_evidence", {})
                            if (
                                original.get("trade_id") == entry.get("trade_id")
                                and original.get("source_trade_timestamp")
                                == entry.get("source_trade_timestamp")
                                and original.get("evidence_class") == "PROSPECTIVE_POLL"
                            ):
                                entry["evidence_class"] = "PROSPECTIVE_POLL"
                                break
                    if entry.get("evidence_class") != "PROSPECTIVE_POLL":
                        continue
                    recovered.append(
                        dict(
                            **{
                                key: entry.get(key)
                                for key in (
                                    "trade_id",
                                    "source_event_id",
                                    "source_trade_timestamp",
                                    "original_first_detection",
                                    "sidecar_capture_time",
                                    "price",
                                    "quantity",
                                    "transaction_hash",
                                    "evidence_class",
                                )
                            },
                            station=(entry.get("metadata") or {}).get("station"),
                            nearest_nominal_time=(entry.get("metar_schedule") or {}).get(
                                "nearest_nominal_time"
                            ),
                            signed_offset_seconds=(entry.get("metar_schedule") or {}).get(
                                "signed_offset_seconds"
                            ),
                            weather_status=(entry.get("weather") or {}).get("status"),
                        )
                    )
                if len(recovered) >= 10:
                    break
            self.state["latest_entries"] = sorted(
                recovered, key=lambda row: str(row.get("sidecar_capture_time"))
            )[-10:]

    def event(self, kind: str, at: datetime, payload: dict[str, Any]) -> dict[str, Any]:
        counts = self.state["counts"]
        counts[kind] = counts.get(kind, 0) + 1
        return dict(kind=kind, at=at.isoformat(), payload=payload)

    def book(self, token: str, at: datetime) -> dict[str, Any] | None:
        valid = []
        for row in self.state["books"].get(token, []):
            received = clock(row["received_at"])
            if received and received <= at:
                valid.append(row)
        if not valid:
            return None
        chosen: dict[str, Any] = valid[-1]
        age = (at - (clock(chosen["received_at"]) or at)).total_seconds()
        return {
            **chosen,
            "age_seconds": age,
            "status": "RECORDED_SNAPSHOT" if age <= 10 else "STALE_BOOK",
            "fill_evidence": "NONE_SNAPSHOT_IS_NOT_A_FILL",
        }

    def ingest(self, row: dict[str, Any], at: datetime) -> list[dict[str, Any]]:
        payload, kind = row["payload"], row["kind"]
        receipt = clock(row["received_at"])
        if not receipt or receipt > at:
            return [self.event("SOURCE_TIME_REJECTED", at, dict(source_event_id=row["id"]))]
        if kind == "MARKET":
            reference = market_reference(payload, receipt.isoformat())
            if reference and reference["condition_id"]:
                markets = self.state["markets"]
                markets.pop(reference["condition_id"], None)
                markets[reference["condition_id"]] = reference
                while len(markets) > 500:
                    del markets[next(iter(markets))]
        elif kind == "BOOK" and payload.get("complete") is True:
            try:
                bids, asks = (
                    top_levels(payload.get("bids"), True),
                    top_levels(payload.get("asks"), False),
                )
            except ValueError:
                return [
                    self.event(
                        "SOURCE_BOOK_REJECTED",
                        at,
                        dict(source_event_id=row["id"], reason="MALFORMED_DEPTH"),
                    )
                ]
            token = str(payload.get("token_id") or "")
            books = self.state["books"]
            history = books.pop(token, [])
            history = [
                b
                for b in history
                if (receipt - (clock(b["received_at"]) or receipt)).total_seconds() <= 300
            ]
            history.append(
                dict(
                    source_event_id=row["id"],
                    received_at=receipt.isoformat(),
                    token_id=token,
                    condition_id=payload.get("market"),
                    connection_id=payload.get("connection_id"),
                    bids=bids,
                    asks=asks,
                    snapshot_source=payload.get("source"),
                    depth_scope="TOP_5_OF_RECORDED_FULL_SNAPSHOT_NOT_QUEUE_EVIDENCE",
                    source_hash=payload.get("hash"),
                )
            )
            books[token] = history[-20:]
            while len(books) > 100:
                del books[next(iter(books))]
        elif kind in {"COVERAGE_GAP", "STREAMHEALTH"}:
            stream = str(payload.get("state") or "")
            connection = payload.get("connection_id")
            previous_connection = self.state.get("stream_connection_id")
            clear_all = (
                kind == "COVERAGE_GAP"
                or stream in {"RECONNECTING", "STOPPED", "MALFORMED_MESSAGE"}
                or connection is not None
                and previous_connection not in (None, connection)
            )
            if clear_all:
                self.state["books"] = {}
            elif stream == "SUBSCRIPTIONS_CHANGED":
                selected = payload.get("tokens")
                if isinstance(selected, list):
                    retained = {str(token) for token in selected}
                    self.state["books"] = {
                        token: ring
                        for token, ring in self.state["books"].items()
                        if token in retained
                    }
                else:
                    # Missing selected identities cannot certify continued coverage.
                    self.state["books"] = {}
            if connection is not None:
                self.state["stream_connection_id"] = connection
            return [
                self.event(
                    "SOURCE_COVERAGE",
                    at,
                    dict(
                        source_event_id=row["id"],
                        source_kind=kind,
                        source_received_at=receipt.isoformat(),
                        details=payload,
                    ),
                )
            ]
        elif kind in {"ROLE_EVIDENCE", "ENDPOINT_RECEIPT"}:
            identity = str(payload.get("trade_id") or "")
            if not identity:
                return [
                    self.event(
                        "SOURCE_EVIDENCE_REJECTED",
                        at,
                        dict(source_event_id=row["id"], reason="MISSING_EXACT_TRADE_ID"),
                    )
                ]
            evidence = dict(
                source_event_id=row["id"],
                source_recorded_at=receipt.isoformat(),
                sidecar_evidence_captured_at=at.isoformat(),
                original_evidence=dict(payload),
                trade_id=identity,
                entry_record_status="ALREADY_SEEN"
                if identity in self.state["seen"]
                else "PENDING_OR_UNMONITORED_TRADE",
                no_history_rewrite=True,
            )
            cache_name = "role_evidence" if kind == "ROLE_EVIDENCE" else "endpoint_receipts"
            cache = self.state[cache_name]
            if kind == "ENDPOINT_RECEIPT":
                existing = cache.pop(identity, [])
                endpoint = str(payload.get("endpoint") or "")
                if not any(
                    str(item["original_evidence"].get("endpoint") or "") == endpoint
                    for item in existing
                ):
                    existing.append(evidence)
                cache[identity] = existing[-5:]
            else:
                cache.pop(identity, None)
                cache[identity] = evidence
            while len(cache) > 2000:
                del cache[next(iter(cache))]
            return [
                self.event(
                    "ROLE_EVIDENCE_JOIN" if kind == "ROLE_EVIDENCE" else "ENDPOINT_RECEIPT_JOIN",
                    at,
                    evidence,
                )
            ]
        elif kind == "TRADE":
            if (
                payload.get("trader_wallet", "").lower() != WALLET
                or payload.get("side") != "BUY"
                or str(payload.get("outcome")).lower() != "no"
                or not str(payload.get("slug") or "").startswith(
                    ("highest-temperature-in-", "lowest-temperature-in-")
                )
            ):
                return []
            identity = str(payload.get("trade_id") or "")
            if not identity or identity in self.state["seen"]:
                return []
            self.state["seen"] = (self.state["seen"] + [identity])[-10000:]
            source, first = (
                clock(payload.get("source_trade_timestamp")),
                clock(payload.get("first_collector_receipt_utc")),
            )
            if (
                payload.get("evidence_class") != "PROSPECTIVE_POLL"
                or not source
                or not first
                or first > at
                or source > first + timedelta(seconds=1)
            ):
                return [
                    self.event(
                        "CENSORED_BUY",
                        at,
                        dict(
                            trade_id=identity,
                            source_event_id=row["id"],
                            evidence_class=payload.get("evidence_class"),
                            reason="NON_PROSPECTIVE_OR_INVALID_SOURCE_CLOCK",
                        ),
                    )
                ]
            market = self.state["markets"].get(str(payload.get("condition_id")))
            if market and (
                market["tokens"]["no"] != payload.get("token_id")
                or (clock(market["metadata_received_at"]) or at) > first
            ):
                market = None
            entry = dict(
                trade_id=identity,
                source_event_id=row["id"],
                source_trade_timestamp=source.isoformat(),
                source_timestamp_precision_seconds=payload.get(
                    "source_timestamp_precision_seconds", 1
                ),
                original_first_detection=first.isoformat(),
                sidecar_capture_time=at.isoformat(),
                sidecar_delay_seconds=(at - first).total_seconds(),
                price=payload.get("price"),
                quantity=payload.get("size"),
                condition_id=payload.get("condition_id"),
                token_id=payload.get("token_id"),
                transaction_hash=payload.get("transaction_hash"),
                order_role="UNKNOWN",
                order_submission_time=None,
                block_number=payload.get("block_number"),
                log_index=payload.get("log_index"),
                metar_schedule=schedule_context(market.get("station") if market else None, source),
                metadata=market,
                weather=weather_before(
                    self.weather, market.get("station") if market else None, source
                ),
                source_time_book=self.book(str(payload["token_id"]), source),
                detection_time_book=self.book(str(payload["token_id"]), first),
                pre_event_history_status="ONLY_ORIGINAL_RECORDED_RECEIPTS_NO_RETROACTIVE_SNAPSHOT",
                matching_controls="COVERAGE_CANDIDATES_ONLY_NOT_COMPLETE_COUNTERFACTUAL",
                evidence_class="PROSPECTIVE_POLL",
            )
            role = self.state["role_evidence"].get(identity)
            entry["role_evidence_available_at_detection"] = (
                role if role and (clock(role["source_recorded_at"]) or at) <= first else None
            )
            entry["endpoint_receipts_known_at_capture"] = list(
                self.state["endpoint_receipts"].get(identity, [])
            )
            if market:
                entry["yes_book_at_detection"] = self.book(market["tokens"]["yes"], first)
            self.state["latest_entries"] = (
                self.state["latest_entries"]
                + [
                    dict(
                        trade_id=identity,
                        source_event_id=row["id"],
                        source_trade_timestamp=source.isoformat(),
                        original_first_detection=first.isoformat(),
                        sidecar_capture_time=at.isoformat(),
                        price=payload.get("price"),
                        quantity=payload.get("size"),
                        station=market.get("station") if market else None,
                        transaction_hash=payload.get("transaction_hash"),
                        nearest_nominal_time=entry["metar_schedule"].get("nearest_nominal_time"),
                        signed_offset_seconds=entry["metar_schedule"].get("signed_offset_seconds"),
                        weather_status=entry["weather"].get("status"),
                        evidence_class="PROSPECTIVE_POLL",
                    )
                ]
            )[-10:]
            self.state["pending"] = (
                self.state["pending"]
                + [
                    dict(
                        trade_id=identity,
                        token_id=payload["token_id"],
                        detection=first.isoformat(),
                        remaining=list(HORIZONS),
                    )
                ]
            )[-500:]
            return [self.event("ENTRY_OBSERVED", at, entry)]
        return []

    def followups(self, at: datetime) -> list[dict[str, Any]]:
        result = []
        for pending in self.state["pending"]:
            detection = clock(pending["detection"]) or at
            for seconds in list(pending["remaining"]):
                target = detection + timedelta(seconds=seconds)
                if target > at:
                    continue
                book = self.book(pending["token_id"], at)
                # A late sidecar sample is explicitly not the requested horizon book.
                result.append(
                    self.event(
                        "POST_ENTRY_SAMPLE",
                        at,
                        dict(
                            trade_id=pending["trade_id"],
                            requested_horizon_seconds=seconds,
                            requested_time=target.isoformat(),
                            actual_capture_time=at.isoformat(),
                            sampling_delay_seconds=(at - target).total_seconds(),
                            book=book,
                            status="LATE_RECORDED_SAMPLE_NOT_EXACT_HORIZON"
                            if (at - target).total_seconds() > 1
                            else "RECORDED_SAMPLE",
                            execution="NOT_SIMULATED",
                        ),
                    )
                )
                pending["remaining"].remove(seconds)
        self.state["pending"] = [p for p in self.state["pending"] if p["remaining"]]
        return result

    def cycle(self, source: Path, at: datetime) -> None:
        key = str(source.resolve())
        previous = self.cursors.get(key)
        cursor, rows = source_rows(source, previous)
        events = []
        if self.upgraded_from not in (None, VERSION):
            events.append(
                self.event(
                    "BUFFER_VERSION_UPGRADE",
                    at,
                    dict(
                        previous_version=self.upgraded_from,
                        new_version=VERSION,
                        reason="BEST_DEPTH_SORTING_FIXED_BEFORE_CONTINUOUS_DEPLOYMENT",
                        history_preserved=True,
                    ),
                )
            )
            self.upgraded_from = VERSION
        if previous is None:
            events.append(
                self.event(
                    "CENSORED_STARTUP",
                    at,
                    dict(
                        source=str(source),
                        cursor=cursor,
                        reason="PREEXISTING_HISTORY_NOT_LIVE_EVENTS",
                    ),
                )
            )
        for row in rows:
            events.extend(self.ingest(row, at))
        self.cursors[key] = cursor
        events.extend(self.followups(at))
        bucket = int(at.timestamp()) // 30
        if bucket != self.state.get("control_bucket"):
            observations = []
            for token in self.state["books"]:
                book = self.book(token, at)
                if book and book["status"] == "RECORDED_SNAPSHOT":
                    observations.append(dict(token_id=token, book=book))
            events.append(
                self.event(
                    "CONTROL_CANDIDATE",
                    at,
                    dict(
                        bucket_utc_start=datetime.fromtimestamp(bucket * 30, UTC).isoformat(),
                        actual_sample_time=at.isoformat(),
                        books=observations[:100],
                        no_entry_status="PENDING_DELAYED_TRADES_UNKNOWN",
                        exposure_coverage="SELECTED_WATCHLIST_NOT_ALL_MARKET",
                        control_semantics="RECORDED_CANDIDATE_NOT_MATCHED_BASELINE",
                    ),
                )
            )
            self.state["control_bucket"] = bucket
        self.state["heartbeat"] = at.isoformat()
        self.state["pid"] = os.getpid()
        self.store.commit(events, self.state, self.cursors, at)
        tick = time.monotonic()
        if tick - self.last_publish_monotonic >= 60:
            publish_live(self.store.directory, self.state, self.cursors)
            self.last_publish_monotonic = tick


def status(directory: Path = DIRECTORY) -> dict[str, Any]:
    events = read_battle(directory, limit=10)
    lock = directory / "monitor.lock"
    pid = None
    try:
        # Windows holds an OS lock on byte zero. Read metadata after that byte.
        with lock.open(encoding="utf-8") as handle:
            handle.seek(1)
            info = json.load(handle)
        pid = info.get("pid")
    except (OSError, ValueError, TypeError):
        pass
    heartbeat = None
    for path in sorted(directory.glob("battle-*.sqlite3"), reverse=True):
        conn = readonly_connection(path)
        try:
            row = conn.execute("SELECT state FROM checkpoint WHERE singleton=1").fetchone()
            if row:
                heartbeat = json.loads(row[0])
                break
        finally:
            conn.close()
    summary = (
        {k: heartbeat.get(k) for k in ("version", "heartbeat", "shutdown_at", "pid", "counts")}
        if heartbeat
        else None
    )
    return dict(
        status="RUNNING" if isinstance(pid, int) and alive(pid) else "STOPPED",
        pid=pid,
        state=summary,
        recent_events=events,
        version=VERSION,
    )


def watch(
    directory: Path = DIRECTORY,
    source: Path = TRADER,
    weather: Path = WEATHER,
    duration: float | None = None,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / "monitor.lock"
    lock = acquire(lock_path, str(uuid4()), recover=True)
    store: BattleStore | None = None
    stop = False

    def request_stop(signum: int, frame: Any) -> None:
        nonlocal stop
        stop = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, request_stop)
    logs = directory / "logs"
    logs.mkdir(exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        logs / "monitor.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8"
    )
    logger = logging.getLogger("premetar.entry_timing")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    started = time.monotonic()
    try:
        store = BattleStore(directory, max_segment_bytes=50_000_000, max_total_bytes=500_000_000)
        monitor = Monitor(store, weather)
        monitor.state.pop("shutdown_at", None)
        logger.info("EXP0017 started pid=%s; source access read-only", os.getpid())
        while not stop and not (directory / "stop.request").exists():
            if duration is not None and time.monotonic() - started >= duration:
                break
            at = datetime.now(UTC)
            try:
                monitor.cycle(source, at)
            except (sqlite3.Error, OSError, ValueError) as error:
                logger.warning("source cycle failed class=%s", type(error).__name__)
                # Discard in-memory source cursor/data changes on failed commits.
                monitor = Monitor(store, weather)
            for _ in range(100):
                if (
                    stop
                    or (directory / "stop.request").exists()
                    or duration is not None
                    and time.monotonic() - started >= duration
                ):
                    break
                time.sleep(0.1)
        at = datetime.now(UTC)
        monitor.state["shutdown_at"] = at.isoformat()
        store.commit(
            [monitor.event("STOP", at, dict(reason="STOP_REQUEST_OR_DURATION_OR_SIGNAL"))],
            monitor.state,
            monitor.cursors,
            at,
        )
        publish_live(directory, monitor.state, monitor.cursors, status_value="STOPPED")
    finally:
        if store:
            store.close()
        lock.close()
        with contextlib.suppress(OSError):
            lock_path.unlink()
        logger.removeHandler(handler)
        handler.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("watch", "status"))
    parser.add_argument("--duration", type=float)
    args = parser.parse_args()
    if args.duration is not None and args.duration <= 0:
        parser.error("duration must be positive")
    if args.action == "watch":
        watch(duration=args.duration)
    else:
        print(json.dumps(status(), indent=2))


if __name__ == "__main__":
    main()
