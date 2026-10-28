# EXP-0013 operation and evidence boundaries

The new research sidecar is separate from both existing Windows tasks. Neither
task/configuration is changed. It reads existing databases with mode=ro/query_only
and never imports another bot. No credentials, private keys or order submissions.

Run from the repository root (the research-only adapters also reuse audited
scripts/research helpers, so a wheel installed without repository sources is not
the supported launch mode). Python/uv/dependencies are the existing environment.

```powershell
Set-Location D:\metar-execution-lab\michupl-pre-metar
uv run python -m premetar.research.forecast_monitor watch --duration 86400
uv run python -m premetar.research.forecast_monitor status
```

One OS-held lock in data/research/exp0013/observer.lock prevents duplicate sidecars.
It does not share or alter either production lock. Crashed locks are recovered
only if the recorded owner/PID is verified dead. The manual background launch
uses Start-Process -WindowStyle Hidden with this environment's absolute python
path, absolute working directory and separate stdout/stderr files under logs/.
No Task Scheduler autostart is installed. Maximum duration24h, mainDB+WAL cap2GB;
either ends this bounded research capture. Long-duration validation is pending.

Gracefully stop ONLY this sidecar within its5second diagnostics cycle:

```powershell
New-Item -ItemType File data/research/exp0013/stop.request
```

The stop marker intentionally prevents subsequent starts until removed. Do not
touch the weather/trader tasks. Ctrl+C is also usable in a foreground terminal.
Never delete observation databases or raw captures to free space automatically.

## Storage, clocks and freshness

Append-only separate data/research/exp0013/observations.sqlite3 uses the existing
immutable event store and short WAL transactions. WS_RAW precedes normalization;
text is losslessly zlib/base64 encoded with original-byte SHA256. Delta projection
JSON is not duplicated; replay uses these original bytes and receipt order.
Monotonic receive clocks are scoped to each stream invocation. UTC offset remains
UNKNOWN; microsecond serialization is not certified timing accuracy.

Invalid known-token depth affects only its identified condition/tokens. Unknown
wire identities/reconnects invalidate all relevant depth. A rejected token may
be unsubscribed briefly then resubscribed, no more than once per60seconds, to
request a fresh documented full snapshot. This does not synthesize depth, refresh
PONG clocks, erase gaps or certify sequenced delivery. All failures remain raw.

One hourly supported SQLite backup uses a replaceable separate analysis cache;
full historical CPU work runs outside the asyncio loop. CAL2 cache parameters
can use only prior captured references; each signal stores exact references,
offset and history availability. Initial independent weather/report snapshots
are immutable and hashed. No unsafe live WAL file-only copying is used.

## Reproducible report

First create separate consistent snapshots with SQLite backup API, then:

```powershell
uv run python -m scripts.research.forecast_integrated_report `
  --weather-snapshot data/research/exp0013/<weather-snapshot.sqlite3> `
  --research-db data/research/exp0013/<research-snapshot.sqlite3> `
  --output reports/research
Invoke-Item reports/research/epwa_forecast_pws_metar_orderbook.md
```

The report records both SHA256 values and its exact research cutoff. Weather
history is explicitly retrospective; v1.1 signal/outcome evidence is prospective.
The90second v1 prototype revealed a startup pairing defect, preserved via a
separate EXCLUSION event. Unsupported v1 signals are excluded without rewriting
any history. Valid original forecast/book captures retain their evidence value.

London settlement contracts referencing EGLC are not weather-matched to EGLL.
No listed exact match is invented for an absent airport. Existing monitor's
bounded discovered universe, instrument cap and two-day horizon are disclosed.
Contract text is preserved; integer METAR subset maxima do not certify the
contract's precise qualifying reference or final settlement. Complementary
1−YESbid is an indicative matching route, not a guaranteed executable fill.
Unknown costs, rules or complete contemporaneous depth block economic claims.

## Qwen

One health diagnosis28October found localhost8888 unreachable. No model generation
or delegated tokens were fabricated; work continued independently. New runtime
does not depend on Qwen. See reports/dev/exp0013_qwen_audit.json.
