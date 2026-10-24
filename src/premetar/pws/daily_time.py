"""Calendar boundaries and fold-preserving buckets, adapted from a Qwen proposal."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def local_day_bounds(day: date, timezone: str) -> tuple[datetime, datetime]:
    zone = ZoneInfo(timezone)
    return (
        datetime.combine(day, time.min, tzinfo=zone).astimezone(UTC),
        datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone).astimezone(UTC),
    )


def bucket_start(event: datetime, minutes: int, timezone: str) -> datetime:
    if event.tzinfo is None or event.utcoffset() is None:
        raise ValueError("Timezone-aware event required")
    if minutes <= 0 or 60 % minutes:
        raise ValueError("Bucket must be a positive divisor of 60")
    local = event.astimezone(ZoneInfo(timezone))
    return local.replace(
        minute=local.minute // minutes * minutes, second=0, microsecond=0
    ).astimezone(UTC)
