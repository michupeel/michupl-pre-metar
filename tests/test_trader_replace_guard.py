"""Accidental SQLite REPLACE must not rewrite first-receipt evidence."""

from datetime import UTC, datetime
from pathlib import Path

from premetar.research.trader_store import TraderStore


def test_sql_replace_cannot_rewrite_event_by_key_or_primary_id(tmp_path: Path) -> None:
    store = TraderStore(tmp_path / "research.sqlite3")
    store.append("TRADE", {"price": "0.98"}, datetime(2026, 10, 27, tzinfo=UTC), "one")
    original = store.connection.execute("SELECT * FROM events").fetchone()
    for sql in (
        "INSERT OR REPLACE INTO events(id,kind,received_at,event_key,payload,payload_hash) VALUES(1,'OTHER','later','other','{}','changed')",
        "INSERT OR REPLACE INTO events(kind,received_at,event_key,payload,payload_hash) VALUES('TRADE','later','one','{}','changed')",
    ):
        with store.connection:
            store.connection.execute(sql)
        assert store.connection.execute("SELECT * FROM events").fetchall() == [original]
    assert store.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    store.close()
