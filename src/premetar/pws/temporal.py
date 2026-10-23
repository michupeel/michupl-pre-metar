"""Temporal diagnostics adapted from Qwen's proposal after correctness review."""

import math
from datetime import datetime
from statistics import median
from typing import Any

from premetar.pws.models import utc


def temporal_metrics(
    samples: list[tuple[datetime, float]],
    now: datetime,
    expected_interval: float | None = None,
    stale_seconds: float = 1800,
    stuck_seconds: float = 21600,
    jump_c_per_min: float = 2,
    peer_range_c: float | None = None,
) -> dict[str, Any]:
    now = utc(now)
    for threshold in (stale_seconds, stuck_seconds, jump_c_per_min, expected_interval):
        if threshold is not None and (not math.isfinite(threshold) or threshold <= 0):
            raise ValueError("Thresholds must be finite and positive")
    if peer_range_c is not None and (not math.isfinite(peer_range_c) or peer_range_c < 0):
        raise ValueError("Peer range must be finite and nonnegative")
    flags: set[str] = set()
    unique: dict[datetime, float] = {}
    for time, value in samples:
        time = utc(time)
        if not math.isfinite(value):
            raise ValueError("Nonfinite temperature")
        if time > now:
            flags.add("CLOCK_ANOMALY")
            continue
        if time in unique and unique[time] != value:
            flags.add("CONFLICTING_DUPLICATE")
        unique.setdefault(time, value)
    ordered = sorted(unique.items())
    intervals = [(b[0] - a[0]).total_seconds() for a, b in zip(ordered, ordered[1:], strict=False)]
    age = (now - ordered[-1][0]).total_seconds() if ordered else None
    if age is not None and age > stale_seconds:
        flags.add("STALE_DATA")
    med = median(intervals) if intervals else None
    p90 = sorted(intervals)[math.ceil(0.9 * len(intervals)) - 1] if intervals else None
    if med and p90 and p90 > 3 * med:
        flags.add("IRREGULAR_UPDATES")
    missing = availability = None
    span = (ordered[-1][0] - ordered[0][0]).total_seconds() if intervals else 0
    if intervals and expected_interval:
        missing = sum(max(0, math.floor(g / expected_interval) - 1) for g in intervals)
        availability = min(1, len(ordered) / (1 + span / expected_interval))
        if missing:
            flags.add("MISSING_INTERVALS")
    if intervals and span >= stuck_seconds and len({v for _, v in ordered}) == 1:
        flags.add(
            "STUCK_SENSOR" if peer_range_c is not None and peer_range_c >= 2 else "STUCK_SUSPECT"
        )
    if any(
        abs(b[1] - a[1]) / (gap / 60) > jump_c_per_min
        for a, b, gap in zip(ordered, ordered[1:], intervals, strict=False)
    ):
        flags.add("TEMPERATURE_SPIKE")
    return {
        "median_update_interval": med,
        "p90_update_interval": p90,
        "observation_age": age,
        "longest_gap": max(intervals) if intervals else None,
        "missing_intervals": missing,
        "availability": availability,
        "sample_count": len(ordered),
        "flags": sorted(flags),
    }
