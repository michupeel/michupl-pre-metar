"""Pure recovery counters, reviewed/adapted from a local Qwen proposal."""

from datetime import UTC, datetime
from typing import Any


def transition(
    previous: dict[str, Any] | None,
    status: str,
    now: datetime,
    failures_to_inactive: int = 3,
    recoveries_to_active: int = 2,
) -> dict[str, Any]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Aware clock required")
    if status not in {"ACTIVE", "STALE", "NO_MEASUREMENT", "INVALID", "UNVERIFIED"}:
        raise ValueError("Unknown availability status")
    if failures_to_inactive < 1 or recoveries_to_active < 1:
        raise ValueError("Positive hysteresis required")
    old = previous or {}
    mode = old.get("mode", "UNVERIFIED")
    failures, good = int(old.get("fail_streak", 0)), int(old.get("good_streak", 0))
    if status == "UNVERIFIED":
        good = 0
    elif status == "ACTIVE":
        failures = 0
        good += 1
        if previous is None or mode != "INACTIVE" or good >= recoveries_to_active:
            mode = "ACTIVE"
    else:
        failures += 1
        good = 0
        if previous is None or mode != "ACTIVE" or failures >= failures_to_inactive:
            mode = "INACTIVE"
    return dict(
        mode=mode,
        fail_streak=failures,
        good_streak=good,
        last_checked=now.astimezone(UTC).isoformat(),
    )
