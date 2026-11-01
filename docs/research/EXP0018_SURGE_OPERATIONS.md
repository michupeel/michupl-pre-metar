# EXP0018.1 operations and evidence boundaries

Research only. Existing weather, trader, EXP0017 and dashboard processes were not restarted. No orders, wallet authentication or inference at runtime. No persistent task installed. The new recorder has completed bounded tests and is currently stopped; multi-day stability remains unverified.

## PowerShell

Run from `D:\metar-execution-lab\michupl-pre-metar`:

```powershell
uv run python -m premetar.research.surge_hunter --duration 360 --contracts 4
uv run python -m premetar.research.surge_hunter --duration 3500 --contracts 4 --continuous
uv run python -m scripts.research.wellington_surge
uv run python -m scripts.research.surge_report
```

The continuous foreground command starts successive finite sessions; each gap and new selection is explicit, not continuous historical coverage. Ctrl+C checkpoints and releases the isolated lock. An error stops continuation. Never run a second instance or reuse the existing collector's output directory. Four contracts / eight tokens is the initial budget; eight / sixteen was tested separately. Universe selection is frozen at session start using existing market metadata, never future wallet activity. A new socket is necessary for this isolated raw-first capture and session instrumentation; existing source events are reused for wallet attribution and original forensic replay. It is not a replacement subscription for the healthy trader process.

## Limits

Rolling receive-ordered history: 300 seconds, 12000 events globally, 2000 per token, 256 tokens; cap loss is disclosed. Raw capture: 100 MB per session, 500 MB aggregate. Derived journal: 500 MB; minimum free disk 1 GB. Limits stop capture rather than delete research evidence. Inspect usage before resuming. Reports read a bounded journal tail (100000 events) and at most 30 capture files; read metadata discloses truncation. Long-run aggregate reporting beyond these bounds needs a separate incremental audit, not an assertion of complete history.

Only same-token/session comparable states trigger. Missing initial snapshots, reconnect gaps, stale quotes and inconsistent BBO prevent executable interpretations. One-sided and genuinely empty books remain useful evidence. No sequence guarantee is invented. PONG proves connection activity, not fresh depth. Fees and exact arrival liquidity are unknown unless independently evidenced; no paper fills or profit are fabricated. Arrival reviews use first recorded paired states at/after each modeled latency and retain unknown outcomes.

## Observed validation

Four bounded sessions lasted approximately 361, 361, 31 and 16 seconds. Zero reconnects; no wallet BUY in the watched universe. Four liquidity-threshold records represent two mirrored packets in two market/day clusters, not four independent signals. Zero supported fills, zero qualifying matched controls, zero actual complete pre-entry windows. Six minutes of recording without a trader entry is not proof of usable history before an entry. Public-book freshness expires after ten seconds without a qualifying update.

Earlier reconnect cause is UNKNOWN. Confirmed retry amplifier: resetting backoff on handshake prevented exponential growth for short sessions. Only this experiment opts into a 60-second stability reset; existing defaults unchanged. Synthetic reconnect test verifies 3/6/12 seconds. Record close-frame diagnostics on future failures.

Dashboard http://127.0.0.1:8766/ adds static read-only evidence; publication gates prevent later reports leaking into an earlier as-of panel. Explicit retrospective mode unlocks historical forensics. HTTP and DOM tests passed. Actual browser rendering/screenshot could not be verified: the computer-use runtime exits on an invalid I: MXC volume. Do not treat DOM tests as visual inspection.

## Reproducibility and primary sources

Wellington source IDs and snapshot cutoff are embedded in the replay and its report. Original transaction hashes link raw public WS prints to canonical Polygon receipts; RPC response envelopes retain backfill receipt time. On-chain evidence was retrieved after the event, never presented as real-time wallet knowledge. The observed fixture is public evidence, separately labeled from synthetic tests.

Verified protocol: https://docs.polymarket.com/api-reference/wss/market
Verified ExchangeV2 matching implementation: https://github.com/Polymarket/ctf-exchange-v2/blob/main/src/exchange/mixins/Trading.sol
Public receipt source: https://polygon-bor-rpc.publicnode.com

BUY/BUY mint is not the Solidity enum named COMPLEMENTARY (direct opposite-side matching). Block timestamps and API seconds do not disclose order submission time. Original audit histories and source databases remain unchanged.


## Final existing-process check (2026-11-01 01:10 UTC)

Weather PID11236, trader11748, dashboard32732 and entry-timing36160 remained present with their original start times. Four matching tasks remained RUNNING; D1 and the M3 recovery task were READY, not asserted running. Weather heartbeat01:10:35UTC; KNMI/DWD successful requests01:10:32, AWC01:10:07, zero consecutive errors. Latest inserted official observation receipt01:02:49UTC. Latest inserted PWS observation in continuous-v1.sqlite3 was October27 12:49:23UTC: fresh PWS ingestion is NOT confirmed, despite the live weather process. This is an existing limitation, outside this surge-only change; no selection or collector changes were made. Do not equate process existence or successful empty polling with fresh sensor measurements. Free D: space approximately41.54GB.
