"""EXP0018.1 descriptive book-state classification."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from premetar.research.entry_timing_monitor import clock, top_levels


def book_state(book: dict[str, Any] | None, at: datetime, max_age: float = 10) -> str:
    if not isinstance(at, datetime):
        raise ValueError("at must be a datetime")
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("at must be timezone-aware")

    if book is None:
        return "NO_INITIAL_SNAPSHOT"

    if book.get("gap", False):
        return "RECONNECT_GAP"
    if not book.get("mapping_verified", True):
        return "INVALID_TOKEN_MAPPING"
    if book.get("complete") is not True:
        return "UNKNOWN_STATE"

    received_at_str = book.get("received_at")
    if not isinstance(received_at_str, str):
        return "INCONSISTENT_BOOK"

    received_at = clock(received_at_str)
    if received_at is None:
        return "INCONSISTENT_BOOK"

    now_utc: datetime = at.astimezone(UTC)
    if received_at > now_utc:
        return "INCONSISTENT_BOOK"

    age: float = (now_utc - received_at).total_seconds()
    if age > max_age:
        return "STALE_BOOK"

    bids_raw = book.get("bids")
    asks_raw = book.get("asks")

    if not isinstance(bids_raw, list) or not isinstance(asks_raw, list):
        return "INCONSISTENT_BOOK"

    try:
        bids = top_levels(book.get("bids"), True)
        asks = top_levels(book.get("asks"), False)
    except ValueError:
        return "INCONSISTENT_BOOK"

    if not bids and not asks:
        return "VALID_EMPTY_BOOK"

    if bids and asks:
        bid_p = Decimal(str(bids[0]["price"]))
        ask_p = Decimal(str(asks[0]["price"]))
        if bid_p >= ask_p:
            return "INCONSISTENT_BOOK"

    if bids and asks:
        return "VALID_TWO_SIDED_BOOK"
    elif bids or asks:
        return "VALID_ONE_SIDED_BOOK"
    else:
        return "VALID_EMPTY_BOOK"
