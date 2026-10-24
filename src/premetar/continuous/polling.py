"""Adaptive policy adapted from reviewed local Qwen proposal."""

import math
from datetime import datetime
from statistics import median

from premetar.pws.models import utc


def observation_interval(times: list[datetime]) -> float | None:
    unique = sorted({utc(t) for t in times})
    if len(unique) < 4:
        return None
    return median((b - a).total_seconds() for a, b in zip(unique, unique[1:], strict=False))


def next_interval(
    times: list[datetime], minimum: float, maximum: float, empty_count: int = 0
) -> float:
    if (
        not all(math.isfinite(x) for x in (minimum, maximum))
        or not 0 < minimum <= maximum
        or empty_count < 0
    ):
        raise ValueError("Invalid interval bounds")
    interval = max(minimum, min(maximum, observation_interval(times) or minimum))
    return float(min(maximum, interval * 2 ** min(empty_count, 4)))


def provider_state(
    *,
    disabled: bool = False,
    auth_failed: bool = False,
    rate_limited: bool = False,
    last_data_age: float | None = None,
    stale_after: float = 900,
    failures: int = 0,
) -> str:
    if disabled:
        return "DISABLED"
    if auth_failed:
        return "AUTH_FAILED"
    if rate_limited:
        return "RATE_LIMITED"
    if last_data_age is None or last_data_age > stale_after:
        return "STALE"
    return "DEGRADED" if failures else "HEALTHY"
