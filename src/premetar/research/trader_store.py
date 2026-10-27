"""Append-only, independently persisted public trader research evidence."""

import json
import sqlite3
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any


def _utc(value: datetime | str) -> str:
    parsed = (
        datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Receipt timestamp must be timezone-aware")
    return parsed.astimezone(UTC).isoformat()


class TraderStore:
    """One writer connection; every append is a short committed transaction."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.connection = sqlite3.connect(path, timeout=5)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY,
                kind TEXT NOT NULL,
                received_at TEXT NOT NULL,
                event_key TEXT,
                payload TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                UNIQUE(kind, event_key)
            );
            CREATE INDEX IF NOT EXISTS trader_events_kind_id ON events(kind,id);
            CREATE INDEX IF NOT EXISTS trader_source_clock ON events(json_extract(payload,'$.source_trade_timestamp') DESC) WHERE kind='TRADE';
            CREATE TRIGGER IF NOT EXISTS trader_events_no_update
                BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'immutable research event'); END;
            CREATE TRIGGER IF NOT EXISTS trader_events_no_delete
                BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'immutable research event'); END;
            CREATE TRIGGER IF NOT EXISTS trader_events_no_replace
                BEFORE INSERT ON events WHEN EXISTS(
                    SELECT 1 FROM events WHERE id=NEW.id OR
                    (NEW.event_key IS NOT NULL AND kind=NEW.kind AND event_key=NEW.event_key)
                ) BEGIN SELECT RAISE(IGNORE); END;
        """)

    def append(
        self,
        kind: str,
        payload: dict[str, Any],
        received_at: datetime | str,
        key: str | None = None,
    ) -> bool:
        """Preserve first receipt on duplicate (kind,key); NULL keys are distinct events."""
        if not kind or len(kind) > 80:
            raise ValueError("Invalid event kind")
        timestamp = _utc(received_at)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        digest = sha256(encoded.encode()).hexdigest()
        with self.connection:
            cursor = self.connection.execute(
                "INSERT OR IGNORE INTO events(kind,received_at,event_key,payload,payload_hash) "
                "VALUES (?,?,?,?,?)",
                (kind, timestamp, key, encoded, digest),
            )
        return cursor.rowcount == 1

    def events(self, kind: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return _events(self.connection, kind, limit)

    def close(self) -> None:
        self.connection.close()


def _events(connection: sqlite3.Connection, kind: str | None, limit: int) -> list[dict[str, Any]]:
    if limit < 1 or limit > 1_000_000:
        raise ValueError("Limit must be between 1 and 1000000")
    clause = " WHERE kind=?" if kind is not None else ""
    params: tuple[Any, ...] = (kind, limit) if kind is not None else (limit,)
    rows = connection.execute(
        "SELECT id,kind,received_at,event_key,payload,payload_hash FROM events"
        + clause
        + " ORDER BY id DESC LIMIT ?",
        params,
    ).fetchall()
    return [
        {
            "id": row[0],
            "kind": row[1],
            "received_at": row[2],
            "key": row[3],
            "payload": json.loads(row[4]),
            "payload_hash": row[5],
        }
        for row in reversed(rows)
    ]


def readonly_connection(path: Path) -> sqlite3.Connection:
    """Never creates a DB; query_only provides an additional write guard."""
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    connection.execute("PRAGMA query_only=ON")
    return connection


def read_events(path: Path, kind: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    connection = readonly_connection(path)
    try:
        return _events(connection, kind, limit)
    finally:
        connection.close()


def read_status(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"state": "NOT_STARTED", "counts": {}}
    connection = readonly_connection(path)
    try:
        counts = dict(connection.execute("SELECT kind,COUNT(*) FROM events GROUP BY kind"))
        health = _events(connection, "HEALTH", 1)
        run = _events(connection, "RUN", 1)
        return {
            "state": "RECORDED_STATUS_CHECK_HEARTBEAT",
            "counts": counts,
            "health": health[-1] if health else None,
            "run": run[-1] if run else None,
        }
    finally:
        connection.close()
