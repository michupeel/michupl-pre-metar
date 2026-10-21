# Milestone 1 verification — 2026-10-21 UTC

Environment: Windows11, Python3.12.10; uv.lock pins35packages including the dev
group. This repository has no imports or runtime dependencies on the parent lab.

## Actual live smoke (not fixtures)

Command:

```powershell
uv run premetar collect --stations EDDM,EHAM --duration 125 --no-live
```

Run `20261021T173308809928Z-64678398`,17:33:08.889618–17:35:14.386220UTC,
125.497seconds, graceful `duration_complete`.

| Check | Observed result |
|---|---:|
| HTTP responses preserved RAW | 9 |
| Normalized first source/run/row observations | 105 |
| Canonical full reports | 2 |
| Provider receipt events, including repeated polls | 9 |
| Collector/parser errors | 0 |
| Matched uncensored latency pairs | 0 |
| SHA256-verified raw envelopes | 9/9 |
| SQLite integrity / foreign keys | ok / ok |

The full evidence is local ignored `reports/smoke-evidence.json`, reproducible by:

```powershell
uv run python scripts/verify_capture.py --output reports/smoke-evidence.json
uv run premetar analyze
```

Snapshots below show first normalized receipts, not later identical poll receipts:

| Station/source | Event UTC | Upstream receipt UTC | Our first receive UTC | Celsius |
|---|---|---|---|---:|
| EDDM/AWC |17:20:00|17:26:05.376|17:33:09.604652|9|
| EHAM/AWC |17:25:00|17:28:06.989|17:33:09.604652|12|
| EDDM/DWD10min |16:50:00|NULL|17:33:09.619186|9.6|
| EHAM/KNMI METAR |17:25:00|17:22:42|17:33:09.383328|12|

All four are startup-censored. KNMI's upstream timestamp before nominal17:25 is
preserved as given, not proof of when its public endpoint first exposed the report.
All `source_publish_time` fields are NULL. DWD `report_time` is also NULL.

Example SQLite row (actual data, not invented):

```json
{"station_icao":"EDDM","source":"dwd_10min","product_type":"DWD_10MIN",
 "event_time":"2026-10-21T16:50:00Z","report_time":null,
 "source_publish_time":null,"source_receipt_time":null,
 "collector_request_start_time":"2026-10-21T17:33:08.994334Z",
 "collector_receive_time":"2026-10-21T17:33:09.619186Z",
 "temperature_c":9.6,"startup_censored":1,
 "raw_sha256":"1f33f39ae8cbe146d122f5f47f85080c714384c823589abfb426ae4c959e2384"}
```

Compact transcript of the final Rich view,17:35:14UTC:

```text
PRE-METAR LIVE
EDDM next17:50Z
  awc         event17:20:00 received17:35:10.685 temp9
  dwd_10min   event16:50:00 received17:35:10.454 temp9.6
EHAM next17:55Z
  knmi_metar  event17:25:00 received17:35:10.255 temp12
  awc         event17:25:00 received17:35:10.685 temp12
```

## Automated checks

`uv run pytest -q`: **46passed**. `uv run mypy`: no issues in8source files.
Ruff lint and format checks are required before the final commit.

Final checks also passed: Ruff lint, all23Python files formatted, and `uv build`
produced a source distribution and wheel. A second5-second live smoke after
the lock/clock correction completed gracefully with three HTTP200 captures and
no source/parser errors (`20261021T174148095999Z-e0e61533`). The long-run database
keeps both runs; counts above intentionally describe only the first frozen smoke.

The corrected bounded endpoint-verification script also returned HTTP200 for all
six targets: DWD station catalogue/ZIP/product PDF, KNMI latest METAR, AWC METAR
and AWC OpenAPI. Capture: `data/verification/20261021T174320195018Z/`.

Behavior covers Celsius positive/negative .5 boundaries/M00, UTC and month/year/
leap-year rollover, separate nominal/upstream clocks, both DWD ZIP naming variants,
raw-before-parser durability and hash, duplicate/cross-source receipts, immutable
first source receipt, parser failure with preserved raw, restart history, URL/header
redaction, wrong station/run/history rejection, next-target/no-lookahead matching,
unsorted input, request-order math, missing-clock race rejection, source failure
isolation, Retry-After parsing, disabled adapters and refusing an occupied lock.

## Clock and experimental limitations

The first smoke found Windows Time service unavailable (`w32tm` error0x80070426).
No service settings were changed; UTC offset is unknown and warning is retained.
Its `monotonic_ns` resolution was15.625ms. Version1.1 uses high-resolution monotonic
`perf_counter_ns`, with clock name and resolution recorded in new run manifests.
Old captures stay unchanged and never join clocks across runs.

This short startup-only dataset establishes operation, not prediction accuracy or
latency advantage. The report correctly says INSUFFICIENT DATA. DWD publication
lag can eliminate any advantage. EHAM candidate10min adapter and a second EDDM
full-report path remain M2 work. Optional METAR.ws/D-ATIS have not been connected.
