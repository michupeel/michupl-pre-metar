"""Descriptive features adapted from Qwen I2; missing evidence stays NULL."""

from datetime import timedelta
from decimal import Decimal
from typing import Any

from premetar.research.entry_timing_monitor import clock

FIELDS = (
    "bid",
    "ask",
    "mid",
    "spread",
    "bid_quantity",
    "ask_quantity",
    "bid_depth",
    "ask_depth",
    "imbalance",
)


def snapshot_features(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    result: dict[str, Any] = dict.fromkeys(FIELDS)
    if snapshot is None:
        return result
    bids, asks = snapshot["bids"], snapshot["asks"]
    bd = sum((Decimal(str(p["size"])) for p in bids), Decimal(0))
    ad = sum((Decimal(str(p["size"])) for p in asks), Decimal(0))
    result.update(
        bid_depth=float(bd),
        ask_depth=float(ad),
        imbalance=float((bd - ad) / (bd + ad)) if bd + ad else None,
    )
    for side, levels in (("bid", bids), ("ask", asks)):
        if levels:
            result[side] = float(Decimal(str(levels[0]["price"])))
            result[side + "_quantity"] = float(Decimal(str(levels[0]["size"])))
    if bids and asks:
        bid, ask = Decimal(str(bids[0]["price"])), Decimal(str(asks[0]["price"]))
        result.update(mid=float((bid + ask) / 2), spread=float(ask - bid))
    return result


def price_changes(points: list[dict[str, Any]], cutoff: str) -> dict[str, Any]:
    at = clock(cutoff)
    if at is None:
        raise ValueError("Aware cutoff required")
    values = sorted(
        ((t, p) for p in points if (t := clock(p.get("received_at"))) is not None and t <= at),
        key=lambda pair: pair[0],
    )

    def mid_before(seconds: int) -> float | None:
        target = at - timedelta(seconds=seconds)
        eligible = [(t, p) for t, p in values if t <= target]
        if not eligible or (target - eligible[-1][0]).total_seconds() > 10:
            return None
        value: float | None = snapshot_features(eligible[-1][1])["mid"]
        return value

    current = mid_before(0)
    mids = {h: mid_before(h) for h in (5, 15, 30, 60, 180)}
    result: dict[str, Any] = {
        f"change_{h}s": current - old if current is not None and old is not None else None
        for h, old in mids.items()
    }
    m15, m30 = mids[15], mids[30]
    result["reversal_30s"] = (
        ((current - m15) * (m15 - m30) < 0)
        if current is not None and m15 is not None and m30 is not None
        else None
    )
    # One-sided books still contain observed prices; missing midpoint isn't no data.
    adjacent = []
    for (before, p), (after, q) in zip(values, values[1:], strict=False):
        a, b = snapshot_features(p)["bid"], snapshot_features(q)["bid"]
        if a is not None and b is not None and (after - before).total_seconds() <= 10:
            adjacent.append((b - a, after.isoformat()))
    jump = max(adjacent, default=None, key=lambda pair: pair[0])
    result["largest_adjacent_bid_increase"] = jump[0] if jump else None
    result["largest_adjacent_bid_increase_received_at"] = jump[1] if jump else None
    return result
