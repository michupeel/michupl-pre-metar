import csv
from datetime import UTC, datetime, timedelta
from pathlib import Path

from premetar.research.trader_analytics import analyze_evidence, book_windows, portfolio_from_events
from premetar.research.trader_store import TraderStore

NOW = datetime(2026, 10, 27, tzinfo=UTC)


def shadow(lot: str, delay: int = 0) -> dict[str, object]:
    return {
        "lot_id": lot,
        "token_id": "token",
        "strategy": "COPY_HOLD",
        "delay_seconds": delay,
        "notional": 10,
        "quantity": "20",
        "target_buy_quantity": "100",
        "gross_value": "10",
        "fee": "0",
        "net_value": "10",
        "vwap": "0.5",
    }


def test_portfolio_parses_only_actual_fills() -> None:
    events = [
        {"kind": "SHADOW", "payload": shadow("filled")},
        {"kind": "SHADOW", "payload": {**shadow("none"), "quantity": "0"}},
        {
            "kind": "EXIT",
            "payload": {
                "lot_id": "filled",
                "quantity": "20",
                "gross_value": "20",
                "fee": "0",
                "net_value": "20",
                "kind": "SETTLEMENT",
            },
        },
    ]
    lots, exits = portfolio_from_events(events)
    assert [lot.lot_id for lot in lots] == ["filled"]
    assert len(exits) == 1


def test_no_post_anchor_book_and_stale_book() -> None:
    trade = {
        "trade_id": "t",
        "token_id": "token",
        "source_trade_timestamp": NOW.isoformat(),
        "first_collector_receipt_utc": (NOW + timedelta(seconds=10)).isoformat(),
    }
    books = [
        {
            "received_at": (NOW + timedelta(seconds=2)).isoformat(),
            "payload": {
                "token_id": "token",
                "complete": True,
                "bids": [{"price": "0.4", "size": "5"}],
                "asks": [{"price": "0.5", "size": "6"}],
            },
        }
    ]
    rows = book_windows([trade], books, asof=NOW + timedelta(minutes=1))
    source_zero = next(
        row
        for row in rows
        if row["anchor"] == "SOURCE_EXECUTION_SECOND_PRECISION" and row["offset_seconds"] == 0
    )
    assert source_zero["status"] == "UNVERIFIABLE"
    source_five = next(
        row
        for row in rows
        if row["anchor"] == "SOURCE_EXECUTION_SECOND_PRECISION" and row["offset_seconds"] == 5
    )
    assert source_five["best_bid"] == "0.4" and source_five["book_age_seconds"] == 3
    detection_zero = next(
        row for row in rows if row["anchor"] == "FIRST_DETECTION" and row["offset_seconds"] == 0
    )
    assert detection_zero["status"] == "UNVERIFIABLE" and detection_zero["best_bid"] is None
    assert rows[-1]["status"] == "WINDOW_NOT_YET_OBSERVED"


def test_incomplete_books_and_wrong_tokens_not_used() -> None:
    trade = {
        "trade_id": "t",
        "token_id": "a",
        "source_trade_timestamp": NOW.isoformat(),
        "first_collector_receipt_utc": NOW.isoformat(),
    }
    books = [
        {"received_at": NOW.isoformat(), "payload": {"token_id": "a", "complete": False}},
        {"received_at": NOW.isoformat(), "payload": {"token_id": "b", "complete": True}},
    ]
    rows = book_windows([trade], books, asof=NOW)
    assert all(row["best_bid"] is None for row in rows)


def test_analytics_separates_scenarios_and_missing_marks(tmp_path: Path) -> None:
    path = tmp_path / "trader.db"
    store = TraderStore(path)
    store.append("SHADOW", shadow("a", 0), NOW, "a")
    store.append("SHADOW", shadow("b", 3), NOW, "b")
    store.append(
        "EXIT",
        {
            "lot_id": "a",
            "quantity": "20",
            "gross_value": "20",
            "fee": "0",
            "net_value": "20",
            "kind": "SETTLEMENT",
        },
        NOW,
        "exit",
    )
    store.close()
    result = analyze_evidence(path, tmp_path / "out")
    assert result["cohorts"] == 2 and result["unresolved_lots"] == 1
    with (tmp_path / "out" / "hightemptation_shadow_metrics.csv").open() as stream:
        metrics = list(csv.DictReader(stream))
    assert metrics[0]["net_pnl"] == "10"
    assert metrics[1]["net_pnl"] == ""
    with (tmp_path / "out" / "hightemptation_unresolved_marks.csv").open() as stream:
        marks = list(csv.DictReader(stream))
    assert marks[0]["status"] == "UNKNOWN"
    assert marks[0]["gross_indicative_mark"] == ""
    with TraderStore(path).connection as connection:
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 3


def test_empty_analytics_has_no_invented_profit(tmp_path: Path) -> None:
    path = tmp_path / "empty.db"
    TraderStore(path).close()
    result = analyze_evidence(path, tmp_path / "out")
    assert result["lots"] == 0
    text = (tmp_path / "out" / "hightemptation_shadow_pnl.md").read_text(encoding="utf-8")
    assert "INSUFFICIENT DATA" in text


def test_execution_coverage_includes_missed_requests_without_shadow(tmp_path: Path) -> None:
    path = tmp_path / "coverage.db"
    store = TraderStore(path)
    for identity in ("filled", "missed"):
        store.append(
            "COPY_REQUEST",
            {"trade": {"trade_id": identity, "side": "BUY"}, "delay_seconds": 0},
            NOW,
            identity,
        )
    store.append(
        "COPY_REQUEST",
        {"trade": {"trade_id": "sell", "side": "SELL"}, "delay_seconds": 0},
        NOW,
        "sell",
    )
    store.append("SHADOW", {**shadow("filled"), "trade_id": "filled"}, NOW, "filled")
    store.append("COPY_MISSED", {"request_key": "missed:0", "reason": "TIMEOUT"}, NOW, "missed:0")
    store.close()
    analyze_evidence(path, tmp_path / "out")
    with (tmp_path / "out" / "hightemptation_shadow_metrics.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 12
    hold = next(row for row in rows if row["strategy"] == "COPY_HOLD" and row["notional"] == "10")
    assert hold["attempts"] == "2"
    assert hold["lot_count"] == "1"
    assert hold["execution_coverage"] == "0.5"


def test_forensics_prioritize_prospective_then_latest_source_not_ingest_order(
    tmp_path: Path,
) -> None:
    path = tmp_path / "priorities.db"
    store = TraderStore(path)
    for index in range(102):
        # Old backfill arrives after prospective data, in reverse source-time order.
        identity = "prospective" if index == 0 else f"history-{index}"
        timestamp = NOW - timedelta(days=index)
        store.append(
            "TRADE",
            {
                "trade_id": identity,
                "token_id": "token",
                "source_trade_timestamp": timestamp.isoformat(),
                "first_collector_receipt_utc": NOW.isoformat(),
                "evidence_class": "PROSPECTIVE_POLL" if index == 0 else "BOOTSTRAP_HISTORICAL",
            },
            NOW,
            identity,
        )
    store.append(
        "ROLE_EVIDENCE",
        {"trade_id": "prospective", "role": "API_ATTRIBUTED_TAKER"},
        NOW,
        "prospective",
    )
    store.close()
    result = analyze_evidence(path, tmp_path / "out")
    assert result["forensic_trades"] == 100
    assert result["role_counts"]["API_ATTRIBUTED_TAKER"] == 1
    with (tmp_path / "out" / "hightemptation_book_windows.csv").open() as stream:
        identities = {row["trade_id"] for row in csv.DictReader(stream)}
    assert "prospective" in identities and "history-1" in identities
    assert "history-101" not in identities and "history-100" not in identities
