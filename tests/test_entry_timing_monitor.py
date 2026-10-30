"""Synthetic local-feed fixtures; no invented market executions are observed data."""

import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from premetar.continuous.locking import acquire
from premetar.research.battle_store import BattleStore
from premetar.research.entry_timing_monitor import (
    Monitor,
    clock,
    market_reference,
    publish_live,
    schedule_context,
    source_rows,
    status,
    weather_before,
)
from premetar.research.trader_normalizer import WALLET

AT = datetime(2026, 10, 29, 12, tzinfo=UTC)


def test_status_reads_metadata_after_windows_locked_byte(tmp_path: Path) -> None:
    path = tmp_path / "monitor.lock"
    lock = acquire(path, "synthetic-status")
    try:
        result = status(tmp_path)
        assert result["status"] == "RUNNING"
        assert result["pid"] == os.getpid()
    finally:
        lock.close()


def test_display_cache_recovers_committed_entry_not_new_forecast(store: Any) -> None:
    original = dict(
        trade_id="recorded",
        source_trade_timestamp=AT.isoformat(),
        original_first_detection=AT.isoformat(),
        sidecar_capture_time=AT.isoformat(),
        evidence_class="PROSPECTIVE_POLL",
        metadata={"station": "EPWA"},
        metar_schedule={"signed_offset_seconds": 125},
        weather={"status": "UNKNOWN"},
    )
    store.commit([dict(kind="ENTRY_OBSERVED", at=AT.isoformat(), payload=original)], {}, {}, AT)
    recovered = Monitor(store).state["latest_entries"]
    assert len(recovered) == 1
    assert recovered[0]["source_trade_timestamp"] == original["source_trade_timestamp"]
    assert recovered[0]["station"] == "EPWA"


@pytest.mark.parametrize("matching", [True, False])
def test_legacy_cache_requires_exact_recorded_endpoint_binding(store: Any, matching: bool) -> None:
    original = dict(
        trade_id="legacy",
        source_trade_timestamp=AT.isoformat(),
        original_first_detection=AT.isoformat(),
        sidecar_capture_time=AT.isoformat(),
        endpoint_receipts_known_at_capture=[
            dict(
                original_evidence=dict(
                    trade_id="legacy" if matching else "another-trade",
                    source_trade_timestamp=AT.isoformat(),
                    evidence_class="PROSPECTIVE_POLL",
                )
            )
        ],
    )
    store.commit([dict(kind="ENTRY_OBSERVED", at=AT.isoformat(), payload=original)], {}, {}, AT)
    recovered = Monitor(store).state["latest_entries"]
    assert len(recovered) == int(matching)


@pytest.fixture
def store(tmp_path: Path) -> Any:
    journal = BattleStore(tmp_path / "journal", min_free_bytes=0)
    yield journal
    journal.close()


def row(
    kind: str, payload: dict[str, Any], seconds: float = 0, identity: int = 1
) -> dict[str, Any]:
    return dict(
        id=identity,
        kind=kind,
        received_at=(AT + timedelta(seconds=seconds)).isoformat(),
        payload=payload,
    )


def market(station: str = "EPWA") -> dict[str, Any]:
    return dict(
        conditionId="0xcondition",
        clobTokenIds='["1","2"]',
        outcomes='["Yes","No"]',
        resolutionSource=f"https://aviationweather.gov/api/data/metar?ids={station}",
        description="Synthetic fixture",
        endDate="2026-10-29T12:00:00Z",
    )


def trade(identity: str = "trade1", **changes: Any) -> dict[str, Any]:
    return dict(
        trade_id=identity,
        trader_wallet=WALLET,
        side="BUY",
        outcome="No",
        slug="highest-temperature-in-warsaw-on-october-29-2026",
        condition_id="0xcondition",
        token_id="2",
        transaction_hash="0xtransaction",
        source_trade_timestamp=(AT + timedelta(seconds=1)).isoformat(),
        first_collector_receipt_utc=(AT + timedelta(seconds=2)).isoformat(),
        price="0.98",
        size="10",
        evidence_class="PROSPECTIVE_POLL",
        **changes,
    )


def book(token: str = "2") -> dict[str, Any]:
    return dict(
        token_id=token,
        complete=True,
        market="0xcondition",
        connection_id="epoch1",
        bids=[dict(price="0.97", size="10")],
        asks=[dict(price="0.99", size="10")],
        hash="fixture",
    )


def test_clock_requires_timezone() -> None:
    assert clock("2026-10-29T13:00:00+01:00") == AT
    assert clock("2026-10-29T12:00:00") is None
    assert clock("broken") is None


def test_schedule_is_declared_nominal_not_publication() -> None:
    result = schedule_context("EPWA", AT - timedelta(seconds=30))
    assert result["nearest_nominal_time"] == AT.isoformat()
    assert result["signed_offset_seconds"] == -30
    assert result["public_release_time"] is None
    assert schedule_context("EGLC", AT)["status"] == "UNKNOWN"


def test_failed_commit_restores_durable_source_cursor(
    store: BattleStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "source.sqlite3"
    conn = source_database(path)
    monitor = Monitor(store, tmp_path / "none")
    monitor.cycle(path, AT)
    add(conn, "TRADE", trade(), 2)
    original = store.commit

    def fail(*args: Any, **kwargs: Any) -> None:
        raise sqlite3.OperationalError("synthetic lock contention")

    monkeypatch.setattr(store, "commit", fail)
    with pytest.raises(sqlite3.OperationalError):
        monitor.cycle(path, AT + timedelta(seconds=3))
    monkeypatch.setattr(store, "commit", original)
    # The watch loop performs this restore, never trusting its failed memory state.
    monitor = Monitor(store, tmp_path / "none")
    monitor.cycle(path, AT + timedelta(seconds=4))
    assert monitor.state["counts"]["ENTRY_OBSERVED"] == 1
    assert monitor.cursors[str(path.resolve())] == 1
    conn.close()


def test_market_binding_and_no_city_airport_guess() -> None:
    reference = market_reference(market("EGLC"), AT.isoformat())
    assert reference and reference["station"] == "EGLC"
    assert reference["settlement_boundary"] is None
    other = market()
    other["resolutionSource"] = ""
    other["description"] = "Warsaw airport"
    reference = market_reference(other, AT.isoformat())
    assert reference and reference["station"] is None
    other["clobTokenIds"] = '["1","1"]'
    assert market_reference(other, AT.isoformat()) is None


def test_snapshot_after_execution_is_not_pre_execution_book(
    store: BattleStore, tmp_path: Path
) -> None:
    monitor = Monitor(store, tmp_path / "absent-weather")
    monitor.ingest(row("MARKET", market(), -3), AT)
    monitor.ingest(row("BOOK", book(), 1.5), AT + timedelta(seconds=3))
    event = monitor.ingest(row("TRADE", trade(), 2), AT + timedelta(seconds=3))[0]
    assert event["kind"] == "ENTRY_OBSERVED"
    assert event["payload"]["source_time_book"] is None
    assert event["payload"]["detection_time_book"]["age_seconds"] == 0.5
    assert event["payload"]["sidecar_capture_time"] != event["payload"]["original_first_detection"]
    assert event["payload"]["order_submission_time"] is None


@pytest.mark.parametrize(
    "evidence", ["HISTORICAL_BACKFILL", "BOOTSTRAP_HISTORICAL", "GAP_CENSORED"]
)
def test_non_prospective_rows_are_censored(store: BattleStore, evidence: str) -> None:
    payload = trade()
    payload["evidence_class"] = evidence
    assert (
        Monitor(store).ingest(row("TRADE", payload, 2), AT + timedelta(seconds=3))[0]["kind"]
        == "CENSORED_BUY"
    )


def test_exact_trade_dedup(store: BattleStore) -> None:
    monitor = Monitor(store)
    source = row("TRADE", trade(), 2)
    assert len(monitor.ingest(source, AT + timedelta(seconds=3))) == 1
    assert monitor.ingest(source, AT + timedelta(seconds=4)) == []


def test_wrong_wallet_and_wrong_token_mapping(store: BattleStore) -> None:
    monitor = Monitor(store)
    payload = trade()
    payload["trader_wallet"] = "0xother"
    assert monitor.ingest(row("TRADE", payload, 2), AT + timedelta(seconds=3)) == []
    monitor.ingest(row("MARKET", market(), -1), AT)
    payload = trade()
    payload["token_id"] = "3"
    event = monitor.ingest(row("TRADE", payload, 2), AT + timedelta(seconds=3))[0]
    assert event["payload"]["metadata"] is None
    assert event["payload"]["weather"]["station"] is None


def test_future_source_receipt_rejected(store: BattleStore) -> None:
    assert Monitor(store).ingest(row("BOOK", book(), 5), AT)[0]["kind"] == "SOURCE_TIME_REJECTED"


def test_stale_books_and_gap_invalidation(store: BattleStore) -> None:
    monitor = Monitor(store)
    monitor.ingest(row("BOOK", book()), AT)
    assert monitor.book("2", AT + timedelta(seconds=11))["status"] == "STALE_BOOK"  # type: ignore[index]
    monitor.ingest(row("COVERAGE_GAP", {}), AT)
    assert monitor.book("2", AT) is None


def test_subscription_change_preserves_retained_token_history(store: BattleStore) -> None:
    monitor = Monitor(store)
    monitor.ingest(
        row("STREAMHEALTH", dict(state="SUBSCRIBED", connection_id="epoch1", tokens=["1", "2"])), AT
    )
    monitor.ingest(row("BOOK", book("1")), AT)
    monitor.ingest(row("BOOK", book("2")), AT)
    monitor.ingest(
        row(
            "STREAMHEALTH",
            dict(state="SUBSCRIPTIONS_CHANGED", connection_id="epoch1", tokens=["2", "3"]),
        ),
        AT,
    )
    assert monitor.book("1", AT) is None
    assert monitor.book("2", AT) is not None
    monitor.ingest(
        row(
            "STREAMHEALTH",
            dict(state="SUBSCRIPTIONS_CHANGED", connection_id="epoch2", tokens=["2", "3"]),
        ),
        AT,
    )
    assert monitor.book("2", AT) is None


def test_role_evidence_append_does_not_rewrite_original_entry(store: BattleStore) -> None:
    monitor = Monitor(store)
    entry = monitor.ingest(row("TRADE", trade(), 2), AT + timedelta(seconds=3))[0]
    role = dict(
        trade_id="trade1",
        role="API_ATTRIBUTED_TAKER",
        transaction_hash="0xtransaction",
        evidence="Synthetic fixture",
    )
    joined = monitor.ingest(row("ROLE_EVIDENCE", role, 10), AT + timedelta(seconds=12))[0]
    assert joined["kind"] == "ROLE_EVIDENCE_JOIN"
    assert joined["payload"]["trade_id"] == "trade1"
    assert joined["payload"]["source_recorded_at"] == (AT + timedelta(seconds=10)).isoformat()
    assert joined["at"] == (AT + timedelta(seconds=12)).isoformat()
    assert joined["payload"]["original_evidence"]["role"] == "API_ATTRIBUTED_TAKER"
    assert joined["payload"]["no_history_rewrite"] is True
    assert entry["payload"]["order_role"] == "UNKNOWN"
    assert entry["payload"]["role_evidence_available_at_detection"] is None


def test_endpoint_receipts_join_exact_id_and_keep_original_detection(store: BattleStore) -> None:
    monitor = Monitor(store)
    receipt = dict(
        trade_id="trade1",
        endpoint="TRADES_V2",
        first_endpoint_receipt=(AT + timedelta(seconds=2)).isoformat(),
    )
    pending = monitor.ingest(row("ENDPOINT_RECEIPT", receipt, 2), AT + timedelta(seconds=3))[0]
    assert pending["payload"]["entry_record_status"] == "PENDING_OR_UNMONITORED_TRADE"
    entry = monitor.ingest(row("TRADE", trade(), 2), AT + timedelta(seconds=3))[0]
    original = entry["payload"]["original_first_detection"]
    monitor.ingest(
        row("ENDPOINT_RECEIPT", dict(trade_id="other", endpoint="ACTIVITY_V2"), 4),
        AT + timedelta(seconds=5),
    )
    later = {
        **receipt,
        "endpoint": "ACTIVITY_V2",
        "first_endpoint_receipt": (AT + timedelta(seconds=4)).isoformat(),
    }
    joined = monitor.ingest(row("ENDPOINT_RECEIPT", later, 4), AT + timedelta(seconds=5))[0]
    assert joined["payload"]["trade_id"] == "trade1"
    assert len(monitor.state["endpoint_receipts"]["trade1"]) == 2
    assert len(entry["payload"]["endpoint_receipts_known_at_capture"]) == 1
    assert entry["payload"]["original_first_detection"] == original


def test_role_before_trade_is_only_as_of_its_original_receipt(store: BattleStore) -> None:
    monitor = Monitor(store)
    role = dict(trade_id="trade1", role="API_ATTRIBUTED_TAKER")
    monitor.ingest(row("ROLE_EVIDENCE", role, 1), AT + timedelta(seconds=3))
    result = monitor.ingest(row("TRADE", trade(), 2), AT + timedelta(seconds=3))[0]
    assert (
        result["payload"]["role_evidence_available_at_detection"]["original_evidence"]["role"]
        == "API_ATTRIBUTED_TAKER"
    )


def test_followups_never_backdate_late_capture(store: BattleStore) -> None:
    monitor = Monitor(store)
    monitor.ingest(row("TRADE", trade(), 2), AT + timedelta(seconds=3))
    follow = monitor.followups(AT + timedelta(seconds=15))
    assert {e["payload"]["requested_horizon_seconds"] for e in follow} == {1, 5}
    assert all(e["at"] == (AT + timedelta(seconds=15)).isoformat() for e in follow)
    assert all(e["payload"]["status"].startswith("LATE_") for e in follow)


def test_bounded_rings(store: BattleStore) -> None:
    monitor = Monitor(store)
    for token in range(101):
        for offset in range(22):
            monitor.ingest(row("BOOK", book(str(token)), offset), AT + timedelta(seconds=30))
    assert len(monitor.state["books"]) == 100
    assert all(len(ring) == 20 for ring in monitor.state["books"].values())


def test_full_snapshots_sort_best_depth_independent_of_provider_order(store: BattleStore) -> None:
    monitor = Monitor(store)
    payload = book()
    payload["bids"] = [
        dict(price=str(p), size="10") for p in ("0.1", "0.5", "0.7", "0.9", "0.96", "0.97")
    ]
    payload["asks"] = [dict(price=str(p), size="10") for p in ("0.999", "0.99", "0.98")]
    monitor.ingest(row("BOOK", payload), AT)
    view = monitor.book("2", AT)
    assert view and view["bids"][0]["price"] == "0.97"
    assert view["asks"][0]["price"] == "0.98"
    assert len(view["bids"]) == 5
    payload["bids"] = [dict(price="NaN", size="10")]
    assert monitor.ingest(row("BOOK", payload), AT)[0]["kind"] == "SOURCE_BOOK_REJECTED"


def test_live_display_skips_nondefault_directories(tmp_path: Path) -> None:
    assert publish_live(tmp_path, {}, {}) is False
    assert list(tmp_path.iterdir()) == []


def test_live_display_is_bounded_atomic_and_censored_rows_excluded(tmp_path: Path) -> None:
    target = tmp_path / "live.json"
    state = dict(
        heartbeat=AT.isoformat(),
        pid=123,
        counts=dict(ENTRY_OBSERVED=11, CENSORED_BUY=3),
        latest_entries=[
            dict(
                trade_id=str(i),
                source_trade_timestamp=AT.isoformat(),
                evidence_class="PROSPECTIVE_POLL",
                full_book="MUST_NOT_COPY",
            )
            for i in range(11)
        ],
    )
    assert publish_live(tmp_path, state, {"source": 50}, target=target, at=AT)
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["status"] == "RUNNING"
    assert payload["published_at"] == AT.isoformat()
    assert len(payload["latest_entries"]) == 10
    assert payload["latest_entries"][0]["trade_id"] == "1"
    assert "full_book" not in target.read_text(encoding="utf-8")
    state["latest_entries"] = [dict(trade_id="censored", evidence_class="GAP_CENSORED")]
    assert publish_live(
        tmp_path,
        state,
        {"source": 51},
        target=target,
        at=AT + timedelta(seconds=1),
        status_value="STOPPED",
    )
    stopped = json.loads(target.read_text(encoding="utf-8"))
    assert stopped["status"] == "STOPPED" and stopped["latest_entries"] == []
    assert stopped["source_cursor"] == {"source": 51}
    assert list(tmp_path.glob("*.tmp")) == []


def test_failed_commit_never_publishes_display(
    store: BattleStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from premetar.research import entry_timing_monitor as module

    path = tmp_path / "source.sqlite3"
    source_database(path).close()
    published = []
    monkeypatch.setattr(module, "publish_live", lambda *a, **kw: published.append(True))

    def fail(*args: Any, **kwargs: Any) -> None:
        raise sqlite3.OperationalError("synthetic commit failure")

    monkeypatch.setattr(store, "commit", fail)
    with pytest.raises(sqlite3.OperationalError):
        Monitor(store).cycle(path, AT)
    assert published == []


def source_database(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE events(id INTEGER PRIMARY KEY,kind TEXT,received_at TEXT,payload TEXT)"
    )
    return conn


def add(conn: sqlite3.Connection, kind: str, payload: dict[str, Any], seconds: int) -> None:
    conn.execute(
        "INSERT INTO events(kind,received_at,payload) VALUES (?,?,?)",
        (kind, (AT + timedelta(seconds=seconds)).isoformat(), json.dumps(payload)),
    )
    conn.commit()


def test_coldstart_resume_cursor_integrity_and_no_replayed_trade(
    store: BattleStore, tmp_path: Path
) -> None:
    path = tmp_path / "source.sqlite3"
    conn = source_database(path)
    add(conn, "TRADE", trade("old"), 2)
    monitor = Monitor(store, tmp_path / "none")
    monitor.cycle(path, AT + timedelta(seconds=3))
    assert monitor.state["counts"]["CENSORED_STARTUP"] == 1
    assert "ENTRY_OBSERVED" not in monitor.state["counts"]
    add(conn, "TRADE", trade("new"), 4)
    monitor.cycle(path, AT + timedelta(seconds=5))
    resumed = Monitor(store)
    resumed.cycle(path, AT + timedelta(seconds=6))
    assert resumed.state["counts"]["ENTRY_OBSERVED"] == 1
    assert store.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 2
    controls = [e for e in store.read_events(limit=100) if e["kind"] == "CONTROL_CANDIDATE"]
    assert len(controls) == 1
    conn.close()


def test_bounded_read_advances_over_unretained_raw_rows(tmp_path: Path) -> None:
    path = tmp_path / "source.sqlite3"
    conn = source_database(path)
    conn.executemany(
        "INSERT INTO events(kind,received_at,payload) VALUES ('RAW',?,?)",
        [(AT.isoformat(), "not decoded") for _ in range(1005)],
    )
    conn.commit()
    cursor, rows = source_rows(path, 0)
    assert cursor == 1000 and rows == []
    assert source_rows(path, cursor)[0] == 1005
    conn.close()


def test_missing_weather_is_explicit_unknown(tmp_path: Path) -> None:
    assert weather_before(tmp_path / "absent", "EPWA", AT)["status"] == "UNKNOWN"
    assert weather_before(tmp_path / "absent", None, AT)["station"] is None


def test_weather_availability_and_first_duplicate_receipt(tmp_path: Path) -> None:
    path = tmp_path / "weather.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE observations(id INTEGER PRIMARY KEY,station_icao TEXT,event_time TEXT,collector_receive_time TEXT,temperature_c REAL,raw_text TEXT,source TEXT,startup_censored INTEGER,coverage_gap INTEGER,evidence_class TEXT,product_type TEXT)"
    )
    values = [
        ("2026-10-29T11:30:00+00:00", "2026-10-29T11:32:00+00:00", "METAR EPWA fixture", 0, 0),
        ("2026-10-29T11:30:00+00:00", "2026-10-29T11:35:00+00:00", "METAR EPWA fixture", 0, 0),
        (
            "2026-10-29T11:59:00+00:00",
            "2026-10-29T12:01:00+00:00",
            "METAR EPWA future receipt",
            0,
            0,
        ),
        ("2026-10-29T11:58:00+00:00", "2026-10-29T11:59:00+00:00", "METAR EPWA censored", 1, 0),
        ("2026-10-29T11:57:00+00:00", "2026-10-29T11:59:00+00:00", "METAR EPWA gap", 0, 1),
    ]
    for event, receipt, raw, startup, gap in values:
        conn.execute(
            "INSERT INTO observations(station_icao,event_time,collector_receive_time,temperature_c,raw_text,source,startup_censored,coverage_gap,evidence_class,product_type) VALUES ('EPWA',?,?,10,?,'awc',?,?,'REALTIME_CAPTURED','METAR')",
            (event, receipt, raw, startup, gap),
        )
    conn.commit()
    conn.close()
    result = weather_before(path, "EPWA", AT)
    assert result["metar"]["collector_receive_time"] == "2026-10-29T11:32:00+00:00"
    assert result["metar"]["raw_text"] == "METAR EPWA fixture"
