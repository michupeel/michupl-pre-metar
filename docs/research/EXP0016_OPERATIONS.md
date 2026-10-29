# EXP0016 — isolated D-1 research operations

Independent public-data process, no production weather/trader/battle writes or
order APIs. Existing cohorts, predictions, paper accounts and tasks unchanged.
Frozen baseline d1b93aa; protocol/config in EXP0016_PROTOCOL.md and
configs/experiments/epwa-d1-v1.json. Default calibration promotion is NULL;
all three strategy variants remain SIGNAL-ONLY / CALIBRATION_PENDING.
The pure decision/exit trigger code does not claim a running filled-trade ledger.
An audited promotion plus arrival/execution integration must be independently
verified before simulated entries can be enabled. No trading edge is claimed.

```powershell
Set-Location D:\metar-execution-lab\michupl-pre-metar
uv run python -m premetar.research.d1_monitor status
uv run python -m premetar.research.d1_monitor report
# Start only when this experiment's monitor.lock is not held:
uv run python -m premetar.research.d1_monitor watch
# Exact historical as-of (explicit UTC offset required):
uv run python -m premetar.research.d1_monitor report --at '2026-10-29T16:00:00Z'
```

Only this process's graceful stop:
```powershell
Set-Content .\data\research\epwa_d1\stop.request stop
# Wait for its monitor.lock to disappear. To deliberately resume:
Remove-Item -LiteralPath .\data\research\epwa_d1\stop.request
uv run python -m premetar.research.d1_monitor watch
```

No new Windows task/autostart is installed. Hidden background process continues
after terminal closure, subject to machine uptime; reboot requires manual start.
Never start a duplicate. Journal and checkpoints live only under
data/research/epwa_d1; reused BattleStore WAL/FULL transactions, immutable hash
chain,100MB/dailyUTC segments,2GB cap,1GB free disk floor, no automatic deletion.
No arbitrary24hour stop. Storage limit/error is a visible stop, not data removal.
Stdout/stderr are redirected to own logs; normal event/health evidence is in the
bounded journal, not unbounded verbose text logs.

Public requests justified: one5-model batch/30min for independently requested
families and2 Gamma event lookups/15min for actual D0/D1 EPWA contracts.
Raw HTTP response chunks are durable BEFORE JSON normalization, including errors.
Empty event result is recorded, never fabricated markets. Requests have30s timeout;
periodic failure is isolated, no aggressive retries. Existing EXP0013, trader and
battle raw frames are tailed via bounded read-only connections (150ms VM budget).
Startup skips historical book frames; no offline receipt is recast as live.
Only tokens without a live shared subscription use the reused public WS client;
existing sources/processes are not reconfigured. Unknown/malformed frames break
continuity. Full-depth recovery resubscription is bounded to once/minute/token.
Freshness5s uses actual depth updates, never PONG. Decision-depth quotes are
conditional and NOT fills. Complementary paths/maker queues remain uncertified.

Snapshot/candidate evidence recorded every30s includes BOTH YES/NO depth and
original metadata, receipt timestamps, date, exact/tail labels, fees/constraints,
probability absence and all rejection reasons. Source clocks precede decision;
no forecast initialization/publication is invented. Current as-of API visibly
marks books older than5s stale. D0 snapshots retained; TOMORROW panel filters to
the next local date at the cursor. Prior-day snapshots cannot substitute for
tomorrow. DST uses calendar midnights. Reports disclose bounded read truncation.

Endpoint GET /api/tomorrow?at=ISO is loopback-only, same-origin and read-only,
shares dashboard replay cursor; future/naive timestamps rejected. Loading a new
ASGI route requires restarting ONLY the read-only dashboard process, not collectors.
Generated reports: reports/research/exp0016/{summary.json,forecasts.csv,
markets.csv,candidates.csv,exp0016_d1_forecast_mispricing.md}. Exact cutoff permits
deterministic regeneration while retained segments cover that date.

## Actual historical audit —29October2026

data/research/epwa_calibration/archive.sqlite3 contains14 ARCHIVED_RUN events:
7ICON Global +7ICON EU,00UTC21–27Oct, downloaded28Oct16:53–17:01UTC. All are
APPROXIMATE_REPLAY: availability_time/publication_time NULL, init+6h assumed.
Prior hourly evaluation94 independent targets/5days is NOT final settlement Tmax.
Existing audit reports final_settlement_targets=0 and verified_reference_days=0.
This is zero audited D-1+final settlement pairs, not an absence of archives.

[Single Runs](https://open-meteo.com/en/docs/single-runs-api) identifies run
initialization, not public availability. [Historical Forecast](https://open-meteo.com/en/docs/historical-forecast-api)
stitches runs; [Previous Runs](https://open-meteo.com/en/docs/previous-runs-api)
fixes lead relative to valid time, not necessarily D-1 local issuance windows.
[Model Updates](https://open-meteo.com/en/docs/model-updates) provides last-run
metadata, not an original historical receipt ledger. More downloads cannot repair
those missing clocks or certify final official resolution targets.

Current captured EPWA clauses explicitly use AWC qualifying routine T-remark
temperature, body fallback, SPECI exclusion, local day, ties warmer, corrections
cutoff and Wunderground/no-data fallback. Parsed rule identity is distinct from
certifying a historical final target. [Gamma public discovery](https://gamma-api.polymarket.com/docs)
and [public market stream](https://docs.polymarket.com/market-data/realtime-data)
are used without authentication. The existing legacy-compatible public WS adapter
was verified against actual frames; no authenticated stream or order endpoint.
