import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from premetar.research.trader_reports import generate_reports
from premetar.research.trader_store import (
    TraderStore,
    read_events,
    read_status,
    readonly_connection,
)


def test_duplicate_preserves_first_receipt_and_payload(tmp_path: Path) -> None:
    path = tmp_path / "monitor.db"
    store = TraderStore(path)
    first = datetime(2026, 10, 27, tzinfo=UTC)
    assert store.append("TRADE", {"price": 0.5}, first, "tx1")
    assert not store.append("TRADE", {"price": 0.6}, first + timedelta(seconds=30), "tx1")
    store.close()
    (record,) = read_events(path)
    assert record["received_at"] == first.isoformat()
    assert record["payload"] == {"price": 0.5}


def test_restart_recovers_dedup(tmp_path: Path) -> None:
    path = tmp_path / "monitor.db"
    now = datetime.now(UTC)
    store = TraderStore(path)
    store.append("TRADE", {}, now, "a")
    store.close()
    recovered = TraderStore(path)
    assert not recovered.append("TRADE", {}, now, "a")
    assert recovered.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    recovered.close()


def test_immutable_and_readonly(tmp_path: Path) -> None:
    path = tmp_path / "monitor.db"
    store = TraderStore(path)
    store.append("TRADE", {}, datetime.now(UTC), "a")
    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute("UPDATE events SET kind='X'")
    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute("DELETE FROM events")
    reader = readonly_connection(path)
    with pytest.raises(sqlite3.OperationalError):
        reader.execute("INSERT INTO events(kind) VALUES ('X')")
    reader.close()
    store.close()


def test_missing_read_does_not_create(tmp_path: Path) -> None:
    path = tmp_path / "missing.db"
    assert read_events(path) == []
    assert read_status(path)["state"] == "NOT_STARTED"
    assert not path.exists()


def test_invalid_payload_and_timestamp_leave_no_rows(tmp_path: Path) -> None:
    store = TraderStore(tmp_path / "monitor.db")
    with pytest.raises(ValueError):
        store.append("X", {}, datetime(2026, 10, 27))
    with pytest.raises(ValueError):
        store.append("X", {"bad": float("nan")}, datetime.now(UTC))
    assert store.events() == []
    store.close()


def test_distinct_raw_responses_and_ordering(tmp_path: Path) -> None:
    store = TraderStore(tmp_path / "monitor.db")
    now = datetime.now(UTC)
    for i in range(5):
        store.append("RAW", {"poll": i}, now)
    assert [row["payload"]["poll"] for row in store.events(limit=2)] == [3, 4]
    store.close()


def test_report_while_writer_open_and_empty_data(tmp_path: Path) -> None:
    path = tmp_path / "monitor.db"
    store = TraderStore(path)
    store.append("HEALTH", {"state": "HEALTHY"}, datetime.now(UTC))
    result = generate_reports(path, tmp_path / "reports")
    assert result["trades_exported"] == 0
    assert "INSUFFICIENT DATA" in (tmp_path / "reports/hightemptation_shadow_pnl.md").read_text()
    assert read_status(path)["counts"] == {"HEALTH": 1}
    store.close()


def test_report_preserves_payload_nested_values(tmp_path: Path) -> None:
    path = tmp_path / "monitor.db"
    store = TraderStore(path)
    store.append(
        "TRADE",
        {"trade_id": "tx", "evidence_class": "HISTORICAL", "nested": [1, 2]},
        datetime.now(UTC),
    )
    result = generate_reports(path, tmp_path / "reports")
    assert result["trades_exported"] == 1
    assert read_events(path)[0]["payload"]["nested"] == [1, 2]
    store.close()


def test_reader_sees_only_committed_evidence_during_write(tmp_path: Path) -> None:
    path = tmp_path / "monitor.db"
    store = TraderStore(path)
    now = datetime.now(UTC)
    store.append("TRADE", {"trade_id": "first"}, now, "first")
    store.connection.execute("BEGIN IMMEDIATE")
    store.connection.execute(
        "INSERT INTO events(kind,received_at,event_key,payload,payload_hash) VALUES(?,?,?,?,?)",
        ("TRADE", now.isoformat(), "uncommitted", '{"trade_id":"uncommitted"}', "fixture"),
    )
    assert len(read_events(path)) == 1
    assert generate_reports(path, tmp_path / "reports")["trades_exported"] == 1
    store.connection.rollback()
    assert len(read_events(path)) == 1
    assert store.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    store.close()


def test_latency_summary_excludes_bootstrap_and_gap_censored(tmp_path: Path) -> None:
    path = tmp_path / "monitor.db"
    store = TraderStore(path)
    for i, (classification, delay) in enumerate(
        [
            ("BOOTSTRAP_HISTORICAL", 100000),
            ("GAP_CENSORED", 1000),
            ("PROSPECTIVE_POLL", 2),
            ("PROSPECTIVE_POLL", 4),
        ]
    ):
        store.append(
            "TRADE",
            {
                "trade_id": str(i),
                "evidence_class": classification,
                "trade_detection_latency": delay,
                "slug": "highest-temperature-in-warsaw-on-october-27-2026",
                "side": "BUY",
                "outcome": "No",
                "price": 0.98,
                "order_role": "UNKNOWN",
            },
            datetime.now(UTC),
            str(i),
        )
    generate_reports(path, tmp_path / "reports")
    report = (tmp_path / "reports/hightemptation_live_activity.md").read_text(encoding="utf-8")
    assert "3.000s (N=2)" in report
    assert "| warsaw | TMAX | BUY | No | UNKNOWN | 0.97–1.00 | 4 |" in report
    store.close()
