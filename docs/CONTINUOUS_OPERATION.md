# Continuous observation and validation — Milestone 1.6

## Operation (PowerShell)

Run from this repository, using its existing environment:

~~~powershell
Set-Location D:\metar-execution-lab\michupl-pre-metar
$env:UV_CACHE_DIR="$PWD/.uv-cache"
uv sync --locked
uv run premetar continuous start
# Bounded operational test, in place of the unbounded command:
uv run premetar continuous start --duration 660
uv run premetar continuous status
uv run premetar continuous stations
uv run premetar predictions list --limit 20
uv run premetar continuous report
uv run premetar continuous stop
# Manual settlement only while the collector is stopped:
uv run premetar predictions settle
~~~

The legacy collect/analyze/status and pws commands remain available. The separate
continuous command preserves their existing CLI interfaces. Reports are read-only
and do not require stopping the collector. Do not start a second collector over
the same database. A second start cannot cancel an existing stop request.

Configuration: configs/experiments/continuous-v1.json. Change airport subsets,
provider polling policies, checkpoints, QC thresholds and calibration window there
before beginning a new experiment. The collector freezes canonical configuration
and exact candidate identities. A changed configuration needs a new experiment ID
and a separate database. Every run also freezes its configuration,
protocol and clock diagnostic in the existing immutable manifest infrastructure.

## Existing components reused

Official HTTP source loops, AWC/KNMI/DWD parsers, raw envelopes, hashes, first
receipt records, SQLite WAL/FULL transactions and the serialized disk executor
remain the collection foundation. The continuous extension uses the existing
PWS adapters, station/sensor/discovery/arrival tables, selection audit, deterministic
QC, calibration and immutable pws_predictions table. No additional METAR collector
or prediction storage system was created. The runtime uses no GPU or LLM.

New continuous tables hold versioned configuration, a frozen DISCOVERY_CANDIDATE
cohort, checkpoint attempts, a resume cursor, append-only settlement versions,
poll events and health snapshots. Indexes support matching predictions to nominal
targets without rescanning observation history for every prediction. Unsupported
schema versions stop startup.

Sources: AWC for four airports; direct KNMI METAR for EHAM; DWD 10-minute EDDM
observations; openSenseMap and Sensor.Community PWS. Netatmo remains disabled
pending verified credentials. No paid service is enabled. Source limitations and
licenses remain in PWS_DATA_SOURCES.md and sources.md.

## Scheduling and failure isolation

One process owns a database and runs independent official/PWS tasks. Each provider
has a separate lifecycle and cooldown. Provider errors retain safe error classes;
authentication/redirect failures disable requests, and HTTP429 honors Retry-After.
A provider outage does not terminate other sources. Fatal database/disk/job errors
stop the process for the Task Scheduler's bounded restart policy.

Defaults: official polling >=60 seconds (AWC requests a2-hour window for delayed/SPECI/COR recovery, with startup censoring), daily discovery, up to four stations per
provider per airport, PWS polling >=300 seconds, adaptive maximum1800 seconds,
HTTP timeout20 seconds, at most3 attempts, request spacing>=1 second, no burst.
Provider-specific limits can be made more conservative in polling_limits.
Transport response frequency never counts as observation frequency.

Adaptive intervals use at most512 recent observations from one stable sensor per
station, deduplicated by actual source clock. Startup and restart poll immediately;
subsequent cadence is inferred from prior sensor/server-ingest clocks. Empty data
backs off; repeated readings retain raw arrivals but not additional unique samples.
Provider cooldown persists for the lifetime of its transport, with no indefinite
authentication retries. Daily discovery eligibility is restored from persisted
discovery records; failed empty discoveries retry no faster than that interval.

Cold candidates require temperature sensors, exclude declared indoor/mobile
stations and honor audited exclusions. The policy balances providers and prefers
fresh discovery metadata, outdoor exposure and metadata completeness, with distance
and compass quadrant diversity. Unknown exposure remains unknown. Candidate status
does not imply thermometer accuracy, independence or predictive value. Existing
cohorts remain frozen; later algorithm changes do not silently replace them.

The OS-held file lock rejects live/unknown owners. A lock left by this project's
verified dead process can be recovered after a crash; unknown legacy locks require
inspection. SQLite transactions remain atomic; raw bytes are fsynced before parse.
Unexpected exits preserve prior receives and forecasts. On restart the first new
official snapshot is censored, rather than relabelled as first public availability.

## Prospective predictions

Configured UTC routine minutes: EDDM20/50, EHAM25/55, EPWA00/30, EGLL20/50.
These were checked against a genuine 24-hour AWC response on2026-10-24.
They are experimental schedule assumptions, not permanent guarantees. Off-schedule
METAR and SPECI are retained but do not settle routine targets. Unexpected/missing
reports remain visible rather than being reassigned to a convenient target.

Checkpoints: T-10m, T-5m, T-3m, T-2m, T-1m. Optional30s is not enabled by default.
A checkpoint must execute within5 seconds of its due time. The actual input cutoff
and completion timestamp are recorded; forecasts are never backdated. Startup
elapsed checkpoints and downtime misses have separate reasons. The cursor restores
up to7 days of individual missed slots after interruption; longer downtime is not
expanded into unlimited synthetic scheduler records.

Models:
- previous_metar: most recent eligible routine integer report.
- temperature_persistence: explicit alias of that persistence baseline, not an
  independent source of skill.
- simple_recent_metar_trend: two prior routine reports, <=1-hour gap, linear trend.
- nearest: nearest eligible selected PWS.
- median: median of eligible, conservatively independent PWS contributions.
- inverse_distance: existing inverse distance estimator.
- quality_weighted: existing score weighting; unavailable without sufficient history.

The baseline reference must be <=2 hours old. All models exclude unavailable,
future-measured and otherwise ineligible inputs. A target already received blocks
new forecasts even if its nominal observation time is still in the future.
The live KNMI early receipt demonstrated why this guard matters.

Existing corrections use only past labels. QC/calibration refresh runs hourly
after the initial5-minute collection period. The completion publication timestamp,
input cutoff, discovery/quality/calibration IDs and observation IDs are retained.
A score cannot become TRUSTED from a handful of data. Minimum predictive scoring
requirements remain100 out-of-sample samples across7 days; calibration requires
20 prior pairs within the configured100-pair window.

EXP-A PRE_OBSERVATION is enabled. EXP-B post-observation/pre-receipt signal
generation is deferred and disabled; it is never mixed into these forecast scores.
Known nominal-future reports do not authorize post-receipt forecasts.

## Settlement and interpretation

Routine matching uses exact aware UTC event times, airport and report type.
Repeated settlement is idempotent. The full TAC/COR/AUTO identity and provider
receipts survive. Every correction gets a new append-only settlement, with initial
and latest views exported separately; original forecasts never change. Conflicting
initial routine temperatures invalidate prospective evaluation for that target.
Missing targets remain pending, and delayed targets are retried. The current
reference search window is7 days; very late older reports require a deliberate
offline extension, not automatic reassignment.

Scores use initial settlements by default. Integer exact/within1C accuracy,
integer MAE/RMSE/bias and continuous interval-distance error are distinct. METAR
integers are quantized intervals, not exact continuous reference temperatures.
Matched baseline CSV comparisons require the same airport/target/checkpoint.

Day-block bootstrap intervals resample complete UTC days (2000 deterministic
replicates), only with >=100 matched targets across>=7 days. They are descriptive;
dependence across days and station selection on the same dataset remain limitations.
No robust edge or confirmatory significance is claimed by this milestone.

Lead is our earliest recorded receive minus actual forecast creation, never
nominal time minus creation. Same-run monotonic differences are also retained when
possible; monotonic clocks are never compared across restarts. UTC offset remains
unverified when clock diagnostics cannot establish it. Startup/gap-censored
references are excluded from the uncensored lead summary. A positive difference
does not prove global publication lead or a trading opportunity.

Stability is evaluated after settlement through later *observed* checkpoints.
Missing checkpoints provide no evidence of stability. First correct, last incorrect,
first stable correct, revision count and observed stability span are exported.
These ex-post summaries cannot change earlier signals.

## Health, logs and storage

continuous status shows persistent run/PID/heartbeat, next UTC report/countdown,
selected and usable stations, genuine measurement clocks and separately labelled
server-ingest clocks, latest reference reports, pending forecasts, provider
states, errors and storage. A stale heartbeat is not a running collector.

Rotating project logs: logs/continuous/collector.log and errors.log,
2MB/file plus3 backups. No raw payload/credential logging. Raw files remain in the
existing append-only storage. Health refreshes each minute; raw directory size
is scanned hourly, with its scan time retained, to avoid repeated full-tree walks.
The default warning threshold is10GB; research data is never automatically deleted.
The storage estimate may lag by an hour. No retention deletion policy is enabled.

On this workstation Windows Time Service was stopped during validation; absolute
clock offset was not verified and no time settings were changed.

## Windows logon autostart

~~~powershell
uv run premetar service install --dry-run
uv run premetar service install --no-dry-run
uv run premetar service status
# Start the registered task now (do not also start a foreground collector):
Start-ScheduledTask -TaskName MichuplPreMetar-Continuous-v1
# Graceful stop; wait for the task to finish before starting another instance:
uv run premetar continuous stop
uv run premetar service remove
~~~

The task uses this repo's absolute .venv/Scripts/pythonw.exe, absolute config,
explicit working directory, current-user InteractiveToken and LeastPrivilege.
IgnoreNew prevents overlapping task instances; the database OS lock also protects
manual launches. RestartOnFailure is1 minute, at most3 retries; no execution time
limit. Install previews first, refuses unrelated same-name actions, and verifies
saved executable/config/working directory, SID, privilege and restart settings.
Removal refuses an unrelated task and does not forcibly terminate a collector.
Logs work without a console.

This is an installed **logon fallback**, not a pre-login boot service. Automatic
collection resumes when this Windows user logs in; pre-login startup would need
a separately authorized account/security arrangement. No password is stored,
administrator privilege requested, or unrelated task changed. Keep the workstation
awake and connected for continuous observations; no power policy was modified.

## Validation and open work

See CONTINUOUS_VALIDATION.md for actual run/verification evidence. Unit fixtures
are synthetic and run without unrestricted external access. The live smoke/soak
is a separate genuine network capture. Long-duration reliability, calibrated
station skill, source independence and a useful information edge remain unverified.


## Timestamp hotfix 1.6.1

The existing task, database, raw storage and cohort remain in place. The strict
policy is separately frozen in each run and rejects unverified measurement clocks
and age>300s. Sensor.Community continues raw capture but cannot supply analytical
measurements. EHAM may therefore have zero live-eligible PWS; this is a data
limitation, not permission to use its months-old readings or ingestion proxies.
Use `uv run premetar pws today --airport EPWA` for on-demand read-only inspection
and `uv run premetar pws timestamp-audit` for current exclusions.
Clock audit is on-demand and read-only; its cached evidence expires after1hour.
No daily-report task was installed. See STRICT_TIMESTAMPS.md and
TIMESTAMP_HOTFIX_VALIDATION.md for evidence and deployment details.
