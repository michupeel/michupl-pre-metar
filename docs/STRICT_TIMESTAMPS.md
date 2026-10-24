# Strict measurement-time policy — Milestone 1.6.1

The separate `configs/timestamp-policy-v1.json` is frozen in every new run manifest.
It supplements the unchanged continuous-v1 experiment configuration. The default
maximum age is 300 seconds at first receipt **and** at inference time. There is no
future-measurement tolerance: a negative age is rejected, never made absolute.
All eligible clocks are aware UTC. Missing/naive/malformed time, unknown semantics,
server ingestion/publication substitutes, non-finite/implausible temperatures,
unknown units and missing identities block analytical eligibility. Historical raw
evidence is retained; current freshness is distinct from historical validity.

## Provider evidence

Rechecked 2026-10-24 against [openSenseMap API documentation](https://docs.opensensemap.org/)
and the [Sensor.Community official API wiki](https://github.com/opendata-stuttgart/meta/wiki/EN-APIs).
openSenseMap documents UTC RFC3339 clocks and `lastMeasurement.createdAt` as the
measurement timestamp. This verifies the API contract, not the hardware clock.
Its upload API also permits omitted createdAt; absent device-clock attestation is
a residual limitation. We do not claim independent sensor-clock certification.

Sensor.Community's upload example contains no measurement-time field and explicitly
says the server supplies the timestamp. Its read timestamp is retained only as
PROVIDER_INGEST_TIME. No trustworthy independent measurement clock was found in
the audited v1 response. It is excluded from prediction, calibration, quality
samples and accuracy summaries by default, including forged rows labelled otherwise.
Raw capture continues under the existing conservative polling/storage policy.

## Audit and immutable history

Additive timestamp schema v1 stores policy definitions, first-receipt observation
assessments and append-only prediction exclusions. Original normalized/raw payloads,
forecasts and settlements are not rewritten. Legacy openSenseMap rows are assessed
against the documented API contract; arbitrary providers do not gain that inference.
Calibration/QC snapshots predating the strict policy cannot influence new forecasts.
Old forecasts with ineligible inputs or unverified parameter provenance are excluded
from evaluation even when their old settlement remains stored.

Every writer uses the existing single database worker. The migration is rehearsed on
a SQLite-supported backup, then applied only during a graceful stop of the existing
task. No unsafe live WAL file copy, data deletion or second collector is used.

## Reference receipt barrier

The existing first-seen receipt records remain authoritative across providers and
restarts. Final prediction insertion checks the target's earliest METAR receipt,
regardless of whether nominal time lies in the future. A conservative in-process
barrier blocks scheduling while a buffered reference response awaits durable raw
capture and parsing. SPECI remains separate; corrections append rather than replace.
Post-observation forecasts remain disabled. No historical prediction is backdated.

## Clock interpretation

`uv run premetar continuous clock-audit` issues read-only service/status/source/
configuration/timezone queries and independent five-sample NTP stripcharts to
time.windows.com and time.cloudflare.com. It never changes services or settings.
Two sufficiently consistent comparisons are required; cached evidence expires
after one hour. VERIFIED/FAILED refer to a one-second research offset budget;
automatic synchronization is reported separately and may remain UNKNOWN.
Stopped W32Time alone does not prove an incorrect clock. No stored timestamps are
offset-corrected. Python microseconds do not establish clock accuracy.

## Daily local database report

```powershell
Set-Location D:\metar-execution-lab\michupl-pre-metar
uv run premetar pws today --airport EPWA --date 2026-10-24 --limit 50
uv run premetar pws today --airport EPWA
uv run premetar pws today --airport EHAM --bucket-minutes 10
uv run premetar pws timestamp-audit
Invoke-Item .\reports\daily\EPWA_2026-10-24.md
```

Reports open the existing DB in read-only mode and use one consistent WAL snapshot.
Local-day boundaries are consecutive calendar midnights in each airport's IANA
zone, including 23/25-hour DST days. EPWA 2026-10-24 is UTC 2026-10-23 22:00 through
2026-10-24 22:00, exclusive. Complete CSVs accompany the limited terminal timeline.
All currently selected sensors remain visible, including quarantined/stale sensors.
Valid day summaries require freshness at receipt; live eligibility also checks age now.
Buckets never forward-fill. Multiple sensors per station contribute one station
median, with one conservative vote per 200m cluster; physical independence remains
UNVERIFIED. Min/max and dispersion retain actual within-bucket sensor differences.
Measurement cadence uses distinct measurement clocks, not HTTP poll clocks.

METAR agreement uses rounding intervals and nearest measurement within five minutes,
one pair per sensor/cycle. These are exploratory meteorological comparisons, not
prospective forecasts. Availability reconstructions separate pre-observation and
post-observation/pre-receipt phases and never create live predictions retrospectively.
Actual immutable forecasts and exclusions are exported separately. Small sample and
single-day station rankings describe operations, never TRUSTED predictive skill.
No plotting framework was added; CSVs are complete and the chart is optional.
