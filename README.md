# michupl-pre-metar

Prospective, raw-first research into temperature information **before our first
observed full METAR receipt**. We study information propagation:

sensor → local observation → national meteorological system → METAR/OPMET →
aggregators → market.

This is not conventional weather forecasting. We do not assume an information
edge exists. A reproducible negative result is useful; insufficient data is a
different result. There is no trading functionality.

## Continuous experiment (Milestone 1.6)

The prospective collector now supports all four airports, automatic UTC prediction
checkpoints, append-only outcome settlement, health reporting and a least-privilege
Windows logon task. It reuses the METAR/PWS collectors and immutable prediction
storage. Start from the project root:

~~~powershell
uv sync --locked
uv run premetar continuous start
uv run premetar continuous status
uv run premetar predictions list
uv run premetar continuous report
~~~

Use separate terminals for status/reporting; collection does not require a dashboard.
[Operation and exact PowerShell commands](docs/CONTINUOUS_OPERATION.md) cover
candidate selection, polling, graceful stop and autostart.
[Validation evidence](docs/CONTINUOUS_VALIDATION.md) distinguishes observed results
from implementation and remaining limitations. There is insufficient prospective
history to establish an information edge.

## Quick start

Python3.12+ and [uv](https://docs.astral.sh/uv/) are required. PowerShell:

```powershell
Set-Location D:\metar-execution-lab\michupl-pre-metar
uv sync --locked
uv run premetar collect --stations EDDM,EHAM
```

The default collector needs no API keys and runs until Ctrl+C. It polls three
public endpoints at60s intervals: AWC full METAR for EDDM/EHAM, DWD10min EDDM,
and direct KNMI full METAR for EHAM. No automatic burst is enabled. To keep a
separate source selection or bounded smoke run:

```powershell
uv run premetar collect --stations EDDM,EHAM --sources awc,dwd_10min,knmi_metar --poll-interval 60 --database data/premetar.sqlite3 --raw-path data/raw --duration 125 --no-live
uv run premetar status
uv run premetar status --as-json
uv run premetar sources
uv run premetar stations
uv run premetar analyze
```

On this workstation, if the default uv cache is denied, set
`$env:UV_CACHE_DIR="$PWD/.uv-cache"` before invoking uv. The dependency lock was
resolved and tested with Python3.12.10 on Windows11. Native certificate trust is
used without disabling HTTPS verification.

## What is implemented

- Independent async source loops with timeouts, backoff, Retry-After, source
  isolation, graceful shutdown and Rich terminal display.
- Immutable fsynced byte-exact RAW envelopes before parsing, SHA256 and per-run
  protocol/configuration/clock manifest. All blocking disk/parser/SQLite work uses
  one dedicated thread, keeping the event loop available for other sources.
- SQLite WAL schema for runs, raw payloads, observations, canonical reports,
  provider receipts, health and errors. Restart appends a new run and preserves data.
- Typed UTC model with nullable event/report/publish/upstream/request/receive clocks;
  monotonic clocks only compare inside one run. No invented publication timestamps.
- METAR/SPECI parser retaining original TAC, AUTO, COR, negative zero, dewpoint and
  report identity. WMO rounding uses exact Decimal ties toward warmer, including M00.
- Basic same-station next-routine-report matching, accuracy by lead bucket,
  source receive race, explicit exclusions and Markdown/JSON/CSV/Parquet output.

## Evidence and limitations

Read [verified source register](docs/sources.md), [experiment](docs/experiment.md),
[architecture](docs/architecture.md), [verification](docs/verification.md) and
[research log](RESEARCH_LOG.md). The source register links primary documentation,
license terms, endpoint verification and clock meanings.

DWD10-minute sampling does **not** imply10-minute publication: its `now` product
is documented as updating hourly/less than1h. It can arrive too late. `TT_10` is
not assumed equal to airport METAR temperature or final market settlement.

EHAM has two full-report dissemination paths; EDDM only AWC in M1. They may share
upstream observations. “First seen” always means our configured channels, never
global first publication. Polling can introduce up to roughly a polling interval
plus request/cache delay; request start is not a publication lower bound.

First successful snapshots, collection gaps, historical-event-only data and
cross-run clocks are excluded from latency evidence. Historical observation time
alone never proves availability. Latest-only polling may miss intervening SPECI.

KNMI10min OpenData/notifications require configuration and format verification;
they are explicitly disabled in M1. METAR.ws is M2; D-ATIS, EPWA and EGLL are M3.
The optional interfaces and `.env.example` do not pretend these adapters work.
No key from an existing bot is read or reused. This program currently does not
load .env; optional env names are reserved for later adapters.

M2 also covers full stable-correct prediction, source-calibrated probabilities,
confidence intervals and held-out validation. M1 outputs INSUFFICIENT DATA, not
an unsupported strong edge conclusion.

## Data and recovery

```text
src/premetar/       models, parsers, sources, collector, store, analysis, CLI, protocol
tests/             synthetic behavioral fixtures (not observed edge evidence)
docs/              source registry, architecture, experiment, verification, review
scripts/           bounded public endpoint verification
data/raw/          ignored immutable source/YYYY/MM/DD/*.json; manifests/
data/premetar.sqlite3   ignored normalized DB + WAL
reports/           ignored generated latest.md/json + pairs/source-race CSV/Parquet
```

Raw envelopes store body Base64, SHA256, safe request URL, selected HTTP headers,
UTC request start/end/receive and monotonic receive. Repeated METAR responses
retain every receipt; unchanged DWD rows preserve the first normalized receipt,
with every HTTP body still retained. Revised DWD rows are separate observations.
Raw files are authoritative even after parser failure; automated DB rebuild is
on the M2 roadmap. Back up the raw directory and use SQLite's backup API for a
consistent DB copy while collection is running.

One process owns one database. After a crash, first confirm the process is dead,
then remove only that database's `.lock` and restart. Never remove a live lock.
Status separates HTTP transport freshness from age of the newest observation.
Persistent errors are saved with safe class names and linked RAW, without tokens.

## Development

```powershell
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

Code is MIT licensed. Source data retains DWD/KNMI/NOAA terms and attribution;
the code license does not relicense third-party data. Data, credentials, generated
reports and virtual environments are ignored by Git.

## Milestone 1.5 — open PWS discovery and QC

The PWS subsystem discovers openSenseMap and Sensor.Community stations near
EDDM, EHAM, EPWA and EGLL, retains original raw responses, separates stations
from sensors and arrivals, and runs deterministic QC. Discovery is an inventory,
not a claim that each record is a useful or independent weather station.
Netatmo is explicitly blocked pending credential/runtime/terms verification;
its optional OAuth refresh helper is implemented without logging tokens.

PowerShell, from this repository:

```powershell
$env:UV_CACHE_DIR="$PWD/.uv-cache"
uv sync --locked
uv run premetar pws sources
uv run premetar pws discover --all-airports --radius 20
uv run premetar pws stations --airport EHAM
uv run premetar pws qc --airport EHAM
uv run premetar pws rank --airport EHAM
# Auto-selection needs sufficient prior OOS evidence; new stations remain UNVERIFIED.
uv run premetar pws select --airport EHAM --top 10
# For initial monitoring, copy a real ID from stations and give an audit reason:
uv run premetar pws select --airport EHAM --station-id "PROVIDER:REAL_ID" --reason "Initial prospective research monitoring"
uv run premetar pws collect --airport EHAM --duration 300
uv run premetar pws analyze --airport EHAM
uv run premetar pws report --all-airports
# To exclude a station:
uv run premetar pws select --airport EHAM --station-id "PROVIDER:REAL_ID" --exclude --reason "Manual review: unsuitable siting"
```

`PROVIDER:REAL_ID` is a placeholder, not a discovered station. No automatic
TRUSTED promotion occurs. Manual monitoring selection does not bypass physical,
freshness, availability-time or indoor/mobile guards in the estimator.

For concurrent METAR and PWS observations, use one process/database owner:

```powershell
uv run premetar collect --pws --stations EDDM,EHAM --pws-airports EDDM,EHAM,EPWA,EGLL --duration 3600
```

The existing METAR adapters remain EDDM/EHAM; this milestone does not invent
EPWA/EGLL reference coverage. PWS-alone and combined modes are bounded (default
PWS-only 300s; maximum 86400s). Re-run to append to the same database. Discovery
is periodic, not per poll. Polling floors are 300s per station, one request/s per
provider, slower for slower observed updates; no burst mode. Retry-After may
defer an entire provider. An in-flight request/retry may finish after the duration
cutoff so raw writes can drain. Ctrl+C stops the shared tasks gracefully.

The existing `.lock` policy applies to every mutating PWS command. Do not start
separate collectors against the same database. Run selection/report/prediction
commands between bounded collection runs. Read-only `premetar status` remains
available during collection. For a separate smoke database, pass
`--database data/pws-smoke.sqlite3 --raw-path data/pws-smoke-raw` consistently.

To create a prediction **now**, use an aware future target timestamp, ideally
the next verified nominal routine report slot. Available readings must already
be in the DB; an arbitrary future timestamp does not create a new METAR schedule:

```powershell
$target=uv run python -c "from premetar.model import utc_now; from premetar.sources import STATIONS,next_report; print(next_report(STATIONS['EHAM'], utc_now()).strftime('%Y-%m-%dT%H:%M:%SZ'))"
uv run premetar pws predict $target --airport EHAM --method equal_weights
```

Methods: `equal_weights`, `inverse_distance`, `inverse_historical_error`,
`quality_weighted`. The last two require earlier evaluation evidence. Insufficient
data fails explicitly. Predictions are immutable; retrospective analysis never
inserts a historical forecast. Recorded UTC receive differences alone do not
certify information lead; capture coverage is not yet certified.

Configuration is a JSON file accepted as `--config` by PWS commands or
`--pws-config` by combined collection. Copy the packaged
`src/premetar/pws/airports.json`, retaining its airport list, and add overrides:

```json
{
  "poll_seconds": 600,
  "discovery_seconds": 86400,
  "radii_km": [1, 3, 5, 10, 20],
  "qc": {
    "stale_seconds": 1800,
    "min_samples": 100,
    "min_evaluation_days": 7,
    "calibration_method": "median",
    "calibration_window": 100
  }
}
```

The snippet shows override keys; an actual config must also contain `airports`.
Environment variables do not silently change weather settings. Local Qwen is a
development-only tool and is never called by collectors.

Reports under `reports/pws/` include Markdown, full `quality.json`, and
CSV/Parquet station inventory, rankings, provider ages, duplicate candidates,
separate approximate DWD reference comparisons and prediction outcomes.
Missing evidence is NULL/UNVERIFIED, not a fabricated score.
Read [source verification](docs/PWS_DATA_SOURCES.md),
[methodology and limitations](docs/PWS_METHODOLOGY.md),
[local Qwen audit](docs/LOCAL_QWEN_WORKFLOW.md), and
[milestone verification](docs/PWS_VERIFICATION.md).


### Strict timestamps and daily sensor inspection (1.6.1)

Run `uv run premetar pws today --airport EPWA --date 2026-10-24 --limit 50` for
actual local-day readings, inventory, measurement buckets, METAR comparisons and
CSV/Markdown exports. Omit `--date` for the airport's current local date. Run
`uv run premetar pws timestamp-audit` for quarantine/exclusion counts and
`uv run premetar continuous clock-audit` for a read-only Windows/NTP check.
[Strict timestamp policy and interpretation](docs/STRICT_TIMESTAMPS.md) describes
the300s limit, Sensor.Community exclusion and immutable historical evidence.
