# EXP0017 prospective local-feed observer

The sidecar never connects to public HTTP/WebSocket services and never modifies
the existing trader or weather databases. It does not restart existing processes,
place orders, or calculate new forecasts. All source SQLite connections are
`mode=ro` plus `query_only`; ID-tail reads process at most 1000 rows per cycle.
Large unrelated raw response bodies are not read into the sidecar.

```powershell
cd D:\metar-execution-lab\michupl-pre-metar
uv run python -m premetar.research.entry_timing_monitor status
# Bounded operational test, only when no instance exists:
uv run python -m premetar.research.entry_timing_monitor watch --duration 30
# Continuous independent observer:
uv run python -m premetar.research.entry_timing_monitor watch
# Graceful stop of this sidecar only:
New-Item -ItemType File data/research/exp0017/live/stop.request
```

An OS-held single-instance lock prevents duplicate sidecars; dead-owner recovery
uses the existing conservative project mechanism. Remove only this experiment's
`stop.request` before an intentional new run. No autostart task is created here.
The parent deployment may launch the sidecar with hidden `Start-Process` and
separate stdout/stderr files. The source collectors are never stopped for it.

On first startup, the current source maximum ID is checkpointed as
`CENSORED_STARTUP`; older trades are not relabeled live. Restarts resume an atomic
source cursor with immutable journal evidence. Original execution clock, original
trader first-detection clock, and actual sidecar capture clock remain distinct.
Only wallet-matched weather NO BUYs labeled `PROSPECTIVE_POLL` enter the live
entry cohort. Backfills and gap-censored trades retain explicit censored records.

Metadata comes from newly observed MARKET records, bound to exact condition and
NO token. No city-to-airport guess is made. Historical initialization does not
prepopulate the cache; initial entries may correctly have unknown metadata.
The metadata cache is limited to 500 conditions. Full recorded book snapshots
are reduced to top-five levels, at most 20 states per token and 100 tokens,
covering at most five minutes of original receipt history. Snapshot age beyond
10 seconds is stale. A subscription change removes only unsubscribed tokens;
gaps, disconnections, malformed messages or connection-epoch changes clear the
cache. These snapshots do
not certify continuous depth, queue placement, available fills, or cancellations.

Pre-execution book evidence must have an original recorded receipt no later than
the source execution clock. Before-detection evidence has its own cutoff. A
later snapshot is never called the earlier book. Weather context uses only an
exact referenced station and uncensored routine reports already locally received
before source execution, within a bounded last-3000-row source window. Missing
PWS/forecast context is explicitly UNKNOWN rather than backfilled availability.

Controls are 30-second candidate buckets with actual sampling time, watchlist
coverage and pending no-entry classification. They are **not a complete matched
all-market counterfactual**: delayed trades and selected subscriptions remain
confounders. Public market trade messages do not identify wallets. Follow-ups
request 1/5/30/60/300-second horizons but the 10-second polling cadence may sample
late; actual delay is stored and never backdated or passed off as the exact book.

`ROLE_EVIDENCE` and `ENDPOINT_RECEIPT` source events produce separate immutable
joins by exact trade ID. Each retains original source evidence receipt and actual
sidecar evidence capture time. Later maker/taker evidence never rewrites the
original entry's UNKNOWN role. API-attributed taker evidence is not promoted to
chain verification. Endpoint receipts never overwrite the original detection.
Evidence caches are bounded to 2000 trade IDs, at most five endpoints per trade;
all appended join evidence remains in the independent journal.

Persistence is separate under `data/research/exp0017/live` using existing
`BattleStore` immutable hash-chain events and atomic checkpoints. Segments rotate
at 50 MB/day; total budget is 500 MB with a 1 GB free-disk floor. Limits stop the
sidecar without deleting evidence. Diagnostic logs rotate at 2 MB plus two copies.
In-memory cursor state is discarded on failed database commits. Heartbeats are
checkpoint state; `status` reports process liveness separately. Long-duration
uptime and comprehensive source coverage require actual later observation.

## Observed bounded smoke, 29 October 2026

The separate observer ran for 30 seconds from 20:09:17 to 20:09:47 UTC and a
15-second restart from 20:11:15 to 20:11:30 UTC. Both exited with code 0 and
released the lock. Source cursor advanced from 4,031,548 to 4,032,323; actual new
book snapshots were recorded in control candidates. No genuine monitored NO BUY
occurred during these windows. The journal contains one censored startup, three
control candidates and two STOP events; `PRAGMA integrity_check` returned `ok`.

The first smoke exposed provider depth returned in ascending bid order. Before
continuous deployment, v1.1 explicitly sorts bids descending and asks ascending
before retaining the best five levels. Invalid/nonfinite depth is rejected.
The prototype journal remains intact; a `BUFFER_VERSION_UPGRADE` event records
the change and only its cached in-memory checkpoint book buffer is reset. No
trade or fill was inferred from those prototype control snapshots. The 23 focused
tests, Ruff lint/format and strict module mypy passed after this correction.
These bounded smokes are not evidence of long-duration uptime or trader behavior.


## Installed operation and display (30 October)

Dedicated current-user logon task `MichuplPreMetar-EntryTiming-v1` uses absolute project pythonw, Limited/Interactive, IgnoreNew, restart60seconds x3, no password. Preview/install/status/start/remove are exposed by `scripts/entry-timing-service.ps1`; install/remove require `-Apply` and exact ownership. The read-only sidecar was started29Oct and its cursor/11genuineentries survived controlled own-process upgrades30Oct. Weather/trader/dashboard processes were not restarted. This is not a tested reboot or fault-free multi-day soak.

`entry_timing_live.json` is an ignored atomic bounded display projection updated at most once a minute after journal commit. The immutable journal remains authoritative. Legacy display rows require exact pre-existing endpoint trade/time evidence; missing as-of data stays UNKNOWN. Windows status reads lock metadata after its locked byte. Historical summary revisionv1.1 has its own actual30Oct publication clock.

```powershell
.\scripts\entry-timing-service.ps1 -Action status
uv run python -m premetar.research.entry_timing_monitor status
# Graceful stop of this observer only:
Set-Content -LiteralPath data/research/exp0017/live/stop.request -Value stop
# After status confirms STOPPED, remove stop.request before starting again.
```
