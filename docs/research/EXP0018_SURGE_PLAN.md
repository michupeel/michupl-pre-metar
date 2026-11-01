# EXP0018.1 — Surge Hunter plan

Baseline d59aff3; 2026-11-01. Research/shadow only; existing processes, source
databases, strategies and all historical EXP0018 audits preserved.

## Hypotheses / primary measurements

H1 independent surge, H2 own-trade effect, H3 complementary matching, H4 different
moments, H5 delayed/coarse reporting, H6 cancellation/replenishment/snapshot change,
H7 inconsistent depth, H8 combined explanations. No mechanism is preselected.
Measure independently detected surges, usable pre-entry coverage, connection gaps,
delayed wallet associations and matched controls. No profitability threshold or
trigger promotion from a single Wellington case. Market/day, not partial fills,
is the clustering unit. Unknown matching/submission clocks remain unknown.

## Existing capabilities and gaps

EXP0018 supplies frozen watchlists, independent raw-first TraderStore, immutable
BattleStore checkpoint/cursors, single-instance protection, bounded capture,
BookRing same-epoch reconstruction/BBO checks, strict UTC and source receipt
semantics. Existing stream reconnects too eagerly after short sessions; actual
disconnect cause not recorded beyond exception class. Snapshot ring180states can
truncate five minutes; top-five depth isn't full execution/queue evidence.
EXP0012 has verified event topics, V2 receipt decoder and conditional FIFO.
EXP0017 public captures preserve execution/detection separately. Existing static
dashboard can be extended without restarting ASGI. No new production dependencies.

## Minimal architecture / ownership

Existing public stream -> raw durable commit -> isolated SurgeMonitor subclass ->
typed book states + bounded rolling event buffer -> independent detector ->
append-only SURGE / feasibility / delayed association events -> offline reports
and additive static dashboard. Metadata/tokens frozen before entry, source wallet
feed consumed read-only. Capture directory data/research/exp0018_surge, distinct
lock/journal/raw DB; no reuse/overwrite of EXP0018 historical journals.

Qwen owns small state classifier, rolling buffer, detector, conservative liquidity
diagnostics, association helpers, tests and dashboard scaffold. Codex owns clocks,
exchange semantics, integration, forensic evidence joins and acceptance. Exact
function interfaces are supplied per task. <=2 attempts unless measurable progress.
Record generation tokens/time, review time, generated/accepted sizes and failures;
never rewrite the previous audit. Do not invent a direct-Codex timing baseline.

## Capture / budgets

Start4 frozen contracts/8tokens using existing metadata, no duplicate HTTP polling.
Only bounded live tests initially; target >=360seconds to exercise a five-minute
window, within existing3600second cap. Public socket lifecycle reused. Optional
stable-session backoff for this experiment only; default existing behavior preserved.
Expose close codes/elapsed times, CPU/peak memory and storage growth. No disconnect
cause claimed without evidence. No interpolation or implicit continuity from PONG.

Rolling buffer300s, <=12000 descriptive events globally / <=2000per token; capacity
loss explicitly flags incomplete windows. Raw journal remains authoritative. Existing
raw caps100MB/session500MBtotal/free1GB; derived journal50MBsegments500MBtotal.
Budget exhaustion stops, never deletes evidence. Long-running command may cycle
bounded sessions with explicit restart gaps; not enabled as a background task.
No production restart, source migration, order submission or credentials.

## Interfaces and temporal rules

Snapshots normalized to token, condition, outcome, received_at, exchange_timestamp,
connection_id, source_event_id, bids/asks and completeness/state. Bid/ask NULL when
side empty; zero depth only for a verified empty side. Absent snapshot is unknown.
Surge events compare same-session ordered states <=decision time, default price
jump0.10 in<=5s, depth change>=100shares and>=50%, spread change0.05. Definitions
are research thresholds, not optimized on Wellington. Initial/snapshot/gap events
cannot be treated as continuous price moves. Public prints differ from quotes.

Complementary YES bid -> theoretical NO cost1-bidYES only. Actual exchange/version,
matching proof, simultaneous depth, fees and arrival eligibility are required for
supported execution; absent inputs cannot create a fill. Unknown maker queue blocks.
Hypothetical candidate != order != fill != round-trip profit. Source trade time
has1second precision and may not equal matching-engine or order-submission time.

Independent surges are stored even without wallet activity. Associations use source
time and detection time separately; no-entry labels are provisional and censored
by delayed reporting. Controls require same station/day, comparable price/liquidity
and known timing metadata; missing confounders => INSUFFICIENT DATA.

## Forensic replay / acceptance

Freeze source max ID, extract Wellington exact YES/NO token events within±300s
through short kind/id reads; preserve raw hashes and original timestamps, snapshots,
public prints, wallet BUY/SELL and role evidence. Use existing V2 ABI decoder when
actual public transaction receipt is available; do not invent absent logs. Verify
official current protocol/exchange sources. Replay report must state what each
clock does/doesn't establish and evaluate all H1–H8.

Acceptance: deterministic replay, state/one-sided/missing/gap tests, detector/no-
lookahead tests, liquidity/fees/partial-fill/unknown-queue rejection, delayed-control
tests, budget/lock/restart tests, full pytest/Ruff/format/strictmypy, new SQLite
integrity checks and bounded public smoke with genuine counts (possibly no trades).
Dashboard distinguishes observed/source/detection/hypothetical and hides future
catalogs in replay. Rendered-browser verification attempted, failure reported.
Commit plan first; logical code/report commits; push branch, no merge/autostart.
