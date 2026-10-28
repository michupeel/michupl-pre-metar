# EXP-0015 — SIMPLE Limit99 vs WEATHER vs HYBRID

Cutoff: 2026-10-28T23:26:01.203986+00:00. Scope: prospective shadow only, frozen config at RUN. Counts below include independent latency/scenario simulations; they are NOT independent trades or days.

## Event funnel

```json
{
  "ACCOUNTING_EXCLUSION": 30,
  "BUY_SUBMITTED": 30,
  "CANCEL_REQUEST": 9,
  "CONFIDENCE": 4,
  "CONTROL_ANNOTATION": 15,
  "CONTROL_HORIZON_UNRESOLVED": 90,
  "CONTROL_UNMATCHED": 15,
  "FORECAST": 10,
  "FORECAST_RAW": 10,
  "METRIC": 73,
  "ORDER_EXPIRED": 9,
  "ORDER_REJECTED": 21,
  "ORDER_RESTING": 9,
  "REALIZATION_BOOTSTRAP": 1,
  "RESTART_GAP": 5,
  "RUN": 10,
  "STOP": 9,
  "WEATHER_REJECT": 15
}
```

Family | Mode | Scenario | Latency ms | Submitted | Filled BUY orders | Open positions | Realized USD | Unrealized USD | Net USD
--- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---:
HYBRID | MAKER | EVIDENCE_SUPPORTED | 100 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
HYBRID | MAKER | EVIDENCE_SUPPORTED | 1000 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
HYBRID | MAKER | EVIDENCE_SUPPORTED | 3000 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
HYBRID | MAKER | EVIDENCE_SUPPORTED | 500 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
HYBRID | MAKER | EVIDENCE_SUPPORTED | 5000 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
HYBRID | MAKER | OPTIMISTIC_UPPER_BOUND | 100 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
HYBRID | MAKER | OPTIMISTIC_UPPER_BOUND | 1000 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
HYBRID | MAKER | OPTIMISTIC_UPPER_BOUND | 3000 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
HYBRID | MAKER | OPTIMISTIC_UPPER_BOUND | 500 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
HYBRID | MAKER | OPTIMISTIC_UPPER_BOUND | 5000 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
HYBRID | MAKER | PESSIMISTIC | 100 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
HYBRID | MAKER | PESSIMISTIC | 1000 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
HYBRID | MAKER | PESSIMISTIC | 3000 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
HYBRID | MAKER | PESSIMISTIC | 500 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
HYBRID | MAKER | PESSIMISTIC | 5000 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
HYBRID | TAKER | DEPTH_SUPPORTED | 100 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
HYBRID | TAKER | DEPTH_SUPPORTED | 1000 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
HYBRID | TAKER | DEPTH_SUPPORTED | 3000 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
HYBRID | TAKER | DEPTH_SUPPORTED | 500 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
HYBRID | TAKER | DEPTH_SUPPORTED | 5000 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
SIMPLE | MAKER | EVIDENCE_SUPPORTED | 100 | 1 | 0 | 0 | None | None | None
SIMPLE | MAKER | EVIDENCE_SUPPORTED | 1000 | 1 | 0 | 0 | None | None | None
SIMPLE | MAKER | EVIDENCE_SUPPORTED | 3000 | 1 | 0 | 0 | None | None | None
SIMPLE | MAKER | EVIDENCE_SUPPORTED | 500 | 1 | 0 | 0 | None | None | None
SIMPLE | MAKER | EVIDENCE_SUPPORTED | 5000 | 1 | 0 | 0 | None | None | None
SIMPLE | MAKER | OPTIMISTIC_UPPER_BOUND | 100 | 1 | 0 | 0 | None | None | None
SIMPLE | MAKER | OPTIMISTIC_UPPER_BOUND | 1000 | 1 | 0 | 0 | None | None | None
SIMPLE | MAKER | OPTIMISTIC_UPPER_BOUND | 3000 | 1 | 0 | 0 | None | None | None
SIMPLE | MAKER | OPTIMISTIC_UPPER_BOUND | 500 | 1 | 0 | 0 | None | None | None
SIMPLE | MAKER | OPTIMISTIC_UPPER_BOUND | 5000 | 1 | 0 | 0 | None | None | None
SIMPLE | MAKER | PESSIMISTIC | 100 | 1 | 0 | 0 | None | None | None
SIMPLE | MAKER | PESSIMISTIC | 1000 | 1 | 0 | 0 | None | None | None
SIMPLE | MAKER | PESSIMISTIC | 3000 | 1 | 0 | 0 | None | None | None
SIMPLE | MAKER | PESSIMISTIC | 500 | 1 | 0 | 0 | None | None | None
SIMPLE | MAKER | PESSIMISTIC | 5000 | 1 | 0 | 0 | None | None | None
SIMPLE | TAKER | DEPTH_SUPPORTED | 100 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
SIMPLE | TAKER | DEPTH_SUPPORTED | 1000 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
SIMPLE | TAKER | DEPTH_SUPPORTED | 3000 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
SIMPLE | TAKER | DEPTH_SUPPORTED | 500 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
SIMPLE | TAKER | DEPTH_SUPPORTED | 5000 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
SIMPLE_98_CONTROL | MAKER | EVIDENCE_SUPPORTED | 100 | 1 | 0 | 0 | None | None | None
SIMPLE_98_CONTROL | MAKER | EVIDENCE_SUPPORTED | 1000 | 1 | 0 | 0 | None | None | None
SIMPLE_98_CONTROL | MAKER | EVIDENCE_SUPPORTED | 3000 | 1 | 0 | 0 | None | None | None
SIMPLE_98_CONTROL | MAKER | EVIDENCE_SUPPORTED | 500 | 1 | 0 | 0 | None | None | None
SIMPLE_98_CONTROL | MAKER | EVIDENCE_SUPPORTED | 5000 | 1 | 0 | 0 | None | None | None
SIMPLE_98_CONTROL | MAKER | OPTIMISTIC_UPPER_BOUND | 100 | 1 | 0 | 0 | None | None | None
SIMPLE_98_CONTROL | MAKER | OPTIMISTIC_UPPER_BOUND | 1000 | 1 | 0 | 0 | None | None | None
SIMPLE_98_CONTROL | MAKER | OPTIMISTIC_UPPER_BOUND | 3000 | 1 | 0 | 0 | None | None | None
SIMPLE_98_CONTROL | MAKER | OPTIMISTIC_UPPER_BOUND | 500 | 1 | 0 | 0 | None | None | None
SIMPLE_98_CONTROL | MAKER | OPTIMISTIC_UPPER_BOUND | 5000 | 1 | 0 | 0 | None | None | None
SIMPLE_98_CONTROL | MAKER | PESSIMISTIC | 100 | 1 | 0 | 0 | None | None | None
SIMPLE_98_CONTROL | MAKER | PESSIMISTIC | 1000 | 1 | 0 | 0 | None | None | None
SIMPLE_98_CONTROL | MAKER | PESSIMISTIC | 3000 | 1 | 0 | 0 | None | None | None
SIMPLE_98_CONTROL | MAKER | PESSIMISTIC | 500 | 1 | 0 | 0 | None | None | None
SIMPLE_98_CONTROL | MAKER | PESSIMISTIC | 5000 | 1 | 0 | 0 | None | None | None
SIMPLE_98_CONTROL | TAKER | DEPTH_SUPPORTED | 100 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
SIMPLE_98_CONTROL | TAKER | DEPTH_SUPPORTED | 1000 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
SIMPLE_98_CONTROL | TAKER | DEPTH_SUPPORTED | 3000 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
SIMPLE_98_CONTROL | TAKER | DEPTH_SUPPORTED | 500 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
SIMPLE_98_CONTROL | TAKER | DEPTH_SUPPORTED | 5000 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0
WEATHER | SIGNAL_ONLY | NOT_IDENTIFIABLE | 0 | NOT IDENTIFIABLE | NOT IDENTIFIABLE | 0 | NOT IDENTIFIABLE | NOT IDENTIFIABLE | None

Unknown arrival books are UNKNOWN execution, not exchange rejections or demonstrated nonfills. Original prototype ORDER_REJECTED records with ARRIVAL_BOOK reasons are preserved and paired with ACCOUNTING_EXCLUSION events. Affected historical zero-PnL metrics are excluded from valid economics. Unknown BUY inventory retains worst-case cash reservation; net/realized/unrealized PnL and equity remain null, with explicit possible-position and per-winner loss bounds. Pessimistic no-assured-fill is not a lower profitability bound.

## Questions and interpretation

1. How often can NO actually be bought in the strict range? **INSUFFICIENT PROSPECTIVE EVIDENCE / NOT IDENTIFIABLE**. See full per-variant order funnel, open inventory and exposure; zero events is not a zero-risk proof.
2. How often can inventory subsequently exit at0.99? **INSUFFICIENT PROSPECTIVE EVIDENCE / NOT IDENTIFIABLE**. See full per-variant order funnel, open inventory and exposure; zero events is not a zero-risk proof.
3. Median supported exit time? **INSUFFICIENT PROSPECTIVE EVIDENCE / NOT IDENTIFIABLE**. See full per-variant order funnel, open inventory and exposure; zero events is not a zero-risk proof.
4. Unfilled orders? **INSUFFICIENT PROSPECTIVE EVIDENCE / NOT IDENTIFIABLE**. See full per-variant order funnel, open inventory and exposure; zero events is not a zero-risk proof.
5. Exits never filled? **INSUFFICIENT PROSPECTIVE EVIDENCE / NOT IDENTIFIABLE**. See full per-variant order funnel, open inventory and exposure; zero events is not a zero-risk proof.
6. Worst losses? **INSUFFICIENT PROSPECTIVE EVIDENCE / NOT IDENTIFIABLE**. See full per-variant order funnel, open inventory and exposure; zero events is not a zero-risk proof.
7. Positive net profitability after fees? **INSUFFICIENT PROSPECTIVE EVIDENCE / NOT IDENTIFIABLE**. See full per-variant order funnel, open inventory and exposure; zero events is not a zero-risk proof.
8. Does maker outperform taker? **INSUFFICIENT PROSPECTIVE EVIDENCE / NOT IDENTIFIABLE**. See full per-variant order funnel, open inventory and exposure; zero events is not a zero-risk proof.
9. Does weather improve SIMPLE? **INSUFFICIENT PROSPECTIVE EVIDENCE / NOT IDENTIFIABLE**. See full per-variant order funnel, open inventory and exposure; zero events is not a zero-risk proof.
10. Is HYBRID better on matched opportunities? **INSUFFICIENT PROSPECTIVE EVIDENCE / NOT IDENTIFIABLE**. See full per-variant order funnel, open inventory and exposure; zero events is not a zero-risk proof.
11. Does confidence deterioration precede repricing? **INSUFFICIENT PROSPECTIVE EVIDENCE / NOT IDENTIFIABLE**. See full per-variant order funnel, open inventory and exposure; zero events is not a zero-risk proof.
12. Does price level explain profitability? **INSUFFICIENT PROSPECTIVE EVIDENCE / NOT IDENTIFIABLE**. See full per-variant order funnel, open inventory and exposure; zero events is not a zero-risk proof.
13. Does profit survive conservative fills? **INSUFFICIENT PROSPECTIVE EVIDENCE / NOT IDENTIFIABLE**. See full per-variant order funnel, open inventory and exposure; zero events is not a zero-risk proof.
14. Enough prospective evidence? **INSUFFICIENT PROSPECTIVE EVIDENCE / NOT IDENTIFIABLE**. See full per-variant order funnel, open inventory and exposure; zero events is not a zero-risk proof.
15. Measurable incremental weather value? **INSUFFICIENT PROSPECTIVE EVIDENCE / NOT IDENTIFIABLE**. See full per-variant order funnel, open inventory and exposure; zero events is not a zero-risk proof.

Maker scenarios separate: pessimistic has no identified maker fill, evidence-supported depends on anonymous source trade chronology/queue assumptions, optimistic is an upper bound. Touch/quote is not a fill. Complementary matching THEORETICAL_ONLY; no double-counted liquidity. Conditional taker uses post-arrival depth within2s, not decision ask. Fees require captured explicit current zero schedule; otherwise blocked. No rebates/gas assumptions. Pending SELLs only against owned inventory. Unknown liquidation produces null PnL, plus zero-recovery stress and per-winner correlated losses.

Exit horizons5/10/30/60/300/900/3600seconds and settlement, full/partial exits, drawdown, profit factor, expectancy and day-cluster uncertainty need completed future positions. No closed-only profitability claim. Controls are frozen in EXP0015_PROTOCOL; matched randomized outcomes remain NOT IDENTIFIABLE until recorded compatible books exist. WEATHER is SIGNAL-ONLY; this is not a spurious head-to-head profitability ranking. Neither strategy has demonstrated a robust edge.

Read bounds:```json
{
  "truncated": false,
  "segment_limit_reached": false,
  "segments_available": 1,
  "segments_considered": 1,
  "errors": {},
  "limit": 100000,
  "cutoff": null,
  "semantics": "IMMUTABLE_EVENTS_ONLY_CHECKPOINT_NOT_HISTORICAL_EVIDENCE"
}
```
