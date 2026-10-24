"""Conservative in-process barrier while a received reference awaits durable parsing."""

from datetime import datetime
from threading import Lock


class ReferenceGate:
    def __init__(self) -> None:
        self._lock = Lock()
        self._pending: dict[str, tuple[set[str], datetime]] = {}

    def begin(self, source: str, stations: set[str], received_at: datetime) -> None:
        with self._lock:
            self._pending[source] = (set(stations), received_at)

    def end(self, source: str) -> None:
        with self._lock:
            self._pending.pop(source, None)

    def check(self, airport: str) -> None:
        with self._lock:
            if any(airport in stations for stations, _ in self._pending.values()):
                raise ValueError("REFERENCE_RECEIPT_PENDING_DURABLE_PARSE")
