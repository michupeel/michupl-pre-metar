# EXP0018 — Entry trigger reconstruction

Frozen implementation plan, 2026-10-31. Baseline: `6d2c9e8` on
`research/hightemptation-metar-timing`. Research/shadow only.

## Hypothesis and acceptance

Pre-execution NO/YES price trajectories, liquidity and the actual receipt of
official observations may distinguish HighTempTation entries from comparable
non-entry opportunities. Nominal METAR proximity alone cannot identify a trigger;
executions may also be resting orders. No order placement clock is available.

Primary measurement: fraction of genuine prospective NO entries with fresh paired
YES/NO evidence covering the preceding 300/60/10 seconds. Secondary measurements:
causal price changes, depth imbalance, detection delay, matched-control coverage,
conditional exits. Missing evidence remains NULL, never a synthetic zero/fill.
Any trigger discovery is exploratory; no rule is promoted on this same sample.

## Existing architecture and boundaries

- `trader_monitor.py` captures public wallet trades and market metadata; bounded
  market discovery prioritizes recent wallet instruments (256 tokens). This can
  censor first-entry books; it does also discover general weather markets.
- `trader_stream.py` preserves full BOOK, WS_DELTA, wallet-unattributed WS_TRADE
  and connection health in `data/trader/monitor.sqlite3`. Delta is not itself a
  certified full-depth snapshot. No documented globally continuous sequence.
- EXP0017 independently tails that database. Its ring keeps 20 top-five snapshots
  per token, excluding WS_DELTA. Useful timing baseline, incomplete trigger evidence.
- `BattleStore` supplies isolated immutable hash-chain journals, crash-safe cursors,
  segmentation, free-space guards. Reuse it and the existing OS-held instance lock.
- Weather, forecast, FIFO inventory and market identity utilities are reused.
  Source databases are read-only. No production schema or prediction changes.
- Static dashboard extension can be loaded without restarting the ASGI server.

## Minimal candidate/data flow

Existing source event journal -> bounded read-only ID tail -> validated paired
book ring -> causal feature extraction -> immutable entry/coverage/control records
in `data/research/exp0018/live` -> bounded reports/static dashboard catalog.
Do not add external polling. Cold start is censored; missing watchlist coverage is
reported. Restart clears book certification and records a gap. Only subsequently
received snapshots can restore current coverage. Event IDs deduplicate ingestion.
Source execution, source first detection, sidecar capture and exchange book clocks
remain distinct. Feature inputs must have original receipts <= their cutoff.
Execution timestamps have one-second precision, so pre-execution ambiguity remains.

Initial implementation deliberately uses recorded full snapshots; a WS_DELTA
invalidates current depth until a new full snapshot. It does not claim a complete
reconstructed order book or queue position. Existing original delta evidence is
retained in the source journal. Wider independent discovery/subscription or delta
reconstruction can be proposed after measuring this conservative coverage.

## Budgets and safety

Tail <=1000 source rows/cycle; no RAW bodies decoded. Poll >=1s. Ring <=64 tokens,
300s, <=180 snapshots/token, top-five levels. Samples evicted by caps are explicitly
partial coverage. Pending entries <=100, controls <=20/cycle, market cache <=500.
Journal 50MiB segments, 500MiB total, 1GiB free-space floor; stop at budget, no
automatic research deletion. Rolling logs, finite default run (60s, max3600s).
No unbounded persistence/task changes without explicit user approval. Existing
weather/trader/EXP0017/dashboard processes remain untouched. D1 task is Ready,
not Running: report it, do not restart it. No wallet/auth/order code is introduced.

## Analysis and controls

Persist features at actual source receipt cutoffs, not an oracle's later book.
Pre-execution and pre-detection windows are separate. Controls are selected from
already known comparable markets with similar NO price, spread/depth and context;
they remain PENDING_DELAYED_ATTRIBUTION until a predeclared lag horizon. A finite
horizon cannot prove no wallet trade: labels remain operational/censored. Market
and settlement-day clusters are mandatory; overlapping windows aren't independent.
Conditional FIFO reuse cannot establish unknown opening inventory or maker queues.
Unknown fees/depth block economic fills. No frozen trigger or profitability claim
until prospective evidence supports it. Public prints do not reveal order creation.

## Verification and decision

Tests: UTC/DST, future/malformed clocks, bounded ring, gap/epoch/delta invalidation,
causal features and missing windows, paired identity, restart/deduplication,
read-only source integrity, controls with delayed attribution, journal budgets,
dashboard empty/replay states. Run full pytest, Ruff lint/format and strict mypy.
Bounded real local-feed smoke; report genuine entries only (possibly zero).
Inspect rendered dashboard. Compare baseline/candidate coverage on matched source
receipts; do not call retrospective analysis prospective signal performance.
Commit plan first, then reviewed local patches, tests and reports. Push without
force; no merge to main. Persistent activation is a final approval boundary.

## Delegation

Existing local MCP worker/research only. Verified model ID:
`unsloth/Qwen3.6-35B-A3B-GGUF`. No wrapper/profile/sampling/server changes.
Local tool's existing profile controls inference; effective sampler values may
remain unverified. Probe generation returned zero reasoning tokens. Each patch
is reviewed and tested by Codex. Limit <=3 attempts, stop early on repeated failure.
Task ledger and actual timing/token/acceptance audit are required. Missing review
timing is NULL; no hypothetical cloud-token savings. Initial analysis probe missed
same-zone DST subtraction; rejected review conclusion, retain actual evidence.

## Bounded comparison addendum (before promotion, 2026-10-31)

The first immutable cutoff 7437602 yielded 12 entries and zero fresh paired
pre-execution full snapshots in the preceding 1,500,000 IDs. There were 616,711
delta packets. This measured limitation justifies an opt-in research-only
`--experimental-deltas` variant. Keep the same cutoff for comparison.
Seed from the recorded full WS book and same connection only; apply absolute
level updates, require consistency with the packet's reported BBO, invalidate
on malformed data, epoch/time regression, cap or mismatch. Keep <=4096 levels
per token and existing ring limits. No sequence/hash continuity or executable
depth is certified. Retained subscription identities survive unchanged subscription
refreshes; removed tokens and reconnects lose state. Default remains snapshots.
Official current docs confirm the schema; aggregate-size interpretation remains
an explicitly checked reconstruction assumption, not a provider latency guarantee.
This doesn't change production subscriptions or data. No trigger is promoted.

## Paired capture addendum after source coverage diagnosis

Eleven of12 entries lack ANY earlier NO full snapshot in the original source
slice; one has observed one-sided books, so NULLmid must not be counted as no
capture. Implement a separate bounded public socket using existing `stream_market`
and `TraderStore`, without editing either production module. Freeze16 eligible
paired weather contracts from already captured metadata before subscribing; no
new HTTP discovery polling. Own source IDs carry capture database/session identity.
No source collector is reconfigured. Bound raw capture100MB/run500MBtotal/free1GB;
stop on budget and preserve evidence. Persistent activation still needs approval.
Observed61s smoke had five abrupt disconnects, so continuous readiness remains
DEGRADED. The small immediate-PING diagnostic did not establish a fix; do not
change the stable shared stream adapter or pretend continuity exists.
