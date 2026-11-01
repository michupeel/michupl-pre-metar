"""Research surge definitions, not a trading strategy."""

from __future__ import annotations

import math
from typing import Any, TypeGuard


def _is_finite(v: Any) -> TypeGuard[float]:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def detect_changes(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    price_jump: float = 0.10,
    depth_jump: float = 100,
    spread_jump: float = 0.05,
) -> list[dict[str, Any]]:
    from premetar.research.entry_timing_monitor import clock

    if (
        not after.get("token_id")
        or not after.get("connection_id")
        or any(before.get(k) != after.get(k) for k in ("token_id", "connection_id"))
    ):
        return []
    recv_before, recv_after = clock(before.get("received_at")), clock(after.get("received_at"))
    if recv_before is None or recv_after is None:
        return []
    elapsed = (recv_after - recv_before).total_seconds()
    if not 0 < elapsed <= 5:
        return []

    events: list[dict[str, Any]] = []

    def _emit(kind: str, field: str, delta: float, before_val: float, after_val: float) -> None:
        rel = delta / abs(before_val) if before_val != 0 else None
        events.append(
            {
                "kind": kind,
                "field": field,
                "delta": delta,
                "before": before_val,
                "after": after_val,
                "elapsed_seconds": elapsed,
                "received_at": recv_after.isoformat(),
                "relative_change": rel,
            }
        )

    for fprefix in ("bid", "ask"):
        b = before.get(fprefix)
        a = after.get(fprefix)
        if _is_finite(b) and _is_finite(a):
            delta = a - b
            if abs(delta) >= price_jump:
                kind = f"{fprefix.upper()}_SURGE" if delta > 0 else f"{fprefix.upper()}_COLLAPSE"
                _emit(kind, fprefix, delta, float(b), float(a))

    for fprefix in ("bid_depth", "ask_depth"):
        b = before.get(fprefix)
        a = after.get(fprefix)
        if _is_finite(b) and _is_finite(a):
            if b < 0 or a < 0:
                continue
            delta = a - b
            max_d = max(float(b), 1.0)
            if abs(delta) >= depth_jump and abs(delta) >= 0.5 * max_d:
                kind = "LIQUIDITY_APPEARANCE" if delta > 0 else "LIQUIDITY_WITHDRAWAL"
                _emit(kind, fprefix, delta, float(b), float(a))

    b_spread = before.get("spread")
    a_spread = after.get("spread")
    if _is_finite(b_spread) and _is_finite(a_spread):
        delta = a_spread - b_spread
        if abs(delta) >= spread_jump:
            kind = "SPREAD_COMPRESSION" if delta < 0 else "SPREAD_EXPANSION"
            _emit(kind, "spread", delta, float(b_spread), float(a_spread))

    return events
