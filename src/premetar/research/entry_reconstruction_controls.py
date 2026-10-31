"""Past-only matching. Operational no-entry labels never prove absence of trades."""

import math
from typing import Any

from premetar.research.entry_timing_monitor import clock


def match_controls(
    entry: dict[str, Any], candidates: list[dict[str, Any]], limit: int = 3
) -> list[dict[str, Any]]:
    if not 1 <= limit <= 10:
        raise ValueError("Control limit must be 1..10")
    cutoff = clock(entry.get("received_at"))
    if cutoff is None or not entry.get("station") or not entry.get("settlement_day"):
        return []

    def numeric(row: dict[str, Any]) -> bool:
        return (
            all(
                type(row.get(k)) in (int, float) and math.isfinite(row[k])
                for k in ("price", "spread", "depth")
            )
            and row["depth"] > 0
        )

    if not numeric(entry):
        return []
    ranked = []
    for candidate in candidates:
        receipt = clock(candidate.get("received_at"))
        if not receipt or not 0 <= (cutoff - receipt).total_seconds() <= 10:
            continue
        if any(candidate.get(k) != entry.get(k) for k in ("station", "settlement_day")):
            continue
        if (
            not candidate.get("condition_id")
            or candidate["condition_id"] == entry.get("condition_id")
            or not numeric(candidate)
        ):
            continue
        pd, sd = (
            abs(candidate["price"] - entry["price"]),
            abs(candidate["spread"] - entry["spread"]),
        )
        if (
            pd > 0.0200000001
            or sd > 0.0200000001
            or not 0.5 <= candidate["depth"] / entry["depth"] <= 2
        ):
            continue
        ranked.append((pd, sd, candidate["condition_id"], candidate))
    ranked.sort(key=lambda row: row[:3])
    selected: dict[str, dict[str, Any]] = {}
    for _, _, condition, candidate in ranked:
        selected.setdefault(
            condition,
            dict(
                candidate,
                label="PENDING_DELAYED_ATTRIBUTION",
                control_scope="RECORDED_UNIVERSE_MATCH_NOT_PROVEN_NO_ENTRY",
                matched_at=entry["received_at"],
            ),
        )
    return list(selected.values())[:limit]
