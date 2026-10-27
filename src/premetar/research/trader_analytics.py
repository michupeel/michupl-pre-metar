"""Read-only, bounded evidence analytics; alternative shadow scenarios stay separate."""

import csv
import json
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from premetar.research.trader_portfolio import (
    ExitRecord,
    ShadowLot,
    portfolio_metrics,
    remaining_quantity,
)
from premetar.research.trader_store import readonly_connection

OFFSETS = (-60, -30, -10, -5, 0, 1, 5, 15, 30, 60, 300)


def _optional(value: Any) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def portfolio_from_events(events: list[dict[str, Any]]) -> tuple[list[ShadowLot], list[ExitRecord]]:
    """Use durable execution quantities, never requested notional as a fill."""
    lots: list[ShadowLot] = []
    exits: list[ExitRecord] = []
    for event in events:
        row = event["payload"]
        if event["kind"] == "SHADOW" and Decimal(str(row.get("quantity", 0))) > 0:
            lots.append(
                ShadowLot(
                    str(row["lot_id"]),
                    str(row["token_id"]),
                    str(row["strategy"]),
                    int(row["delay_seconds"]),
                    Decimal(str(row["notional"])),
                    Decimal(str(row["quantity"])),
                    Decimal(str(row["target_buy_quantity"])),
                    Decimal(str(row["gross_value"])),
                    _optional(row.get("fee")),
                    _optional(row.get("net_value")),
                    Decimal(str(row["vwap"])),
                )
            )
        elif event["kind"] == "EXIT":
            exits.append(
                ExitRecord(
                    str(row["lot_id"]),
                    Decimal(str(row["quantity"])),
                    Decimal(str(row["gross_value"])),
                    _optional(row.get("fee")),
                    _optional(row.get("net_value")),
                    str(row["kind"]),
                )
            )
    return lots, exits


def _time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Timezone required")
    return result.astimezone(UTC)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row}) or ["status"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def book_windows(
    trades: list[dict[str, Any]],
    books: list[dict[str, Any]],
    *,
    asof: datetime,
) -> list[dict[str, Any]]:
    """Latest full snapshot received by the requested clock, at most five seconds old.

    The source-time anchor is descriptive only: upstream second precision and
    possible clock offset prevent asserting it is a true pre-execution book.
    """
    indexed: dict[str, list[tuple[datetime, dict[str, Any]]]] = defaultdict(list)
    for event in books:
        row = event["payload"]
        received = _time(event["received_at"])
        if row.get("complete") is True and received <= asof:
            indexed[str(row["token_id"])].append((received, row))
    for rows in indexed.values():
        rows.sort(key=lambda value: value[0])
    rows_out = []
    for trade in trades:
        token = str(trade["token_id"])
        available = indexed.get(token, [])
        clocks = [value[0] for value in available]
        for anchor_name, field in (
            ("SOURCE_EXECUTION_SECOND_PRECISION", "source_trade_timestamp"),
            ("FIRST_DETECTION", "first_collector_receipt_utc"),
        ):
            if not trade.get(field):
                continue
            anchor = _time(str(trade[field]))
            for offset in OFFSETS:
                point = anchor + timedelta(seconds=offset)
                result: dict[str, Any] = {
                    "trade_id": trade["trade_id"],
                    "token_id": token,
                    "anchor": anchor_name,
                    "anchor_utc": anchor.isoformat(),
                    "offset_seconds": offset,
                    "requested_utc": point.isoformat(),
                    "status": "UNVERIFIABLE",
                    "book_received_utc": None,
                    "book_age_seconds": None,
                    "best_bid": None,
                    "best_ask": None,
                    "bid_size": None,
                    "ask_size": None,
                    "spread": None,
                }
                index = bisect_right(clocks, point) - 1
                if point > asof:
                    result["status"] = "WINDOW_NOT_YET_OBSERVED"
                elif index >= 0:
                    received, book = available[index]
                    age = (point - received).total_seconds()
                    result["book_received_utc"] = received.isoformat()
                    result["book_age_seconds"] = age
                    if age <= 5:
                        bids = sorted(
                            book.get("bids", []),
                            key=lambda v: Decimal(str(v["price"])),
                            reverse=True,
                        )
                        asks = sorted(book.get("asks", []), key=lambda v: Decimal(str(v["price"])))
                        result["status"] = "RECORDED_FULL_SNAPSHOT_NOT_FILL_PROOF"
                        for side, levels in (("bid", bids), ("ask", asks)):
                            if levels:
                                result[f"best_{side}"] = levels[0]["price"]
                                result[f"{side}_size"] = levels[0]["size"]
                        if bids and asks:
                            result["spread"] = Decimal(str(asks[0]["price"])) - Decimal(
                                str(bids[0]["price"])
                            )
                rows_out.append(result)
    return rows_out


def analyze_evidence(database: Path, output: Path) -> dict[str, Any]:
    """Copy bounded event sets in one short read transaction, then release live DB."""
    connection = readonly_connection(database)
    try:
        connection.execute("BEGIN")
        counts = dict(connection.execute("SELECT kind,COUNT(*) FROM events GROUP BY kind"))
        captured = connection.execute(
            "SELECT id,kind,received_at,payload FROM events WHERE kind IN "
            "('SHADOW','EXIT','TRADE','ROLE_EVIDENCE','COPY_REQUEST','COPY_MISSED') "
            "ORDER BY id DESC LIMIT 200000"
        ).fetchall()
        book_rows = connection.execute(
            "SELECT id,kind,received_at,payload FROM events WHERE kind='BOOK' "
            "ORDER BY id DESC LIMIT 100000"
        ).fetchall()
        asof = datetime.now(UTC)
    finally:
        connection.close()
    events = [
        {"id": row[0], "kind": row[1], "received_at": row[2], "payload": json.loads(row[3])}
        for row in reversed(captured)
    ]
    books = [
        {"id": row[0], "kind": row[1], "received_at": row[2], "payload": json.loads(row[3])}
        for row in reversed(book_rows)
    ]
    lots, exits = portfolio_from_events(events)
    cohorts: dict[tuple[str, int, Decimal], list[ShadowLot]] = defaultdict(list)
    for lot in lots:
        cohorts[(lot.strategy, lot.delay_seconds, lot.notional)].append(lot)
    shadow_rows = [event["payload"] for event in events if event["kind"] == "SHADOW"]
    # Durable BUY requests include attempts that failed before any SHADOW row.
    # SELL requests are exits and must not enter the BUY execution denominator.
    requests: set[tuple[str, int]] = set()
    for event in events:
        if event["kind"] == "COPY_REQUEST":
            request = event["payload"]
            trade = request.get("trade", {})
            if trade.get("side") == "BUY" and trade.get("trade_id"):
                requests.add((str(trade["trade_id"]), int(request["delay_seconds"])))
    cohort_counts: Counter[tuple[str, int, Decimal]] = Counter()
    for _trade_id, delay in requests:
        for strategy in ("COPY_HOLD", "COPY_FOLLOW", "COPY_TAKE_PROFIT"):
            for notional in (10, 25, 50, 100):
                cohort_counts[(strategy, delay, Decimal(notional))] += 1
    for row in shadow_rows:
        pair = (str(row.get("trade_id", "")), int(row["delay_seconds"]))
        if pair not in requests:
            # Legacy fixtures/captures without durable requests remain auditable.
            cohort_counts[(str(row["strategy"]), pair[1], Decimal(str(row["notional"])))] += 1
    metrics_rows = []
    for key in sorted(set(cohorts) | set(cohort_counts)):
        cohort_lots = cohorts[key]
        identities = {lot.lot_id for lot in cohort_lots}
        metrics = portfolio_metrics(
            cohort_lots, [event for event in exits if event.lot_id in identities]
        )
        attempts = cohort_counts[key]
        metrics_rows.append(
            {
                "strategy": key[0],
                "delay_seconds": key[1],
                "notional": key[2],
                "attempts": attempts,
                "execution_coverage": Decimal(len(cohort_lots)) / Decimal(attempts)
                if attempts
                else None,
                **metrics,
            }
        )
    latest_books: dict[str, dict[str, Any]] = {}
    for event in books:
        if event["payload"].get("complete") is True and _time(event["received_at"]) <= asof:
            latest_books[str(event["payload"]["token_id"])] = event
    marks = []
    for lot in lots:
        remaining = remaining_quantity(lot, exits)
        if remaining == 0:
            continue
        mark_event = latest_books.get(lot.token_id)
        bids = mark_event["payload"].get("bids", []) if mark_event else []
        bid = max((Decimal(str(level["price"])) for level in bids), default=None)
        age = (asof - _time(mark_event["received_at"])).total_seconds() if mark_event else None
        marks.append(
            {
                "lot_id": lot.lot_id,
                "token_id": lot.token_id,
                "strategy": lot.strategy,
                "delay_seconds": lot.delay_seconds,
                "notional": lot.notional,
                "remaining_quantity": remaining,
                "observed_best_bid": bid,
                "gross_indicative_mark": remaining * bid if bid is not None else None,
                "book_received_utc": mark_event["received_at"] if mark_event else None,
                "book_age_seconds": age,
                "status": "UNKNOWN"
                if bid is None
                else "STALE_INDICATIVE_MARK"
                if age is not None and age > 5
                else "INDICATIVE_NOT_EXECUTABLE_LIQUIDATION",
            }
        )
    trades = sorted(
        [event["payload"] for event in events if event["kind"] == "TRADE"],
        key=lambda trade: (
            trade.get("evidence_class") == "PROSPECTIVE_POLL",
            str(trade.get("source_trade_timestamp", "")),
            str(trade.get("trade_id", "")),
        ),
        reverse=True,
    )[:100]
    windows = book_windows(trades, books, asof=asof)
    roles = {
        event["payload"]["trade_id"]: event["payload"].get("role", "UNKNOWN")
        for event in events
        if event["kind"] == "ROLE_EVIDENCE"
    }
    role_counts = Counter(str(roles.get(trade["trade_id"], "UNKNOWN")) for trade in trades)
    output.mkdir(parents=True, exist_ok=True)
    _write_csv(output / "hightemptation_shadow_metrics.csv", metrics_rows)
    _write_csv(output / "hightemptation_unresolved_marks.csv", marks)
    _write_csv(output / "hightemptation_book_windows.csv", windows)
    text = "# Shadow economics — independent scenarios\n\n"
    text += f"Analysis cutoff UTC: {asof.isoformat()}. No scenarios are summed together.\n\n"
    text += "Net metrics include fully closed, fee-known simulated lots only. Open lots are not wins. Marks are indicative gross quotes, not realized PnL or executable liquidation. Displayed-depth assumptions do not prove queue priority or fills.\n\n"
    text += "| Strategy | Delay s | USD budget | Attempts | Filled lots | Closed | Unresolved | Fee-known closed | Net PnL | ROI |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n"
    for row in metrics_rows:
        text += (
            "| "
            + " | ".join(
                str(row.get(key))
                for key in (
                    "strategy",
                    "delay_seconds",
                    "notional",
                    "attempts",
                    "lot_count",
                    "closed_lots",
                    "unresolved_lots",
                    "verified_closed_lots",
                    "net_pnl",
                    "net_roi",
                )
            )
            + " |\n"
        )
    if not metrics_rows:
        text += "\nINSUFFICIENT DATA — no prospective shadow BUY attempts.\n"
    text += "\nFull CSV adds execution coverage, win rate, profit factor, average profit/loss and closed-equity drawdown. Execution coverage counts all durable BUY requests, including COPY_MISSED and pending requests, expanded over the frozen four budgets and three strategies; SELL requests are excluded. Legacy SHADOW records without requests are included once. Original wallet profitability is not inferred from copied lots.\n"
    text += f"\nBounded exports: latest 200000 trade/lifecycle/role/request events, latest 100000 full-book events; forensic windows prioritize prospective detections, then latest source execution timestamps, capped at100 trades. Full DB counts: `{json.dumps(counts, sort_keys=True)}`. Missing historical depth remains UNVERIFIABLE.\n"
    (output / "hightemptation_shadow_pnl.md").write_text(text, encoding="utf-8")
    forensic = output / "hightemptation_signal_forensics.md"
    note = f"\n## Recorded book windows and role evidence\n\nAt {asof.isoformat()}, {len(trades)} recent captured trades, {len(windows)} requested windows; role counts `{json.dumps(dict(role_counts), sort_keys=True)}`. Exact trade-ID positive taker-only matches are API attribution, not on-chain verification. Absence does not prove maker. Source-second anchors are descriptive; clock uncertainty prevents claiming millisecond ordering. Detection-time context is not information known at source execution. Order creation remains unknown. See hightemptation_book_windows.csv; unavailable prior books are never replaced with later books.\n"
    forensic.write_text(
        (forensic.read_text(encoding="utf-8") if forensic.is_file() else "# Signal forensics\n")
        + note,
        encoding="utf-8",
    )
    return {
        "cohorts": len(metrics_rows),
        "lots": len(lots),
        "exits": len(exits),
        "unresolved_lots": len(marks),
        "forensic_trades": len(trades),
        "book_windows": len(windows),
        "role_counts": dict(role_counts),
        "asof": asof.isoformat(),
    }
