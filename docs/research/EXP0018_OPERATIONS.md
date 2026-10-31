# EXP0018 — operational boundary and commands

Research only. Existing weather, trader, EXP0017 and dashboard processes are not
stopped, restarted or reconfigured. D1 task is Ready, not Running; not restarted.
No new Windows task installed. The user attachment explicitly requires:
“A production activation or persistent collector deployment requires explicit approval.”

## Bounded modes

```powershell
cd D:\metar-execution-lab\michupl-pre-metar
# Reuse existing local feed, no additional public connection; finite by default:
uv run python -m premetar.research.entry_reconstruction watch --duration 60
uv run python -m premetar.research.entry_reconstruction status
# Separate frozen paired-book capture (one public socket; no extra HTTP polling):
uv run python -m premetar.research.entry_reconstruction_capture --duration 60
# Conservative, smaller operational comparison (same frozen ranking):
uv run python -m premetar.research.entry_reconstruction_capture --duration 30 --max-contracts 4
# Reproduce the reported historical ID slice (NOT live trigger performance):
uv run python scripts/research/hightemptation_entry_reconstruction.py `
  --maximum-id 7437602 --max-rows 1500000 --experimental-deltas --publish
```

No unbounded flag exists. Duration 1–3600 seconds is enforced. An OS-held lock
at `data/research/exp0018/live/monitor.lock` prevents duplicate default instances.
Completed bounded runs stop normally; checkpoint status is not proof of PID
liveness. On restart, book certification resets; newly connected epochs cannot
inherit old depth. New paired sessions start wallet tails at the current ID and
label startup coverage censored rather than replaying old trades as live.

## Frozen capture policy

`EXP0018-FROZEN-PAIRS-NO090099-HASH-v1` reads at most 5000 recent original MARKET
records through the existing `(kind,id)` index. Requires captured explicit station
reference, active/open/acceptingOrders metadata, metadata age <=600s, and discovery
NO mark in [0.90,0.99]. The mark is only a discovery filter, never executable price.
Eligible conditions are ranked by SHA256(policy+condition), first16 retained;
exact YES/NO pairs (32 tokens) are frozen in immutable RUN and FROZEN_WATCHLIST
records before subscribing. No current/future trader entry selects the watchlist.
This subset is not all weather markets, and may miss the trader's next instrument.
It includes active Tmax/Tmin and may include other settlement dates, explicitly
research capture only; it cannot authorize the parent lab's paper entry policy.

Public stream reuse preserves original WS_RAW before parsing. Original local UTC,
run-scoped monotonic elapsed, exchange timestamps, connection ID and event IDs are
retained. Public messages lack wallet attribution/order creation. Data API source
timestamps aren't independently established matching-engine clocks. A pre-source-
timestamp price jump could be the effect of the target trade, not its cause.

## Storage and interpretation

Own `BattleStore` hash-chain journal: 50MB segments, 500MB per configured directory,
1GB free floor, no deletion. Own public raw-book SQLite files: bounded sessions,
100MB active /500MB total capture budget plus final stop metadata. Existing trader
DB was ~25.3GB and drive free space ~42.5GB at initial inspection: we add no duplicate
market HTTP polling or unrestricted retention. Public WS library queue is bounded
at256 frames and4MiB/frame. All source DB connections are read-only and short-lived.
Raw preservation and journal projection are separate commits; a crash may leave
raw without derived state, never manufacture a missing raw capture. Failed derived
commits restore their durable checkpoint before final failure recording.

Default reconstruction uses full snapshots. `--experimental-deltas` optionally
applies absolute level updates to same-epoch full seeds, <=4096 levels/token,
requires reported BBO consistency and rejects clock regression/malformed data.
Current official schema:
https://docs.polymarket.com/api-reference/wss/market
and https://docs.polymarket.com/market-data/realtime-data .
Aggregate-level replacement is a tested reconstruction interpretation; public
hashes/sequences do not certify end-to-end continuity or queue priority. Restarts,
removed subscriptions, malformed messages and reconnects invalidate coverage.

Missing midpoint is not missing book: one-sided bids/asks stay visible, empty
side depth is0, absent snapshot depth isNULL. Historical replay and prospective
capture are labeled separately. Controls remain pending/censored by detection lag;
they don't yet match all publication/forecast/time-to-settlement confounders.
No independent trigger or shadow fills promoted; fees/copy profitability unknown.

## Observed smoke and limitations

31Oct22:13:37–22:14:39UTC,61.032s:16 contracts/32 tokens,209 WS_RAW,
192 BOOK,203 WS_DELTA,203 packets accepted with seeded BBO consistency. No new
wallet entry occurred. Five ConnectionClosedError reconnects occurred; capture
is DEGRADED, not validated for persistent operation. A subsequent two-token test
had one18s connection survive and one immediate-PING connection close after~6.8s;
no evidence supports claiming a heartbeat fix. No stable existing process changed.

A subsequent smaller4contract/8token run31.032s used one connection,8BOOK/6delta
and zero reconnects/new wallet entries. Last512 callback duration buffer max16ms,
p95reported0ms on the coarse Windows monotonic timer:0means below timer resolution,
NOT zero latency. This short comparison does not establish that cohort size caused
disconnects or that4contracts is a validated permanent fix. `--max-contracts1..32`
is recorded in the immutable manifest; default16 remains unchanged.

New journal and capture SQLite integrity checks PASS; weather DB quick_check PASS.
The 25GB trader DB was not put through a long integrity scan/read transaction.
Browser automation failed at runtime initialization (MXC invalid I: volume / trusted
Node process exit), so no screenshot or visual-pass claim is made. Local HTTP,
JS syntax and synthetic DOM/replay checks are separate from rendered-browser QA.

Dashboard http://127.0.0.1:8766/ loads the additive EXP0018 static panel on refresh;
it does not require ASGI restart. A published audit is hidden before publication
in replay and explicitly stale after120s; it is not a running-observer heartbeat.

Pending before permanent activation: investigate repeated WS disconnects, obtain
approval for separate persistent observer/watchlist lifecycle, verify rendered UI,
then gather independent future entry/control windows before freezing a trigger.
