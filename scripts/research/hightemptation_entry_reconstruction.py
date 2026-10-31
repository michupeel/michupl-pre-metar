"""Reproducible EXP0018 replay of a bounded, immutable source ID interval.

Each read closes promptly. Append-only source maximum ID is frozen before replay;
no long transaction, source backup, API request or source mutation is needed.
All output is RETROSPECTIVE_REPLAY_OF_PROSPECTIVE_CAPTURES, never a live signal.
"""

import argparse
import csv
import hashlib
import json
import os
import sys
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from premetar.research.battle_store import BattleStore
from premetar.research.entry_reconstruction import (
    VERSION,
    Reconstruction,
    source_rows,
)
from premetar.research.entry_reconstruction_clocks import known_clock
from premetar.research.entry_timing_monitor import ROOT, TRADER, WEATHER, clock
from premetar.research.trader_store import readonly_connection

# Existing independent research FIFO utility; no production portfolio import.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from hightemptation_inventory import reconstruct  # noqa: E402

REPORTS = ROOT / "reports/trader"


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, sort_keys=True, allow_nan=False, default=str)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def raw_book_coverage(
    source: Path, entries: list[dict[str, Any]], lower: int, maximum: int
) -> list[dict[str, Any]]:
    """Independent source check bypassing ring/derived-midpoint eligibility."""
    result = [
        dict(
            trade_id=e["trade_id"],
            execution=e["source_trade_timestamp"],
            token_id=e["books"]["no"]["token_id"],
            book_before_count=0,
            latest_book_before=None,
            first_book_after=None,
        )
        for e in entries
    ]
    by_token: dict[str, list[dict[str, Any]]] = {}
    for item in result:
        by_token.setdefault(item["token_id"], []).append(item)
    cursor = lower
    while cursor < maximum:
        c = readonly_connection(source)
        try:
            batch = c.execute(
                "SELECT id,received_at,payload FROM events WHERE kind='BOOK' AND id>? AND id<=? ORDER BY id LIMIT 500",
                (cursor, maximum),
            ).fetchall()
        finally:
            c.close()
        if not batch:
            break
        cursor = batch[-1][0]
        for _identity, receipt, text in batch:
            p = json.loads(text)
            for item in by_token.get(str(p.get("token_id")), []):
                if receipt < item["execution"]:
                    item["book_before_count"] += 1
                    item["latest_book_before"] = receipt
                elif item["first_book_after"] is None:
                    item["first_book_after"] = receipt
    for item in result:
        execution = known_clock(item["execution"])
        pre, post = clock(item["latest_book_before"]), clock(item["first_book_after"])
        item["latest_pre_snapshot_age_seconds"] = (execution - pre).total_seconds() if pre else None
        item["first_post_snapshot_delay_seconds"] = (
            (post - execution).total_seconds() if post else None
        )
    return result


def analyze(
    max_rows: int = 1_500_000,
    source: Path = TRADER,
    weather: Path = WEATHER,
    output: Path = REPORTS,
    publish: bool = False,
    experimental_deltas: bool = False,
    maximum_id: int | None = None,
) -> dict[str, Any]:
    if not 1000 <= max_rows <= 2_000_000:
        raise ValueError("Bounded replay requires 1000..2000000 source IDs")
    started = time.monotonic()
    connection = readonly_connection(source)
    try:
        maximum = int(connection.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0])
        if maximum_id is not None:
            if not 1 <= maximum_id <= maximum:
                raise ValueError("Invalid immutable source cutoff")
            maximum = maximum_id
        lower = max(0, maximum - max_rows)
        first = connection.execute(
            "SELECT received_at FROM events WHERE id>? ORDER BY id LIMIT 1", (lower,)
        ).fetchone()
        last = connection.execute(
            "SELECT received_at FROM events WHERE id=?", (maximum,)
        ).fetchone()
        indexes = [r[1] for r in connection.execute("PRAGMA index_list(events)")]
        # The same immutable ID cutoff also bounds inventory evidence.
        trades = [
            json.loads(r[0])
            for r in connection.execute(
                "SELECT payload FROM events WHERE kind='TRADE' AND id>? AND id<=? ORDER BY id",
                (lower, maximum),
            )
        ]
        # Conservatively quarantine every token seen in non-trade activity.
        nontrade: set[str] = set()
        for (encoded,) in connection.execute(
            "SELECT payload FROM events WHERE kind='ACTIVITY' AND id>? AND id<=? ORDER BY id",
            (lower, maximum),
        ):
            activity = json.loads(encoded)
            if activity.get("type") != "TRADE":
                token = activity.get("asset") or activity.get("token_id")
                if token:
                    nontrade.add(str(token))
    finally:
        connection.close()
    recorded_at = datetime.now(UTC)
    entries, controls = [], []
    post_windows: list[dict[str, Any]] = []
    kinds: Counter[str] = Counter()
    source_kinds: Counter[str] = Counter()
    role_proofs: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="exp0018-replay-") as temporary:
        store = BattleStore(Path(temporary), min_free_bytes=1_000_000_000)
        try:
            observer = Reconstruction(store, weather, experimental_deltas)
            cursor = lower
            while cursor < maximum:
                next_cursor, rows = source_rows(source, cursor)
                if next_cursor <= cursor:
                    raise RuntimeError("Frozen source tail did not advance")
                for row in rows:
                    if row["id"] > maximum:
                        break
                    source_kinds[row["kind"]] += 1
                    if row["kind"] == "ROLE_EVIDENCE":
                        role_proofs[str(row["payload"].get("trade_id"))] = row["payload"]
                    events = observer.ingest(row, recorded_at)
                    for event in events:
                        kinds[event["kind"]] += 1
                        if event["kind"] == "ENTRY_RECONSTRUCTION":
                            data = event["payload"]
                            data["evidence_class"] = "RETROSPECTIVE_REPLAY_OF_PROSPECTIVE_CAPTURES"
                            data["replay_created_at"] = recorded_at.isoformat()
                            entries.append(data)
                        elif event["kind"] == "MATCHED_CONTROL_CANDIDATE":
                            controls.append(event["payload"])
                        elif event["kind"] == "ENTRY_POST_WINDOW":
                            post_windows.append(event["payload"])
                cursor = min(next_cursor, maximum)
            stats = dict(observer.state["reconstruction_counts"])
        finally:
            store.close()
    lots, matches, sales = reconstruct(trades, nontrade_tokens=nontrade)
    by_trade = {r["trade_id"]: r for r in lots}
    rows = []
    for entry in entries:
        lot = by_trade.get(entry["trade_id"])
        entry["conditional_fifo"] = lot
        entry["role_evidence_joined_later"] = role_proofs.get(entry["trade_id"])
        entry["role_evidence_scope"] = "LATER_KNOWLEDGE_NOT_ASOF_SIGNAL"
        entry["post_windows"] = [p for p in post_windows if p["trade_id"] == entry["trade_id"]]
        for followup in entry["post_windows"]:
            for side, book in followup["books"].items():
                if book:
                    entry["books"][side]["history"].append(book)
        rows.append(
            dict(
                trade_id=entry["trade_id"],
                condition_id=entry["condition_id"],
                station=entry["station"],
                execution=entry["source_trade_timestamp"],
                detection=entry["original_first_detection"],
                price=entry["price"],
                detection_delay_seconds=(
                    known_clock(entry["original_first_detection"])
                    - known_clock(entry["source_trade_timestamp"])
                ).total_seconds(),
                no_pre_mid=entry["books"]["no"]["pre_execution"]["mid"],
                no_pre_bid=entry["books"]["no"]["pre_execution"]["bid"],
                no_pre_ask=entry["books"]["no"]["pre_execution"]["ask"],
                no_pre_received_at=entry["books"]["no"]["pre_execution_received_at"],
                yes_pre_received_at=entry["books"]["yes"]["pre_execution_received_at"],
                yes_pre_mid=entry["books"]["yes"]["pre_execution"]["mid"],
                no_spread=entry["books"]["no"]["pre_execution"]["spread"],
                no_imbalance=entry["books"]["no"]["pre_execution"]["imbalance"],
                change_5s=entry["books"]["no"]["price_changes"]["change_5s"],
                change_30s=entry["books"]["no"]["price_changes"]["change_30s"],
                metar_offset_seconds=entry["metar_schedule"].get("signed_offset_seconds"),
                weather_status=entry["weather_at_execution"]["status"],
                window_300s=entry["books"]["no"]["pre_execution_quality"]["window_300s"],
                fifo_status=lot.get("status") if lot else None,
                matched_quantity=lot.get("matched_quantity") if lot else None,
                gross_pnl=lot.get("gross_pnl") if lot else None,
                net_pnl=None,
            )
        )
    # Controls were matched without future knowledge. Attribution is a later review.
    cutoff_time = clock(last[0]) if last else recorded_at
    for control in controls:
        at = known_clock(control["matched_at"])
        seen = [
            t["trade_id"]
            for t in trades
            if t.get("condition_id") == control["condition_id"]
            and (t_at := clock(t.get("source_trade_timestamp")))
            and abs((t_at - at).total_seconds()) <= 300
        ]
        deadline = clock(control["attribution_deadline"])
        control["attribution_status"] = (
            "ENTRY_OBSERVED_IN_WINDOW"
            if seen
            else "NO_ENTRY_OBSERVED_300S_DELAY_CENSOR_REMAINS"
            if cutoff_time and deadline and cutoff_time >= deadline
            else "PENDING_FOLLOWUP"
        )
        control["matched_trade_ids"] = seen
        control["no_entry_proven"] = False
    summary = dict(
        entries=len(entries),
        paired_pre_execution=sum(
            r["no_pre_received_at"] is not None and r["yes_pre_received_at"] is not None
            for r in rows
        ),
        paired_two_sided_pre_execution=sum(
            r["no_pre_mid"] is not None and r["yes_pre_mid"] is not None for r in rows
        ),
        no_pre_execution=sum(r["no_pre_mid"] is not None for r in rows),
        no_pre_snapshot=sum(r["no_pre_received_at"] is not None for r in rows),
        complete_300s_no_windows=sum(
            r["window_300s"] == "SNAPSHOTS_COVER_HORIZON_NOT_CONTINUITY_PROOF" for r in rows
        ),
        controls=len(controls),
        censored_buys=kinds["CENSORED_BUY"],
        median_detection_delay_seconds=median([r["detection_delay_seconds"] for r in rows])
        if rows
        else None,
        conditional_closed_lots=sum(
            bool(by_trade.get(e["trade_id"], {}).get("remaining_quantity") == 0) for e in entries
        ),
        net_profit_identifiable=False,
        frozen_trigger="INSUFFICIENT_PROSPECTIVE_PAIRED_BOOK_HISTORY",
    )
    source_fingerprint = hashlib.sha256(
        json.dumps(
            dict(path=str(source.resolve()), lower=lower, maximum=maximum, first=first, last=last),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    result: dict[str, Any] = dict(
        version=VERSION,
        published_at=recorded_at.isoformat(),
        mode="RETROSPECTIVE_REPLAY_OF_PROSPECTIVE_CAPTURES",
        status="BOUNDED_AUDIT_NOT_LIVE_OBSERVER",
        source_cutoff=dict(
            lower_exclusive=lower,
            maximum_inclusive=maximum,
            first_receipt=first[0] if first else None,
            last_receipt=last[0] if last else None,
            immutable_id_fingerprint=source_fingerprint,
            indexes=indexes,
        ),
        summary=summary,
        book_mode="EXPERIMENTAL_BBO_CHECKED_DELTAS"
        if experimental_deltas
        else "FULL_SNAPSHOTS_ONLY",
        source_kinds=dict(source_kinds),
        event_kinds=dict(kinds),
        counters=stats,
        entries=entries,
        controls=controls,
        elapsed_seconds=time.monotonic() - started,
        limitations=[
            "Recorded bounded watchlist, not all market opportunities",
            "Snapshots are sparse and reset on delta/gap; continuous depth unverified",
            "Execution clocks have one-second precision; placement time unknown",
            "Weather query is bounded, exact configured station required",
            "No frozen prospective trigger, matched outcome efficacy not identified",
            "Unknown inventory, costs and queues prevent copy-profit claims",
            "Source retention is append-only; replay cutoff is by immutable ID, not historical publication",
        ],
    )
    output.mkdir(parents=True, exist_ok=True)
    raw_coverage = raw_book_coverage(source, entries, lower, maximum)
    atomic_json(
        output / "exp0018_raw_book_coverage.json",
        dict(
            cutoff=result["source_cutoff"],
            method="RAW_BOOK_EXACT_TOKEN_SHORT_KIND_ID_BATCHES500",
            entries=raw_coverage,
        ),
    )
    atomic_json(output / "exp0018_entry_trigger_reconstruction.json", result)
    columns = (
        list(rows[0])
        if rows
        else ["trade_id", "execution", "detection", "no_pre_mid", "yes_pre_mid", "net_pnl"]
    )
    write_csv(output / "exp0018_entry_features.csv", rows, columns)
    write_csv(
        output / "exp0018_controls.csv",
        controls,
        [
            "entry_trade_id",
            "condition_id",
            "station",
            "settlement_day",
            "matched_at",
            "price",
            "spread",
            "depth",
            "attribution_status",
            "no_entry_proven",
        ],
    )
    write_csv(
        output / "exp0018_fifo_matches.csv",
        matches,
        [
            "buy_trade_id",
            "sell_trade_id",
            "buy_time",
            "sell_time",
            "quantity",
            "buy_price",
            "sell_price",
            "holding_seconds",
            "gross_pnl",
            "net_pnl",
            "accounting_status",
        ],
    )
    lines = [
        "# EXP0018 — HighTempTation entry trigger reconstruction",
        "",
        f"Generated {recorded_at.isoformat()}. {result['mode']}.",
        f"Frozen source IDs ({lower}, {maximum}]; receipts {first[0] if first else None} to {last[0] if last else None}.",
        "Fingerprint identifies immutable ID boundaries, not a full database content hash. Reads close after <=1000 rows.",
        "",
        "## Coverage and measured results",
        "",
        "```json",
        json.dumps(summary, indent=2),
        "```",
        "",
        "## Real entries (all qualifying rows in CSV)",
        "",
        "| Execution UTC | Station | Price | NO pre-mid | YES pre-mid | Detection delay s |",
        "|---|---|---:|---:|---:|---:|",
    ]
    lines += [
        f"|{r['execution']}|{r['station']}|{r['price']}|{r['no_pre_mid']}|{r['yes_pre_mid']}|{r['detection_delay_seconds']:.3f}|"
        for r in rows[-30:]
    ]
    lines += [
        "",
        "## Independent raw-book coverage",
        "",
        f"{sum(r['book_before_count'] == 0 for r in raw_coverage)}/{len(raw_coverage)} entries have no earlier NO full snapshot anywhere in this frozen source interval. This source check bypasses our ring and midpoint calculations.",
    ]
    for entry in entries:
        jump = entry["books"]["no"]["price_changes"].get("largest_adjacent_bid_increase")
        if jump is None or jump <= 0:
            continue
        changes = entry["books"]["no"]["price_changes"]
        before = entry["books"]["no"]["pre_execution"]
        lines += [
            "",
            f"Observed repricing case: station {entry['station']}, trade `{entry['trade_id']}`; source trade timestamp {entry['source_trade_timestamp']}, first detection {entry['original_first_detection']}, BUY price {entry['price']} and size {entry['quantity']}.",
            f"Largest adjacent recorded NO bid increase {jump:.4f} received {changes['largest_adjacent_bid_increase_received_at']}; latest eligible bid {before['bid']}, ask {before['ask']}. A missing ask means no recorded direct BUY liquidity at that snapshot, not a zero price.",
            "This movement precedes the Data API source timestamp but NOT necessarily the actual matching-engine fill or trader decision. It could be a consequence of that very trade before later reporting/settlement. No independent official publication receipt is available here to distinguish the hypotheses. Later API taker evidence does not reveal order placement time.",
        ]
    lines += [
        "",
        "## Interpretation",
        "",
        "No trigger is promoted. Timing near a nominal METAR is not proof of reacting to its publication. Sparse/missing pre-entry books cannot distinguish momentum, resting limits and weather signals. Correctly time-aligned nulls are more informative than invented triggers.",
        "An empty ask is an observed one-sided book, not an absent timestamp or missing capture. Midpoint-based coverage is reported separately from fresh snapshot/paired coverage. Check raw_book_coverage.json to distinguish truly absent pre-entry packets from one-sided books and reconstruction restrictions.",
        "",
        "Controls match exact station/day plus price ±0.02, spread ±0.02, depth ratio 0.5–2 and <=10s old; candidate metadata/books must be known by detection. Matching currently does NOT balance verified publication context, forecast state, market age or time-to-settlement: control efficacy is incomplete, not a causal strategy test. No-entry remains censored by detection lag. Market/day clusters and overlapping entries are not independent trials.",
        "",
        "Conditional FIFO reuses EXP0012; opening inventory, non-trade history before the cutoff, fees and gas can be unknown. Gross matches are not full portfolio net PnL. A 0.99 SELL print is not our executable maker/taker exit. No shadow fills were generated.",
        "",
        "Source weather context is only last 3000 weather rows, uncensored receipts <= execution; forecasts/PWS/publication clocks not available remain UNKNOWN. Other stations aren't mapped from city guesses. Nearest nominal times are current configured schedules, not verified historical publication times.",
        "",
        "## Method and scope",
        "",
        "NO BUYs at 0.90–0.99 with original PROSPECTIVE_POLL receipt evidence. Startup/backfill/future-clock rows censored. Pre-execution cutoff is strictly before the lower boundary of the source execution second. A separate detection view uses original wallet first receipt. Retrospective replay was created now; no prediction is backdated. No production processes, policies or records changed.",
        "",
        "## Minimal next experiment",
        "",
        "The separate bounded paired-capture command now freezes 16 markets before future entries and reuses the public stream with raw-first storage. It does not change existing subscriptions. Persistent activation still requires approval; reconnect stability must be investigated first. EXP0019 should freeze a small trigger family only on future independent settlement days, include non-entry controls and reject unknown execution costs/depth.",
        "",
        "## Limitations",
        "",
    ] + [f"- {s}" for s in result["limitations"]]
    (output / "exp0018_entry_trigger_reconstruction.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    if publish:
        if source.resolve() != TRADER.resolve():
            raise ValueError("Cannot publish nonproduction source as current dashboard evidence")
        atomic_json(
            ROOT / "src/premetar/dashboard/static/entry_reconstruction_summary.json",
            dict(result, entries=entries[-30:], controls=[]),
        )
    return {k: v for k, v in result.items() if k not in {"entries", "controls"}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-rows", type=int, default=1_500_000)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--experimental-deltas", action="store_true")
    parser.add_argument("--maximum-id", type=int)
    args = parser.parse_args()
    print(
        json.dumps(
            analyze(
                args.max_rows,
                publish=args.publish,
                experimental_deltas=args.experimental_deltas,
                maximum_id=args.maximum_id,
            ),
            indent=2,
        )
    )
