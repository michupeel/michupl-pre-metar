"""Bounded receive-ordered evidence. Capacity losses are never complete coverage."""

import json
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any

from premetar.research.entry_reconstruction_clocks import known_clock
from premetar.research.entry_timing_monitor import clock


class RollingBuffer:
    def __init__(self, max_events: int = 12000) -> None:
        if not 1 <= max_events <= 12000:
            raise ValueError("Invalid event budget")
        self.max_events = max_events
        self.events: deque[dict[str, Any]] = deque()
        self.last: dict[str, tuple[int, datetime]] = {}
        self.newest: datetime | None = None
        self.evicted = 0
        self.truncated_before: datetime | None = None

    def append(self, event: dict[str, Any]) -> bool:
        token, identity, receipt = (
            event.get("token_id"),
            event.get("source_event_id"),
            clock(event.get("received_at")),
        )
        if (
            not isinstance(token, str)
            or not token
            or type(identity) is not int
            or identity < 1
            or receipt is None
        ):
            return False
        if token not in self.last and len(self.last) >= 256:
            return False
        if token in self.last and (
            identity <= self.last[token][0] or receipt < self.last[token][1]
        ):
            return False
        copied = json.loads(json.dumps(event, allow_nan=False))
        copied["received_at"] = receipt.isoformat()
        self.newest = max(self.newest or receipt, receipt)
        self.events = deque(
            e
            for e in self.events
            if known_clock(e["received_at"]) >= self.newest - timedelta(seconds=300)
        )
        self.events.append(copied)
        self.last[token] = (identity, receipt)
        while sum(e["token_id"] == token for e in self.events) > 2000:
            for candidate in self.events:
                if candidate["token_id"] == token:
                    removed = known_clock(candidate["received_at"])
                    self.events.remove(candidate)
                    self.evicted += 1
                    self.truncated_before = max(self.truncated_before or removed, removed)
                    break
        while len(self.events) > self.max_events:
            removed = known_clock(self.events.popleft()["received_at"])
            self.evicted += 1
            self.truncated_before = max(self.truncated_before or removed, removed)
        return True

    def window(self, token: str, at: datetime, seconds: float = 300) -> dict[str, Any]:
        if at.utcoffset() is None or not 1 <= seconds <= 300:
            raise ValueError("Invalid aware window")
        at = at.astimezone(UTC)
        start = at - timedelta(seconds=seconds)
        events = [
            e
            for e in self.events
            if e["token_id"] == token and start <= known_clock(e["received_at"]) <= at
        ]
        partial = self.truncated_before is not None and start <= self.truncated_before
        return dict(
            events=events,
            capacity_evictions=self.evicted,
            coverage="PARTIAL_CAPACITY" if partial else "RECORDED_EVENTS_ONLY_NOT_CONTINUITY_PROOF",
        )
