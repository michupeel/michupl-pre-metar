# EPWA Weather Intelligence Dashboard — Milestone 2.0

Local, Polish, read-only weather and market display. It does not submit orders,
write collector databases, start collectors, or change selection/prediction rules.

## Start

```powershell
Set-Location D:\metar-execution-lab\michupl-pre-metar
uv sync --locked
uv run premetar dashboard --port 8766
Start-Process 'http://127.0.0.1:8766/'
```

The default port is8765. On this workstation it was already occupied by the
parent lab's dashboard, so this dashboard uses8766. Never stop an unknown listener
to free a port. `scripts/start-dashboard.ps1 -Port 8766` is an equivalent launcher.
Only loopback is exposed; no scheduled task or firewall change is installed.

## Data and chronology

`dashboard/reader.py` opens existing weather, EXP0013 and trader SQLite databases
with `mode=ro` and `query_only`. Queries have row/time budgets, and connections are
closed promptly. No long live read transaction, database migration or external
weather polling occurs in the web process. Expensive reads run outside the HTTP
event loop; one locked cache retains at most four days for15seconds. SSE pulses
every5seconds invalidate the browser view; they are not new sensor observations.
Truncation/query errors are disclosed, not interpreted as absence of data.

`service.py` applies strict measurement provenance, first-receipt and event-time
eligibility. Hover/click inspection excludes information received after the cursor,
including forecasts, market metadata, quotes and calibration publication. A PWS
correction must also have existed when that reading was received. Selection is
reconstructed from recorded selection events, rather than applying today's cohort
to older observations. Unknown clock synchronization remains UNKNOWN.

Local-day boundaries use Europe/Warsaw calendar midnights. Replay supports1×/5×/20×;
25October2026 has25 distinct hourly rows and offsets distinguish the repeated02h.
Graphs break across long gaps; no missing temperatures become zero. Forecast hourly
point Tmax is labeled as such; it is not an observed continuous daily maximum.

Markets require verified EPWA/date/token identity. Both binary tokens have separate
bid/ask, quantities, spread and recorded last trade. Quotes older than10seconds,
invalid/crossed prices and unknown mapping are flagged. An ask with positive size
is required before displayed buy liquidity can be marked executable; this remains
a quote, not a guaranteed fill. No midpoint is labeled as a traded price.

The observed routine integer maximum and the maximum of qualifying official reports
are distinct. The captured current Warsaw rule prefers precise hourly T remarks,
otherwise body integers; SPECI is excluded. Neither our incomplete daily capture nor
the current maximum is certified as the final settlement value. See the separate
[calibration audit](EPWA_FORECAST_CALIBRATION.md).

## Source verification and limits

Weathercloud links in the request were reversed. Visible public profiles checked
28October2026 identify:

* [d1542158444](https://app.weathercloud.net/d1542158444#profile): Vevor,
  observer Ichipek, CCL Electronics P100, Raszyn.
* [d0865035381](https://app.weathercloud.net/d0865035381#profile): Lawart.pl,
  observer MC_cichy, Bresser7-in-1.

These are verified profile identities, not an authorized machine-readable data API.
No readings are scraped or invented. A future authorized adapter should reuse the
existing PWSProvider interface and raw-first timestamp policy.

ECharts6.0.0 is vendored with Apache license, notice, exact upstream URLs and hashes
in `static/vendor-manifest.json`; no CDN runtime dependency. FastAPI/uvicorn versions
are pinned by uv.lock. Primary references: [FastAPI responses](https://fastapi.tiangolo.com/advanced/custom-response/),
[Apache ECharts](https://echarts.apache.org/en/download.html).

The original EXP0013 observer reached its pre-existing2GB bound and stopped itself.
To resume measurement without deleting data, an explicit validated `--database`
segment option was added to that same observer. All segments share its existing
single-instance lock. `segments.json` lists up to four additional sibling SQLite
files for the read-only dashboard. The resumed segment retains the24h/2GB bounds;
this is not an indefinitely supervised collector. Weather/trader tasks are untouched.

## Verification artifacts

`reports/dashboard/` contains screenshots of live cards, market history, hour detail
and an as-of case where a10:04 reading received at10:06 is correctly absent at10:05.
Synthetic tests cover empty databases, read-only WAL access, budgets, DST, receipt
filtering, mapping, stale/empty quotes, calibration cutoffs and segment path safety.
Screenshots and measurements are bounded verification, not a long-duration soak.
