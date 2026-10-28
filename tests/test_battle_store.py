"""Synthetic, isolated paper-ledger durability; never touches collector databases."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from premetar.research.battle_store import BattleStore, StorageLimit, read_battle

AT = datetime(2026, 10, 28, 10, tzinfo=UTC)


def store(path: Path, **kwargs: int) -> BattleStore:
    return BattleStore(path, min_free_bytes=0, **kwargs)


def event(at: datetime = AT) -> dict[str, object]:
    return dict(kind="ORDER", at=at, payload={"cash": "99.03", "quantity": "1"})


def test_atomic_restart_and_sequence(tmp_path: Path) -> None:
    journal = store(tmp_path)
    journal.commit([event()], {"cash": "99.03"}, {"source": 12}, AT)
    journal.close()
    journal = store(tmp_path)
    assert journal.restore() == ({"cash": "99.03"}, {"source": 12})
    journal.commit(
        [event(AT + timedelta(seconds=1))],
        {"cash": "98.06"},
        {"source": 13},
        AT + timedelta(seconds=1),
    )
    rows = journal.read_events()
    assert [r["id"] for r in rows] == [1, 2]
    assert rows[1]["previous_hash"] == rows[0]["payload_hash"]
    assert journal.connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    journal.close()


def test_daily_rotation_inherits_cash_and_cursors(tmp_path: Path) -> None:
    journal = store(tmp_path)
    journal.commit([event()], {"cash": "50"}, {"source": 100}, AT)
    journal.commit(
        [event(AT + timedelta(days=1))], {"cash": "49"}, {"source": 101}, AT + timedelta(days=1)
    )
    assert len(journal.paths()) == 2
    assert [r["id"] for r in journal.read_events()] == [1, 2]
    journal.close()
    journal = store(tmp_path)
    assert journal.restore() == ({"cash": "49"}, {"source": 101})
    journal.close()


def test_size_rotation_without_deleting_old_events(tmp_path: Path) -> None:
    journal = store(tmp_path, max_segment_bytes=1)
    journal.commit([event()], {"cash": "99"}, {}, AT)
    journal.commit([event()], {"cash": "98"}, {}, AT)
    assert len(journal.paths()) == 2
    assert len(journal.read_events()) == 2
    journal.close()


def test_malformed_event_does_not_advance_checkpoint_or_partial_write(tmp_path: Path) -> None:
    journal = store(tmp_path)
    journal.commit([event()], {"cash": "99"}, {"source": 1}, AT)
    with pytest.raises(ValueError):
        journal.commit(
            [event(), dict(kind="BAD", payload={"bad": float("nan")})],
            {"cash": "0"},
            {"source": 2},
            AT,
        )
    assert journal.restore() == ({"cash": "99"}, {"source": 1})
    assert len(journal.read_events()) == 1
    journal.close()


def test_transaction_failure_rolls_back_events_and_checkpoint(tmp_path: Path) -> None:
    journal = store(tmp_path)
    journal.commit([event()], {"cash": "99"}, {}, AT)
    journal.connection.executescript(
        "CREATE TRIGGER fail_checkpoint BEFORE INSERT ON checkpoint BEGIN SELECT RAISE(ABORT,'synthetic disk failure'); END;"
    )
    with pytest.raises(sqlite3.IntegrityError):
        journal.commit([event()], {"cash": "0"}, {}, AT)
    assert len(journal.read_events()) == 1
    assert journal.restore() == ({"cash": "99"}, {})
    journal.close()


def test_readonly_asof_and_truncation(tmp_path: Path) -> None:
    journal = store(tmp_path)
    journal.commit([event()], {}, {}, AT)
    journal.commit([event(AT + timedelta(seconds=1))], {}, {}, AT + timedelta(seconds=1))
    rows = read_battle(tmp_path, AT)
    assert len(rows) == 1 and rows[0]["id"] == 1
    limited = read_battle(tmp_path, limit=1)
    assert limited.metadata["truncated"] is True
    assert limited[0]["id"] == 2
    journal.close()


def test_events_immutable_including_replace(tmp_path: Path) -> None:
    journal = store(tmp_path)
    journal.commit([event()], {}, {}, AT)
    for sql in (
        "DELETE FROM events",
        "UPDATE events SET kind='HACK'",
        "INSERT OR REPLACE INTO events SELECT * FROM events",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            journal.connection.execute(sql)
        journal.connection.rollback()
    assert len(journal.read_events()) == 1
    journal.close()


def test_untrusted_manifest_and_empty_orphan_cannot_reset_cash(tmp_path: Path) -> None:
    journal = store(tmp_path)
    journal.commit([event()], {"cash": "42"}, {"source": 123}, AT)
    journal.close()
    (tmp_path / "battle-000002.sqlite3").touch()
    (tmp_path / "manifest.json").write_text(json.dumps({"active": "../../outside.sqlite3"}))
    journal = store(tmp_path)
    assert journal.restore() == ({"cash": "42"}, {"source": 123})
    assert not (tmp_path.parent / "outside.sqlite3").exists()
    journal.close()


def test_rotation_checkpoint_recovers_without_manifest(tmp_path: Path) -> None:
    journal = store(tmp_path)
    journal.commit([event()], {"cash": "41"}, {}, AT)
    journal.commit([event(AT + timedelta(days=1))], {"cash": "40"}, {}, AT + timedelta(days=1))
    journal.close()
    (tmp_path / "manifest.json").unlink()
    journal = store(tmp_path)
    assert journal.restore() == ({"cash": "40"}, {})
    journal.close()


def test_storage_guard_before_commit_preserves_history(tmp_path: Path) -> None:
    journal = store(tmp_path)
    journal.commit([event()], {"cash": "10"}, {}, AT)
    journal.max_total_bytes = 1
    with pytest.raises(StorageLimit):
        journal.commit([event()], {"cash": "0"}, {}, AT)
    assert journal.restore() == ({"cash": "10"}, {})
    assert len(journal.read_events()) == 1
    journal.close()


def test_read_nonexistent_database_creates_nothing(tmp_path: Path) -> None:
    path = tmp_path / "missing"
    assert read_battle(path) == []
    assert not path.exists()


def test_reader_during_inflight_writer_sees_only_committed_events(tmp_path: Path) -> None:
    journal = store(tmp_path)
    journal.commit([event()], {"cash": "99"}, {}, AT)
    journal.connection.execute("BEGIN IMMEDIATE")
    journal.connection.execute(
        "INSERT INTO events VALUES (2,'ORDER',?,'{}','pending','previous')",
        ((AT + timedelta(seconds=1)).isoformat(timespec="microseconds"),),
    )
    assert [r["id"] for r in read_battle(tmp_path)] == [1]
    journal.connection.rollback()
    assert journal.restore() == ({"cash": "99"}, {})
    journal.close()


def test_backwards_commit_cannot_rewrite_asof_history(tmp_path: Path) -> None:
    journal = store(tmp_path)
    journal.commit([event()], {"cash": "99"}, {}, AT)
    with pytest.raises(ValueError, match="backwards"):
        journal.commit([], {"cash": "100"}, {}, AT - timedelta(seconds=1))
    assert journal.restore() == ({"cash": "99"}, {})
    journal.close()


def test_future_event_and_naive_timestamp_rejected(tmp_path: Path) -> None:
    journal = store(tmp_path)
    with pytest.raises(ValueError, match="Future"):
        journal.commit([event(AT + timedelta(seconds=1))], {}, {}, AT)
    with pytest.raises(ValueError, match="timezone"):
        journal.commit([], {}, {}, AT.replace(tzinfo=None))
    assert not journal.read_events()
    journal.close()
