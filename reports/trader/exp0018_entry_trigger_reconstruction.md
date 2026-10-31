# EXP0018 — HighTempTation entry trigger reconstruction

Generated 2026-10-31T22:23:56.677446+00:00. RETROSPECTIVE_REPLAY_OF_PROSPECTIVE_CAPTURES.
Frozen source IDs (5937602, 7437602]; receipts 2026-10-30T23:07:30.216628+00:00 to 2026-10-31T22:03:33.150905+00:00.
Fingerprint identifies immutable ID boundaries, not a full database content hash. Reads close after <=1000 rows.

## Coverage and measured results

```json
{
  "entries": 12,
  "paired_pre_execution": 1,
  "paired_two_sided_pre_execution": 0,
  "no_pre_execution": 0,
  "no_pre_snapshot": 1,
  "complete_300s_no_windows": 0,
  "controls": 0,
  "censored_buys": 0,
  "median_detection_delay_seconds": 2.5248565,
  "conditional_closed_lots": 11,
  "net_profit_identifiable": false,
  "frozen_trigger": "INSUFFICIENT_PROSPECTIVE_PAIRED_BOOK_HISTORY"
}
```

## Real entries (all qualifying rows in CSV)

| Execution UTC | Station | Price | NO pre-mid | YES pre-mid | Detection delay s |
|---|---|---:|---:|---:|---:|
|2026-10-31T03:54:07+00:00|None|0.9405926708|None|None|2.821|
|2026-10-31T04:29:45+00:00|None|0.963602128|None|None|1.524|
|2026-10-31T06:04:39+00:00|None|0.956387373|None|None|2.767|
|2026-10-31T07:01:55+00:00|None|0.98|None|None|2.818|
|2026-10-31T08:21:16+00:00|LLBG|0.98|None|None|2.332|
|2026-10-31T08:58:33+00:00|NZWN|0.9434998556|None|None|2.149|
|2026-10-31T09:31:19+00:00|None|0.98|None|None|1.856|
|2026-10-31T10:53:27+00:00|None|0.98|None|None|2.419|
|2026-10-31T10:58:31+00:00|None|0.9716782247|None|None|2.630|
|2026-10-31T12:57:52+00:00|FACT|0.9354613043|None|None|3.954|
|2026-10-31T16:01:57+00:00|None|0.9732138284|None|None|2.130|
|2026-10-31T20:31:37+00:00|None|0.98|None|None|3.919|

## Independent raw-book coverage

11/12 entries have no earlier NO full snapshot anywhere in this frozen source interval. This source check bypasses our ring and midpoint calculations.

Observed repricing case: station NZWN, trade `43b37defd524bd2febae0e0c68e7149c4bdfae7ced3f99a0529f2fd1590326f2`; source trade timestamp 2026-10-31T08:58:33+00:00, first detection 2026-10-31T08:58:35.148661+00:00, BUY price 0.9434998556 and size 207.78.
Largest adjacent recorded NO bid increase 0.8900 received 2026-10-31T08:58:29.863130+00:00; latest eligible bid 0.99, ask None. A missing ask means no recorded direct BUY liquidity at that snapshot, not a zero price.
This movement precedes the Data API source timestamp but NOT necessarily the actual matching-engine fill or trader decision. It could be a consequence of that very trade before later reporting/settlement. No independent official publication receipt is available here to distinguish the hypotheses. Later API taker evidence does not reveal order placement time.

## Interpretation

No trigger is promoted. Timing near a nominal METAR is not proof of reacting to its publication. Sparse/missing pre-entry books cannot distinguish momentum, resting limits and weather signals. Correctly time-aligned nulls are more informative than invented triggers.
An empty ask is an observed one-sided book, not an absent timestamp or missing capture. Midpoint-based coverage is reported separately from fresh snapshot/paired coverage. Check raw_book_coverage.json to distinguish truly absent pre-entry packets from one-sided books and reconstruction restrictions.

Controls match exact station/day plus price ±0.02, spread ±0.02, depth ratio 0.5–2 and <=10s old; candidate metadata/books must be known by detection. Matching currently does NOT balance verified publication context, forecast state, market age or time-to-settlement: control efficacy is incomplete, not a causal strategy test. No-entry remains censored by detection lag. Market/day clusters and overlapping entries are not independent trials.

Conditional FIFO reuses EXP0012; opening inventory, non-trade history before the cutoff, fees and gas can be unknown. Gross matches are not full portfolio net PnL. A 0.99 SELL print is not our executable maker/taker exit. No shadow fills were generated.

Source weather context is only last 3000 weather rows, uncensored receipts <= execution; forecasts/PWS/publication clocks not available remain UNKNOWN. Other stations aren't mapped from city guesses. Nearest nominal times are current configured schedules, not verified historical publication times.

## Method and scope

NO BUYs at 0.90–0.99 with original PROSPECTIVE_POLL receipt evidence. Startup/backfill/future-clock rows censored. Pre-execution cutoff is strictly before the lower boundary of the source execution second. A separate detection view uses original wallet first receipt. Retrospective replay was created now; no prediction is backdated. No production processes, policies or records changed.

## Minimal next experiment

The separate bounded paired-capture command now freezes 16 markets before future entries and reuses the public stream with raw-first storage. It does not change existing subscriptions. Persistent activation still requires approval; reconnect stability must be investigated first. EXP0019 should freeze a small trigger family only on future independent settlement days, include non-entry controls and reject unknown execution costs/depth.

## Limitations

- Recorded bounded watchlist, not all market opportunities
- Snapshots are sparse and reset on delta/gap; continuous depth unverified
- Execution clocks have one-second precision; placement time unknown
- Weather query is bounded, exact configured station required
- No frozen prospective trigger, matched outcome efficacy not identified
- Unknown inventory, costs and queues prevent copy-profit claims
- Source retention is append-only; replay cutoff is by immutable ID, not historical publication
