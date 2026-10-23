# Milestone 1.5 verification

Verification date:2026-10-23 UTC /2026-10-24 Warsaw. Research-only; no accounts,
subscriptions or trading actions created. Existing weather-bot files/processes
were not changed. Repository initially clean on main at `bbc4d8f`.

## Checks actually run

- `uv sync --locked` baseline:35 packages; original pytest baseline46 PASS.
- `uv sync` after Astral:37 packages resolved/audited.
- `uv run pytest -q --basetemp data/test-pws-complete`: **118 passed in11.84s**.
- `uv run ruff check .`: all checks passed.
- `uv run ruff format --check .`:44 files already formatted.
- `uv run mypy`: no issues in19 source files.
- `git diff --check`: passed.
- Actual database `PRAGMA foreign_key_check`: no violations; provenance view12 rows.
- Original METAR smoke and shared METAR/PWS smoke succeeded.

Offline fixtures cover documented schemas, malformed/empty/missing values,
unknown units/timestamps, auth failure, rate limiting, timeout, geographic edges,
physical/temporal/spatial/solar checks, quantized negative rounding, chronological
calibration, all weighting methods, delayed/future/historical availability,
future selection/QC/calibration exclusion, restart, duplicate receipts, raw
preservation, immutable predictions including INSERT OR REPLACE, Parquet null
inference, provider isolation and shared stop behavior.

An integration regression exposed legacy UTC `Z` versus PWS `+00:00` serialization.
Reference queries now use SQL only to narrow candidates, then exact aware UTC
comparisons to preserve microsecond cutoffs. A reference one microsecond after
decision is explicitly ineligible. No legacy METAR storage rewrite was needed.

One initial combined-test failure was an incomplete synthetic AWC fixture
(missing icaoId), corrected to the verified schema. An initial report failure
exposed Polars' first100-row null inference; full-schema inference plus a105-row
regression fixed it. No known failing tests remain.

The restricted Windows sandbox denied uv canonicalization/local sockets and
stalled a SQLite test fixture. Approved host execution resolved those environment
limitations; the stalled task-owned pytest process was identified and stopped.
No other Python/weather processes were stopped. These were not labelled successful
test runs; the final results above are the observed host-environment results.

## Observed discovery

Documented anonymous APIs,20km radius, NOAA reference points; approx22:30 UTC:

| Airport | openSenseMap stations | with temperature | Sensor.Community temperature location groups |
|---|---:|---:|---:|
| EDDM |35|29|22|
| EHAM |53|38|36|
| EPWA |124|104|63|
| EGLL |9|9|7|

349 airport/provider station associations,308 temperature-bearing associations.
Do not sum these as independently verified physical sensors. No Netatmo or CWOP
counts were measured. Initial verification also obtained an actual empty response
for Sensor.Community's1km EDDM query; empty is not an adapter error.

Raw discovery evidence: `data/pws-smoke-raw/`; normalized SQLite:
`data/pws-smoke.sqlite3`. Raw provider bodies and public station names are ignored,
not included in the source commit. Source schemas/verification bodies are separately
retained under ignored `data/pws-verification/`.

## Actual bounded capture

Command: `premetar collect --pws --stations EDDM,EHAM --duration 45 --no-live
--database data/pws-smoke.sqlite3 --raw-path data/pws-smoke-raw`.

Run `20261023T223626919238Z-e34bb877`, completed normally. Eight nearest
non-indoor temperature-bearing station associations were manually chosen **only
for a smoke test**, not from validated rankings. The selection audit records this.

The shared run retained AWC EDDM/EHAM METAR, KNMI EHAM METAR and DWD EDDM10min;
136 original-pipeline observations and12 PWS observations/12 PWS arrivals were
stored. The database contained19 raw envelopes and zero provider errors after
discovery+capture. PWS readings: four openSenseMap (three missing temperatures,
one -145.38°C) and eight Sensor.Community values from the four selected location
groups. Sensor.Community server timestamps are retained separately; no fabricated
sensor observation/publication clocks.

The impossible value is preserved and flagged. The initial actual-data QC report
found four fresh station associations and no validated station scores. All349
remained UNVERIFIED because calibration/OOS/spatial evidence is insufficient.
Later report freshness naturally changes with wall time; this statement refers
to the initial post-capture report, not a promise that those readings remain fresh.

One actual prospective EHAM smoke forecast was persisted from already captured
eligible data for the next configured routine slot. It is an immutable research
estimate, with continuous capture coverage explicitly false. The generated JSON
is in `data/pws-prediction-smoke.json`; its result is pending in the report until
a matching reference is collected. This is not a measured information edge.
ID `b64b744e72b5451aa13c08887692c960`, created22:58:25.999406UTC,
target23:25UTC on23Oct, estimate11.8°C, integer12°C.

Reports were generated and re-read from the actual database:
`reports/pws/discovery_summary.md`, `quality_report.md`, `predictive_value.md`,
`quality.json` and CSV/Parquet inventory, rankings, ages, duplicate candidates and
prediction results. Conclusion: **INSUFFICIENT DATA**.

## Remaining limitations

Netatmo has a documented OAuth helper and an explicitly disabled runtime adapter;
no credential was used. Its public schema ambiguities, terms/quota/entitlement
verification remain blockers. openSenseMap's current controlling data-license
statement and both public providers' numeric quotas were not conclusively verified.
History support is bounded/schema-tested for openSenseMap; no live history coverage
claim is made. Sensor.Community archives and CWOP remain future work.

Metadata confidence, solar heating, spatial independence, lapse correction and
ranking weights are experimental. DWD's separate approximate0.1°C comparison does
not verify METAR sensor parity. Certified continuous receive coverage is not
implemented. EPWA/EGLL PWS discovery
works, while their METAR reference adapters remain outside this milestone's
existing EDDM/EHAM pipeline. There is no validated predictive improvement or lead.
