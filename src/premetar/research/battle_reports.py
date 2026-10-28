"""Deterministic reports from immutable shadow events; no performance fabrication."""

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from premetar.research.battle_monitor import DIRECTORY, ROOT
from premetar.research.battle_store import read_battle


def generate(
    directory: Path = DIRECTORY, root: Path = ROOT, at: datetime | None = None
) -> dict[str, Any]:
    rows = read_battle(directory, at, limit=100000)
    metrics = [e for e in rows if e["kind"] == "METRIC"]
    latest = metrics[-1]["payload"] if metrics else {}
    realization = latest.get("realization") or {}
    first_run = next((e["at"] for e in rows if e["kind"] == "RUN"), None)
    alignments: dict[tuple[Any, Any], dict[str, Any]] = {}
    for event in metrics:
        for row in (event["payload"].get("realization") or {}).get("history", []):
            key = (row.get("metar_id"), row.get("forecast_snapshot_id"))
            alignments.setdefault(
                key,
                dict(
                    row,
                    evaluation_created_at=event["at"],
                    evaluation_kind="RETROSPECTIVE_BOOTSTRAP_CONTEXT"
                    if first_run and str(row.get("first_received", "")) < first_run
                    else "PROSPECTIVE_REALIZATION_AFTER_REFERENCE_RECEIPT_NOT_A_TRADE",
                ),
            )
    research, trader = root / "reports/research", root / "reports/trader"
    research.mkdir(parents=True, exist_ok=True)
    trader.mkdir(parents=True, exist_ok=True)
    exports = {}
    for name, values in (
        (
            "exp0015_events",
            [
                dict(
                    id=e["id"],
                    at=e["at"],
                    kind=e["kind"],
                    payload=json.dumps(e["payload"], sort_keys=True, ensure_ascii=False),
                )
                for e in rows
                if not e["kind"].endswith("RAW")
            ],
        ),
        ("exp0015_portfolios", latest.get("strategies", [])),
        ("exp0014_metar_alignment", list(alignments.values())),
    ):
        path = (research if name.startswith("exp0014") else trader) / (name + ".csv")
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=sorted({k for r in values for k in r}) or ["status"]
            )
            writer.writeheader()
            writer.writerows(
                {
                    k: json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v
                    for k, v in r.items()
                }
                for r in values
            )
        exports[name] = str(path)
    cutoff = metrics[-1]["at"] if metrics else None
    text = "# EXP-0014 — EPWA forecast realization\n\n"
    text += f"Immutable metric cutoff: {cutoff}. No production model changes.\n\n"
    text += (
        "Current deterministic assessment (not a calibrated probability):\n\n```json\n"
        + json.dumps(realization, indent=2, ensure_ascii=False)
        + "\n```\n\n"
    )
    text += "Forecast snapshot must predate nominal observation; midpoint error is not precise thermometer error. Interval residual, direct vs interpolated forecast, latest available corrections and first receipts are exported. Cloud association is untested; no solar/cloud causal claim. Adaptive Tmax is experimental; daily API aggregate and hourly-point peak are different targets.\n"
    (research / "exp0014_epwa_forecast_realization.md").write_text(text, encoding="utf-8")
    counts = {
        kind: sum(e["kind"] == kind for e in rows) for kind in sorted({e["kind"] for e in rows})
    }
    text = "# EXP-0015 — SIMPLE Limit99 vs WEATHER vs HYBRID\n\n"
    text += f"Cutoff: {cutoff}. Scope: prospective shadow only, frozen config at RUN. Counts below include independent latency/scenario simulations; they are NOT independent trades or days.\n\n"
    text += "## Event funnel\n\n```json\n" + json.dumps(counts, indent=2) + "\n```\n\n"
    text += "Family | Mode | Scenario | Latency ms | Submitted | Filled BUY orders | Open positions | Realized USD | Unrealized USD | Net USD\n--- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---:\n"
    for p in latest.get("strategies", []):
        text += (
            " | ".join(
                str(p.get(k, "NOT IDENTIFIABLE"))
                for k in (
                    "family",
                    "mode",
                    "scenario",
                    "latency_ms",
                    "submitted_orders",
                    "supported_buy_fills",
                    "open_positions",
                    "realized_pnl",
                    "unrealized_pnl",
                    "net_pnl",
                )
            )
            + "\n"
        )
    text += "\nUnknown arrival books are UNKNOWN execution, not exchange rejections or demonstrated nonfills. Original prototype ORDER_REJECTED records with ARRIVAL_BOOK reasons are preserved and paired with ACCOUNTING_EXCLUSION events. Affected historical zero-PnL metrics are excluded from valid economics. Unknown BUY inventory retains worst-case cash reservation; net/realized/unrealized PnL and equity remain null, with explicit possible-position and per-winner loss bounds. Pessimistic no-assured-fill is not a lower profitability bound.\n"
    text += "\n## Questions and interpretation\n\n"
    questions = [
        "How often can NO actually be bought in the strict range?",
        "How often can inventory subsequently exit at0.99?",
        "Median supported exit time?",
        "Unfilled orders?",
        "Exits never filled?",
        "Worst losses?",
        "Positive net profitability after fees?",
        "Does maker outperform taker?",
        "Does weather improve SIMPLE?",
        "Is HYBRID better on matched opportunities?",
        "Does confidence deterioration precede repricing?",
        "Does price level explain profitability?",
        "Does profit survive conservative fills?",
        "Enough prospective evidence?",
        "Measurable incremental weather value?",
    ]
    for index, q in enumerate(questions, 1):
        text += f"{index}. {q} **INSUFFICIENT PROSPECTIVE EVIDENCE / NOT IDENTIFIABLE**. See full per-variant order funnel, open inventory and exposure; zero events is not a zero-risk proof.\n"
    text += "\nMaker scenarios separate: pessimistic has no identified maker fill, evidence-supported depends on anonymous source trade chronology/queue assumptions, optimistic is an upper bound. Touch/quote is not a fill. Complementary matching THEORETICAL_ONLY; no double-counted liquidity. Conditional taker uses post-arrival depth within2s, not decision ask. Fees require captured explicit current zero schedule; otherwise blocked. No rebates/gas assumptions. Pending SELLs only against owned inventory. Unknown liquidation produces null PnL, plus zero-recovery stress and per-winner correlated losses.\n\n"
    text += "Exit horizons5/10/30/60/300/900/3600seconds and settlement, full/partial exits, drawdown, profit factor, expectancy and day-cluster uncertainty need completed future positions. No closed-only profitability claim. Controls are frozen in EXP0015_PROTOCOL; matched randomized outcomes remain NOT IDENTIFIABLE until recorded compatible books exist. WEATHER is SIGNAL-ONLY; this is not a spurious head-to-head profitability ranking. Neither strategy has demonstrated a robust edge.\n\n"
    text += "Read bounds:```json\n" + json.dumps(rows.metadata, indent=2) + "\n```\n"
    (trader / "exp0015_simple_limit99_vs_weather.md").write_text(text, encoding="utf-8")
    result = dict(
        cutoff=cutoff,
        journal_cutoff=max((e["at"] for e in rows), default=None),
        counts=counts,
        sample_days=latest.get("sample_days", []),
        limits=rows.metadata,
        exports=exports,
    )
    (trader / "exp0015_summary.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    return result
