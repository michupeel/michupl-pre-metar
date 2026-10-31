"""Receipt-clock helpers for EXP0018 only."""

from datetime import UTC, datetime


def elapsed_seconds(later: datetime, earlier: datetime) -> float:
    if later.utcoffset() is None or earlier.utcoffset() is None:
        raise ValueError("Both datetimes must be timezone-aware")
    utc_later = later.astimezone(UTC)
    utc_earlier = earlier.astimezone(UTC)
    return (utc_later - utc_earlier).total_seconds()


def known_clock(value: str) -> datetime:
    """Reparse an already validated receipt; never substitute now on failure."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("Aware receipt required")
    return parsed.astimezone(UTC)
