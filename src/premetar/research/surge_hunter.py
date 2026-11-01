"""Independent shadow surge observation; never submits orders or assumes fills."""

import argparse
import asyncio
import hashlib
import json
import math
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from premetar.research.battle_store import BattleStore
from premetar.research.entry_reconstruction import Reconstruction
from premetar.research.entry_reconstruction_capture import capture
from premetar.research.entry_reconstruction_features import snapshot_features
from premetar.research.entry_timing_monitor import ROOT, WEATHER, clock
from premetar.research.surge_associations import associate
from premetar.research.surge_buffer import RollingBuffer
from premetar.research.surge_detector import detect_changes
from premetar.research.surge_liquidity import liquidity_paths
from premetar.research.surge_states import book_state
from premetar.research.trader_normalizer import WALLET
from premetar.research.trader_stream import stream_market

DIRECTORY = ROOT / "data/research/exp0018_surge"
VERSION = "SURGE-HUNTER-v1"


class SurgeMonitor(Reconstruction):
    def __init__(self, store: BattleStore, weather: Path = WEATHER) -> None:
        super().__init__(store, weather, experimental_deltas=True)
        self.buffer = RollingBuffer()
        self.previous: dict[str, dict[str, Any]] = {}
        self.last_print: dict[str, dict[str, Any]] = {}
        self.had_gap = False
        self.seed_times: dict[str, datetime] = {}
        self.gap_times: list[datetime] = []
        self.state.setdefault("surge_pending", [])
        self.state.setdefault("surge_trades", [])
        self.state.setdefault("surge_counts", {})
        self.state.setdefault("surge_recent", [])
        self.state.setdefault("surge_arrivals", [])
        self.started = datetime.now(UTC)
        self.last_publish = 0.0

    def quote(self, token: str, at: datetime) -> dict[str, Any]:
        raw = self.ring.latest(token, at, max_age=300)
        if raw is None:
            prior = [
                b
                for b in self.ring.histories.get(token, [])
                if (clock(b.get("received_at")) or at + timedelta(days=1)) <= at
            ]
            raw = prior[-1] if prior else None
        market = None
        outcome = None
        for m in self.state["markets"].values():
            for side, identity in m["tokens"].items():
                if identity == token:
                    market, outcome = m, side
        valid_mapping = market is not None
        state = book_state(
            dict(raw, complete=True, mapping_verified=valid_mapping) if raw else None, at
        )
        if not valid_mapping:
            state = "INVALID_TOKEN_MAPPING"
        elif raw is None and self.had_gap:
            state = "RECONNECT_GAP"
        return dict(
            snapshot_features(raw),
            state=state,
            token_id=token,
            outcome=outcome,
            condition_id=market["condition_id"] if market else None,
            received_at=raw["received_at"] if raw else at.isoformat(),
            connection_id=raw.get("connection_id") if raw else None,
            source_event_id=raw.get("source_event_id") if raw else None,
            exchange_timestamp=raw.get("exchange_timestamp") if raw else None,
            depth_scope=raw.get("depth_scope") if raw else None,
            hash=raw.get("source_hash") if raw else None,
        )

    def note(self, name: str) -> None:
        counts = self.state["surge_counts"]
        counts[name] = counts.get(name, 0) + 1

    def ingest(self, row: dict[str, Any], at: datetime) -> list[dict[str, Any]]:
        receipt = clock(row.get("received_at"))
        if receipt is None or receipt > at:
            return super().ingest(row, at)
        kind, p = row["kind"], row["payload"]
        events = super().ingest(row, at)
        if kind in {"STREAMHEALTH", "COVERAGE_GAP"} and (
            kind == "COVERAGE_GAP"
            or p.get("state") in {"RECONNECTING", "STOPPED", "SUBSCRIBED", "MALFORMED_MESSAGE"}
        ):
            self.previous = {}
            self.last_print = {}
            self.seed_times = {}
            self.gap_times = (self.gap_times + [receipt])[-100:]
            if p.get("state") == "RECONNECTING":
                self.note("reconnects")
            if p.get("state") != "SUBSCRIBED":
                self.had_gap = True
            events.append(
                self.event(
                    "SURGE_GAP",
                    at,
                    dict(source_event_id=row["id"], received_at=receipt.isoformat(), details=p),
                )
            )
            self.note("gaps")
        tokens = []
        if kind == "BOOK":
            tokens = [str(p.get("token_id") or "")]
        elif kind == "WS_DELTA":
            tokens = sorted(
                {
                    str(c.get("asset_id"))
                    for c in p.get("price_changes", [])
                    if isinstance(c, dict) and c.get("asset_id")
                }
            )
        for token in tokens:
            quote = self.quote(token, receipt)
            quote.update(update_type=kind, capture_id=p.get("capture_id"))
            if not quote["state"].startswith("VALID_"):
                self.previous.pop(token, None)
                self.seed_times.pop(token, None)
                self.gap_times = (self.gap_times + [receipt])[-100:]
                events.append(
                    self.event(
                        "BOOK_INCONSISTENCY"
                        if quote["state"] == "INCONSISTENT_BOOK"
                        else "SURGE_BOOK_UNAVAILABLE",
                        at,
                        dict(quote, source_event_id=row["id"]),
                    )
                )
                self.note("invalid_states")
                continue
            self.buffer.append(quote)
            self.seed_times.setdefault(token, receipt)
            events.append(self.event("SURGE_BOOK_STATE", at, quote))
            prior = self.previous.get(token)
            if prior:
                for change in detect_changes(prior, quote):
                    identity = hashlib.sha256(
                        f"{VERSION}:{p.get('capture_id')}:{row['id']}:{token}:{change['kind']}:{change['field']}".encode()
                    ).hexdigest()
                    market = self.state["markets"].get(quote["condition_id"])
                    pair = market["tokens"] if market else {}
                    no = self.quote(pair["no"], receipt) if pair else None
                    yes = self.quote(pair["yes"], receipt) if pair else None
                    feasibility = liquidity_paths(no, yes, receipt.isoformat())
                    surge = dict(
                        change,
                        surge_id=identity,
                        rule_version=VERSION,
                        condition_id=quote["condition_id"],
                        token_id=token,
                        outcome=quote["outcome"],
                        before_quote=prior,
                        after_quote=quote,
                        source_event_id=row["id"],
                        boundary_kind="SNAPSHOT_TRANSITION"
                        if kind == "BOOK"
                        else "WITHIN_RECEIVED_SESSION_LEVEL_UPDATE",
                        feasibility=feasibility,
                        stage="INTERESTING_BOOK_EVENT_ONLY",
                        supported_fill_quantity=None,
                        settlement_day=market.get("settlement_day") if market else None,
                        station=market.get("station") if market else None,
                        own_trade_effect="NOT_EXCLUDED",
                        matching_time="UNKNOWN",
                        latency_scenarios_seconds=[0.1, 0.5, 1, 3, 5],
                        prospective_capture=True,
                    )
                    self.note(change["kind"])
                    events.append(self.event("SURGE_DETECTED", at, surge))
                    if len(self.state["surge_pending"]) >= 1000:
                        events.append(
                            self.event(
                                "SURGE_FOLLOWUP_CAPACITY_GAP",
                                at,
                                self.state["surge_pending"].pop(0),
                            )
                        )
                    self.state["surge_pending"].append(surge)
                    self.state["surge_recent"] = (self.state["surge_recent"] + [surge])[-20:]
                    if quote["outcome"] == "no" and change["kind"] in {
                        "BID_SURGE",
                        "LIQUIDITY_APPEARANCE",
                    }:
                        self.state["surge_arrivals"].append(
                            dict(
                                surge_id=identity,
                                condition_id=quote["condition_id"],
                                received_at=receipt.isoformat(),
                                remaining=[0.1, 0.5, 1, 3, 5],
                            )
                        )
                        if len(self.state["surge_arrivals"]) > 100:
                            events.append(
                                self.event(
                                    "SURGE_ARRIVAL_CAPACITY_GAP",
                                    at,
                                    self.state["surge_arrivals"].pop(0),
                                )
                            )
            self.previous[token] = quote
        if kind == "WS_TRADE":
            events.append(
                self.event(
                    "SURGE_PUBLIC_TRADE",
                    at,
                    dict(
                        p,
                        received_at=receipt.isoformat(),
                        source_event_id=row["id"],
                        wallet_attribution="UNAVAILABLE",
                    ),
                )
            )
            try:
                price = float(p.get("price"))
            except (TypeError, ValueError):
                price = float("nan")
            token = str(p.get("token_id") or "")
            known_tokens = {t for m in self.state["markets"].values() for t in m["tokens"].values()}
            if token in known_tokens and math.isfinite(price) and 0 <= price <= 1:
                point = dict(
                    token_id=token,
                    connection_id=p.get("connection_id"),
                    received_at=receipt.isoformat(),
                    bid=price,
                )
                for event in detect_changes(self.last_print.get(token, {}), point):
                    if event["kind"] == "BID_SURGE":
                        self.note("TRADE_PRICE_SURGE")
                        events.append(
                            self.event(
                                "TRADE_PRICE_SURGE",
                                at,
                                dict(
                                    event,
                                    kind="TRADE_PRICE_SURGE",
                                    token_id=token,
                                    source_event_id=row["id"],
                                    transaction_hash=p.get("transaction_hash"),
                                    wallet_attribution="UNAVAILABLE",
                                ),
                            )
                        )
                self.last_print[token] = point
        elif kind == "TRADE":
            if str(p.get("trader_wallet") or "").lower() != WALLET:
                return events
            self.state["surge_trades"] = (self.state["surge_trades"] + [p])[-2000:]
            if (
                p.get("side") == "BUY"
                and str(p.get("outcome")).lower() == "no"
                and p.get("evidence_class") == "PROSPECTIVE_POLL"
            ):
                source = clock(p.get("source_trade_timestamp"))
                if source is not None and source <= receipt:
                    window = self.buffer.window(
                        str(p.get("token_id")), source - timedelta(microseconds=1)
                    )
                    market = self.state["markets"].get(str(p.get("condition_id")))
                    required = list(market["tokens"].values()) if market else []
                    start = source - timedelta(seconds=300)
                    complete = (
                        bool(required)
                        and all(
                            token in self.seed_times and self.seed_times[token] <= start
                            for token in required
                        )
                        and not any(start <= gap <= receipt for gap in self.gap_times)
                        and window["coverage"] != "PARTIAL_CAPACITY"
                    )
                    events.append(
                        self.event(
                            "SURGE_ENTRY_WINDOW",
                            at,
                            dict(
                                trade_id=p.get("trade_id"),
                                source_trade_timestamp=p.get("source_trade_timestamp"),
                                first_detection=p.get("first_collector_receipt_utc"),
                                source_precision_seconds=1,
                                window=window,
                                coverage="FULL_RECORDED_SESSION_WINDOW_NOT_MATCHING_CLOCK_PROOF"
                                if complete
                                else "PARTIAL_OR_MISSING_PRE_SOURCE_WINDOW",
                                recorded_session_window_complete=complete,
                                matching_clock_verified=False,
                                session_started=self.started.isoformat(),
                            ),
                        )
                    )
                    self.note("entries")
        return events

    def followups(self, at: datetime) -> list[dict[str, Any]]:
        events = super().followups(at)
        arrivals = []
        for candidate in self.state["surge_arrivals"]:
            decision = clock(candidate["received_at"])
            if decision is None:
                continue
            market = self.state["markets"].get(candidate["condition_id"])
            for latency in list(candidate["remaining"]):
                arrival = decision + timedelta(seconds=latency)
                if at < arrival:
                    continue
                no = self.quote(market["tokens"]["no"], at) if market else None
                yes = self.quote(market["tokens"]["yes"], at) if market else None
                after_arrival = (
                    no is not None
                    and yes is not None
                    and all(
                        (clock(q["received_at"]) or decision) >= arrival
                        and q["state"].startswith("VALID_")
                        for q in (no, yes)
                    )
                )
                if not after_arrival and at < arrival + timedelta(seconds=10):
                    continue
                feasibility = (
                    liquidity_paths(no, yes, at.isoformat())
                    if after_arrival
                    else dict(
                        classification="INSUFFICIENT_DATA",
                        reason="NO_RECORDED_PAIR_AFTER_MODELED_ARRIVAL",
                    )
                )
                events.append(
                    self.event(
                        "SURGE_ARRIVAL_REVIEW",
                        at,
                        dict(
                            surge_id=candidate["surge_id"],
                            latency_seconds=latency,
                            decision_time=decision.isoformat(),
                            modeled_arrival=arrival.isoformat(),
                            review_time=at.isoformat(),
                            no=no,
                            yes=yes,
                            feasibility=feasibility,
                            stage="HYPOTHETICAL_ARRIVAL_FEASIBILITY_ONLY",
                            maximum_supported_quantity=None,
                            supported_fill_quantity=None,
                            net_profit=None,
                            maker_queue_position="UNKNOWN",
                        ),
                    )
                )
                candidate["remaining"].remove(latency)
            if candidate["remaining"]:
                arrivals.append(candidate)
        self.state["surge_arrivals"] = arrivals
        pending = []
        for surge in self.state["surge_pending"]:
            received = clock(surge["received_at"])
            if received and (at - received).total_seconds() >= 300:
                result = associate(surge, self.state["surge_trades"], at.isoformat())
                if (
                    received < self.started
                    and not result["source_clock_following_trade_ids"]
                    and not result["detection_following_trade_ids"]
                ):
                    result["status"] = "COVERAGE_GAP_CENSORED_NO_ENTRY_NOT_ESTABLISHED"
                events.append(
                    self.event(
                        "SURGE_ASSOCIATION_REVIEW",
                        at,
                        dict(
                            surge_id=surge["surge_id"],
                            condition_id=surge["condition_id"],
                            settlement_day=surge.get("settlement_day"),
                            association=result,
                            matched_control_status="INSUFFICIENT_DATA_FULL_SETTLEMENT_AND_METAR_CONTEXT_NOT_VERIFIED",
                        ),
                    )
                )
            else:
                pending.append(surge)
        self.state["surge_pending"] = pending
        return events

    def publish(self, at: datetime) -> None:
        """Bounded UI projection after durable checkpoint, never before it."""
        if self.store.directory.resolve() != DIRECTORY.resolve():
            return
        if not self.state.get("shutdown_at") and time.monotonic() - self.last_publish < 60:
            return
        counts = self.state["surge_counts"]
        kinds = {
            k: v
            for k, v in counts.items()
            if k
            in {
                "BID_SURGE",
                "ASK_SURGE",
                "BID_COLLAPSE",
                "ASK_COLLAPSE",
                "LIQUIDITY_APPEARANCE",
                "LIQUIDITY_WITHDRAWAL",
                "SPREAD_COMPRESSION",
                "SPREAD_EXPANSION",
                "TRADE_PRICE_SURGE",
            }
        }
        data = dict(
            published_at=at.isoformat(),
            mode="PROSPECTIVE_CHECKPOINT_PROJECTION_NOT_PID_PROOF",
            status="STOPPED" if self.state.get("shutdown_at") else "LAST_CHECKPOINT_RUNNING",
            pid=self.state.get("pid"),
            summary=dict(
                surges=sum(kinds.values()),
                events_by_kind=kinds,
                entries=counts.get("entries", 0),
                associations=None,
                supported_fills=0,
                matched_controls=0,
            ),
            session=dict(
                contracts=len(self.state["markets"]),
                tokens=len(
                    {t for m in self.state["markets"].values() for t in m["tokens"].values()}
                ),
                duration_seconds=None,
                reconnects=counts.get("reconnects", 0),
            ),
            events=self.state["surge_recent"],
            freshness=[
                self.quote(token, at)
                for m in self.state["markets"].values()
                for token in m["tokens"].values()
            ],
        )
        target = ROOT / "src/premetar/dashboard/static/surge_hunter_live.json"
        temporary = target.with_suffix(".tmp")
        try:
            temporary.write_text(
                json.dumps(data, allow_nan=False, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            temporary.replace(target)
            self.last_publish = time.monotonic()
        except (OSError, ValueError) as error:
            self.state["projection_error_class"] = type(error).__name__


async def stable_stream(tokens: Any, emit: Any, stop: asyncio.Event) -> None:
    await stream_market(tokens, emit, stop, stable_seconds=60)


async def run(
    duration: float = 360, contracts: int = 4, directory: Path = DIRECTORY
) -> dict[str, Any]:
    result = await capture(
        duration,
        directory,
        max_contracts=contracts,
        observer_factory=SurgeMonitor,
        stream_factory=stable_stream,
    )
    return dict(result, study=VERSION)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=360)
    parser.add_argument("--contracts", type=int, default=4)
    parser.add_argument("--directory", type=Path, default=DIRECTORY)
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Explicit foreground repeated bounded sessions; no autostart",
    )
    args = parser.parse_args()
    while True:
        result = asyncio.run(run(args.duration, args.contracts, args.directory))
        print(json.dumps(result, indent=2), flush=True)
        if result.get("error_class"):
            raise SystemExit("Research session failed; continuous restart stopped")
        if not args.continuous:
            break


if __name__ == "__main__":
    main()
