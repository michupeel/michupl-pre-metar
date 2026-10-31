"""Bounded snapshot evidence. Gaps/deltas never certify executable depth."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from premetar.research.entry_reconstruction_clocks import known_clock
from premetar.research.entry_reconstruction_levels import update_levels
from premetar.research.entry_timing_monitor import clock, top_levels


class BookRing:
    def __init__(self, max_tokens: int = 64, max_states: int = 180) -> None:
        if not 1 <= max_tokens <= 256 or not 1 <= max_states <= 600:
            raise ValueError("Invalid ring budget")
        self.max_tokens, self.max_states = max_tokens, max_states
        self.histories: dict[str, list[dict[str, Any]]] = {}
        self.depth: dict[str, dict[str, Any]] = {}

    def add(self, row: dict[str, Any]) -> bool:
        p, receipt, identity = row.get("payload"), clock(row.get("received_at")), row.get("id")
        if not isinstance(p, dict) or receipt is None or type(identity) is not int or identity < 1:
            return False
        token = p.get("token_id")
        if not isinstance(token, str) or not token.strip() or p.get("complete") is not True:
            return False
        try:
            bids, asks = top_levels(p.get("bids"), True), top_levels(p.get("asks"), False)
        except (ValueError, TypeError):
            return False
        if bids and asks and Decimal(str(bids[0]["price"])) >= Decimal(str(asks[0]["price"])):
            return False
        history = self.histories.get(token, [])
        if history:
            last = history[-1]
            if identity <= last["local_version"] or receipt < known_clock(last["received_at"]):
                return False
            if (p.get("connection_id"), p.get("source")) != (last["connection_id"], last["source"]):
                history = []
        record = dict(
            source_event_id=identity,
            local_version=identity,
            received_at=receipt.isoformat(),
            token_id=token,
            connection_id=p.get("connection_id"),
            source=p.get("source"),
            source_hash=p.get("hash"),
            exchange_timestamp=p.get("source_timestamp"),
            bids=bids,
            asks=asks,
            depth_scope="TOP_5_SNAPSHOT_ONLY_NOT_EXECUTION_PROOF",
            seed_event_id=identity,
            sequence_guarantee="UNAVAILABLE",
            capture_database=p.get("capture_database"),
            capture_id=p.get("capture_id"),
        )
        # Retain bounded full seed only for optional research delta reconstruction.
        if len(p["bids"]) + len(p["asks"]) <= 4096:
            self.depth[token] = dict(record, bids=p["bids"], asks=p["asks"])
        else:
            self.depth.pop(token, None)
        history = [
            b for b in history if known_clock(b["received_at"]) >= receipt - timedelta(seconds=300)
        ]
        self.histories.pop(token, None)
        self.histories[token] = (history + [record])[-self.max_states :]
        while len(self.histories) > self.max_tokens:
            oldest = next(iter(self.histories))
            del self.histories[oldest]
            self.depth.pop(oldest, None)
        return True

    def invalidate(self, token: str | None = None) -> None:
        if token is None:
            self.histories.clear()
            self.depth.clear()
        else:
            self.histories.pop(token, None)
            self.depth.pop(token, None)

    def delta(self, row: dict[str, Any]) -> int:
        """Experimental receive-order replay; BBO consistency is required, not fill proof.

        Absolute level replacement is checked against the packet's reported BBO.
        A missing/invalid seed, epoch, clock, BBO or malformed change invalidates it.
        No server sequence guarantee or exchange hash verification is invented.
        """
        p, receipt = row.get("payload"), clock(row.get("received_at"))
        if not isinstance(p, dict) or receipt is None or type(row.get("id")) is not int:
            self.invalidate()
            return 0
        changes = p.get("price_changes")
        if (
            not isinstance(changes, list)
            or not changes
            or any(not isinstance(c, dict) or not c.get("asset_id") for c in changes)
        ):
            self.invalidate()
            return 0
        grouped: dict[str, list[dict[str, Any]]] = {}
        for change in changes:
            grouped.setdefault(str(change["asset_id"]), []).append(change)
        successes = 0
        for token, updates in grouped.items():
            seed = self.depth.get(token)
            if (
                not seed
                or not p.get("connection_id")
                or p.get("connection_id") != seed.get("connection_id")
            ):
                self.invalidate(token)
                continue
            if row["id"] <= seed["local_version"] or receipt < known_clock(seed["received_at"]):
                self.invalidate(token)
                continue
            try:
                if any(c.get("side") not in {"BUY", "SELL"} for c in updates):
                    raise ValueError("Unknown side")
                bids = update_levels(seed["bids"], [c for c in updates if c["side"] == "BUY"])
                asks = update_levels(seed["asks"], [c for c in updates if c["side"] == "SELL"])
                if len(bids) + len(asks) > 4096:
                    raise ValueError("Depth budget exceeded")
                best_bid = Decimal(bids[-1]["price"]) if bids else Decimal(0)
                best_ask = Decimal(asks[0]["price"]) if asks else Decimal(1)
                if (
                    best_bid >= best_ask
                    or str(updates[-1].get("best_bid")) != str(best_bid)
                    or str(updates[-1].get("best_ask")) != str(best_ask)
                ):
                    # Numeric equality permits provider decimal formatting differences.
                    if (
                        best_bid >= best_ask
                        or Decimal(str(updates[-1].get("best_bid"))) != best_bid
                        or Decimal(str(updates[-1].get("best_ask"))) != best_ask
                    ):
                        raise ValueError("Reported BBO inconsistent")
                prior_exchange = seed.get("exchange_timestamp")
                new_exchange = p.get("source_timestamp")
                if (
                    prior_exchange is not None
                    and new_exchange is not None
                    and int(new_exchange) < int(prior_exchange)
                ):
                    raise ValueError("Exchange clock regression")
                synthetic = dict(
                    row,
                    payload=dict(
                        seed,
                        token_id=token,
                        complete=True,
                        bids=bids,
                        asks=asks,
                        source=seed["source"],
                        hash=None,
                        source_timestamp=new_exchange,
                    ),
                )
                if not self.add(synthetic):
                    raise ValueError("Reconstructed depth invalid")
                current = self.histories[token][-1]
                current.update(
                    seed_event_id=seed["seed_event_id"],
                    depth_scope="LOCAL_RECEIVE_ORDER_RECONSTRUCTION_NOT_EXECUTABLE_PROOF",
                    update_kind="WS_DELTA",
                    delta_hash=updates[-1].get("hash"),
                )
                self.depth[token].update(current, bids=bids, asks=asks)
                successes += 1
            except (ValueError, TypeError, ArithmeticError):
                self.invalidate(token)
        return successes

    def window(self, token: str, cutoff: datetime) -> list[dict[str, Any]]:
        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ValueError("Aware cutoff required")
        cutoff = cutoff.astimezone(UTC)
        return [
            b
            for b in self.histories.get(token, [])
            if cutoff - timedelta(seconds=300) <= known_clock(b["received_at"]) <= cutoff
        ]

    def latest(self, token: str, cutoff: datetime, max_age: float = 10) -> dict[str, Any] | None:
        values = self.window(token, cutoff)
        last = values[-1] if values else None
        if (
            last
            and (cutoff.astimezone(UTC) - known_clock(last["received_at"])).total_seconds()
            <= max_age
        ):
            return dict(
                last,
                freshness_seconds=(
                    cutoff.astimezone(UTC) - known_clock(last["received_at"])
                ).total_seconds(),
            )
        return None
