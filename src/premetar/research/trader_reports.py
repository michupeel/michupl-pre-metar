"""Bounded, read-only exports of trader shadow-monitor evidence."""

import csv
import json
from bisect import bisect_right
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from premetar.research.trader_store import readonly_connection


def market_identity(slug: str) -> tuple[str, str]:
    for prefix, kind in (("highest-temperature-in-", "TMAX"), ("lowest-temperature-in-", "TMIN")):
        if slug.startswith(prefix) and "-on-" in slug:
            return kind, slug.removeprefix(prefix).split("-on-", 1)[0]
    return "OTHER", "UNKNOWN"


def characterize(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Descriptive first later SELL; never a lot match, full exit or PnL estimate."""
    source_count = len(trades)
    trades = [
        row
        for row in trades
        if row.get("token_id") and isinstance(row.get("source_trade_timestamp"), str)
    ]
    sell_clocks: dict[str, list[str]] = {}
    for trade in trades:
        if trade.get("side") == "SELL":
            sell_clocks.setdefault(str(trade["token_id"]), []).append(
                trade["source_trade_timestamp"]
            )
    for clocks in sell_clocks.values():
        clocks.sort()
    delays = []
    missing = same_second = buys = 0
    for trade in trades:
        if trade.get("side") != "BUY":
            continue
        buys += 1
        stamp = trade["source_trade_timestamp"]
        clocks = sell_clocks.get(str(trade["token_id"]), [])
        index = bisect_right(clocks, stamp)
        same_second += int(stamp in clocks)
        if index == len(clocks):
            missing += 1
        else:
            delays.append(
                (
                    datetime.fromisoformat(clocks[index]) - datetime.fromisoformat(stamp)
                ).total_seconds()
            )
    return {
        "buy_records": buys,
        "excluded_missing_clock_or_token": source_count - len(trades),
        "with_strictly_later_sell": len(delays),
        "without_later_sell": missing,
        "same_second_ambiguous": same_second,
        "median_first_later_sell_seconds": median(delays) if delays else None,
        "first_later_sell_within_10_seconds": sum(delay <= 10 for delay in delays),
        "first_later_sell_within_60_seconds": sum(delay <= 60 for delay in delays),
        "market_kinds": dict(Counter(market_identity(str(t.get("slug") or ""))[0] for t in trades)),
        "source_time_precision_seconds": 1,
        "interpretation": "First later same-token SELL, not proof of full liquidation, linked lots, fees or profit; source timestamps are not decision times",
    }


def _csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row}) or ["status"]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, sort_keys=True)
                    if isinstance(value, (dict, list))
                    else value
                    for key, value in row.items()
                }
            )


def generate_reports(database: Path, output: Path) -> dict[str, Any]:
    """A single read transaction copies normalized evidence, then closes before rendering."""
    if not database.is_file():
        raise FileNotFoundError(database)
    connection = readonly_connection(database)
    try:
        connection.execute("BEGIN")
        counts = dict(connection.execute("SELECT kind,COUNT(*) FROM events GROUP BY kind"))
        rows = connection.execute(
            "SELECT kind,received_at,payload FROM events WHERE kind NOT IN ('RAW','BOOK','WS_RAW') "
            "ORDER BY id LIMIT 100000"
        ).fetchall()
    finally:
        connection.close()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for kind, received, encoded in rows:
        payload = json.loads(encoded)
        grouped.setdefault(kind, []).append({"event_receipt_utc": received, **payload})
    output.mkdir(parents=True, exist_ok=True)
    trades = sorted(
        grouped.get("TRADE", []), key=lambda row: str(row.get("source_trade_timestamp", ""))
    )
    role_evidence = {row["trade_id"]: row for row in grouped.get("ROLE_EVIDENCE", [])}
    trades = [
        {**row, "verified_role": role_evidence.get(row.get("trade_id"), {}).get("role", "UNKNOWN")}
        for row in trades
    ]
    shadows = grouped.get("SHADOW", [])
    weather = grouped.get("WEATHER", [])
    _csv(output / "hightemptation_trades.csv", trades)
    _csv(
        output / "hightemptation_detection_latency.csv",
        [
            {
                key: value
                for key, value in trade.items()
                if key
                in {
                    "trade_id",
                    "source_trade_timestamp",
                    "first_collector_receipt_utc",
                    "trade_detection_latency",
                    "detection_latency_seconds",
                    "historical",
                    "bootstrap",
                    "event_receipt_utc",
                    "evidence_class",
                }
            }
            for trade in trades
        ],
    )
    _csv(output / "hightemptation_shadow_trades.csv", shadows)
    _csv(output / "hightemptation_weather_context.csv", weather)
    _csv(output / "hightemptation_activity.csv", grouped.get("ACTIVITY", []))
    endpoint_rows = grouped.get("ENDPOINT_RECEIPT", [])
    races: dict[str, dict[str, Any]] = {}
    for row in endpoint_rows:
        race = races.setdefault(row["trade_id"], {"trade_id": row["trade_id"]})
        race[row["endpoint"]] = row["first_endpoint_receipt"]
        race[row["endpoint"] + "_evidence"] = row["evidence_class"]
    for race in races.values():
        paired = all(
            race.get(endpoint + "_evidence") == "PROSPECTIVE_POLL"
            for endpoint in ("TRADES_V2", "ACTIVITY_V2")
        )
        race["race_status"] = "PAIRED_PROSPECTIVE" if paired else "CENSORED_OR_INCOMPLETE"
        race["activity_minus_trades_seconds"] = (
            (
                datetime.fromisoformat(race["ACTIVITY_V2"])
                - datetime.fromisoformat(race["TRADES_V2"])
            ).total_seconds()
            if paired
            else None
        )
    _csv(output / "hightemptation_endpoint_race.csv", list(races.values()))
    generated = datetime.now(UTC).isoformat()
    header = f"# EXP-0011 public trader research\n\nGenerated UTC: {generated}\n\n"
    header += "Historical/bootstrap trades are not prospective detections. Source trade time is not order placement time.\n\n"
    header += f"Recorded event counts: `{json.dumps(counts, sort_keys=True)}`.\n\n"
    evidence_counts = Counter(str(trade.get("evidence_class", "UNKNOWN")) for trade in trades)
    prospective = [trade for trade in trades if trade.get("evidence_class") == "PROSPECTIVE_POLL"]
    latencies = [
        float(trade["trade_detection_latency"])
        for trade in prospective
        if isinstance(trade.get("trade_detection_latency"), (int, float))
        and not isinstance(trade.get("trade_detection_latency"), bool)
    ]
    latency_text = (
        f"Median source execution timestamp → first collector receipt: {median(latencies):.3f}s "
        f"(N={len(latencies)}). This includes upstream indexing, polling and clock error; "
        "it is not pure network latency. Upstream second precision does not support millisecond claims."
        if latencies
        else "INSUFFICIENT DATA: no uncensored prospective detection latencies."
    )
    shadow_counts = Counter(str(shadow.get("status", "UNKNOWN")) for shadow in shadows)
    grouping: Counter[tuple[str, str, str, str, str, str]] = Counter()
    for trade in trades:
        slug = str(trade.get("event_slug") or trade.get("slug") or "")
        kind, city = market_identity(slug)
        try:
            price = float(trade.get("price", "nan"))
            price_bin = (
                "<0.50"
                if price < 0.5
                else "0.50–0.89"
                if price < 0.9
                else "0.90–0.969"
                if price < 0.97
                else "0.97–1.00"
                if price <= 1
                else "UNKNOWN"
            )
        except (TypeError, ValueError):
            price_bin = "UNKNOWN"
        grouping[
            (
                city,
                kind,
                str(trade.get("side", "UNKNOWN")),
                str(trade.get("outcome", "UNKNOWN")),
                str(trade.get("verified_role", "UNKNOWN")),
                price_bin,
            )
        ] += 1
    group_table = "| City from recorded slug | Statistic | Side | Outcome | Role evidence | Price bin | Trades |\n|---|---|---|---|---|---|---|\n"
    for group, count in sorted(grouping.items()):
        group_table += (
            "| " + " | ".join(value.replace("|", "/") for value in group) + f" | {count} |\n"
        )
    samples = "| Class | Source execution UTC | First receipt UTC | Side | Outcome | Price | Shares | Market |\n|---|---|---|---|---|---|---|---|\n"
    for trade in trades[-20:]:
        values = [
            trade.get("evidence_class"),
            trade.get("source_trade_timestamp"),
            trade.get("first_collector_receipt_utc"),
            trade.get("side"),
            trade.get("outcome"),
            trade.get("price"),
            trade.get("size"),
            trade.get("market_title"),
        ]
        samples += (
            "| "
            + " | ".join(str(value).replace("|", "/").replace("\n", " ") for value in values)
            + " |\n"
        )
    (output / "hightemptation_live_activity.md").write_text(
        header
        + f"TRADE records: {len(trades)}; SHADOW records: {len(shadows)}.\n\n"
        + f"Evidence classes: `{json.dumps(dict(evidence_counts), sort_keys=True)}`.\n\n"
        + f"Uncensored prospective trades: {len(prospective)}. {latency_text}\n\n"
        + "## Latest captured trades\n\n"
        + samples
        + "\n"
        + "## Complete exported cohort breakdown\n\n"
        + group_table
        + "\n"
        + f"Shadow outcomes: `{json.dumps(dict(shadow_counts), sort_keys=True)}`.\n\n"
        + "Exports include all observed sides, failures and unavailable evidence. "
        "See raw capture and event payloads for exact first-receipt provenance. "
        "Normalized export cap: 100000 non-book events; event counts above disclose full database counts.\n",
        encoding="utf-8",
    )
    (output / "hightemptation_shadow_pnl.md").write_text(
        header
        + "## Profitability\n\nINSUFFICIENT DATA for verified realized copy-trading profitability. "
        "Unresolved positions are not wins. Unknown fees, settlement rules, missing depth or unavailable "
        "exit evidence prevent certified net PnL. Original trader PnL is not copy-trader PnL. "
        "No aggregate profit factor, ROI or drawdown is inferred from missing outcomes. "
        "Execution estimates are hypothetical displayed-liquidity estimates, not actual fills.\n",
        encoding="utf-8",
    )
    (output / "hightemptation_signal_forensics.md").write_text(
        header
        + "## Historical descriptive characterization\n\n"
        + "```json\n"
        + json.dumps(
            {
                "all_records": characterize(trades),
                "by_statistic": {
                    kind: characterize(
                        [
                            row
                            for row in trades
                            if market_identity(str(row.get("slug") or ""))[0] == kind
                        ]
                    )
                    for kind in ("TMAX", "TMIN", "OTHER")
                },
            },
            indent=2,
        )
        + "\n```\n\n"
        + "TMAX and TMIN are distinct market cohorts. Historical exit timing does not establish copy profitability.\n\n"
        + "## Interpretation\n\nExecution time does not establish decision time. "
        "Maker/taker remains UNKNOWN unless separately verified by reliable execution-role evidence. "
        "Resting orders are a competing explanation. A snapshot fetched after trade detection cannot "
        "reconstruct the pre-trade book. Weather context is available-as-of only where recorded receipt "
        "times demonstrate that condition. No missing forecast is substituted retrospectively.\n",
        encoding="utf-8",
    )
    hypotheses = [
        (
            "H1 Early official information",
            "Official original receipt precedes wallet execution",
            "Unobserved faster feeds and order placement time",
        ),
        (
            "H2 PWS information",
            "Fresh causal PWS signal precedes execution",
            "Trader access to same station; confounding signals",
        ),
        (
            "H3 Probabilistic Tmax",
            "Frozen forecasts explain entries and comparable no-trades",
            "Original forecast versions and probability model",
        ),
        (
            "H4 Known-information mispricing",
            "Exact verified rules and already public irreversible bound",
            "Rules, corrections, source precision",
        ),
        (
            "H5 Microstructure",
            "Independent book movement precedes execution",
            "Wallet attribution and queue position",
        ),
        (
            "H6 Resting limits",
            "Verified maker role supports earlier resting instruction",
            "Order creation/cancellation history",
        ),
        (
            "H7 Hybrid",
            "Different predeclared regimes explain out-of-sample entries",
            "Independent days and negative controls",
        ),
    ]
    text = (
        header
        + "| Hypothesis | Discriminating observation | Missing evidence | Conclusion |\n|---|---|---|---|\n"
    )
    for name, observation, missing in hypotheses:
        text += f"| {name} | {observation} | {missing} | UNVERIFIED |\n"
    (output / "hightemptation_hypothesis_matrix.md").write_text(text, encoding="utf-8")
    return {
        "counts": counts,
        "trades_exported": len(trades),
        "shadows_exported": len(shadows),
        "output": str(output.resolve()),
    }
