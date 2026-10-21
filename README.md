# michupl-pre-metar

Prospective, raw-first research into temperature information **before our first
observed full METAR receipt**. We study information propagation:

sensor → local observation → national meteorological system → METAR/OPMET →
aggregators → market.

This is not conventional weather forecasting. We do not assume an information
edge exists. A reproducible negative result is useful; insufficient data is a
different result. There is no trading functionality.

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
