# Milestone 1.6 — operational validation

Snapshot: **2026-10-24T12:56:46Z**. Values below are actual observations from this
workstation, not fixture values. Collection continues and subsequent counts change.

## Readiness

| Capability | Result |
|---|---|
| Continuous collector | READY — running under the registered task |
| Automatic prospective predictions | READY |
| Append-only settlement | READY |
| Windows autostart | INSTALLED — current-user logon fallback |
| Saved task configuration | VERIFIED through XML and native Windows Limited privilege |
| SQLite integrity | PASS; integrity_check=ok, no foreign-key violations |
| Clock synchronization | UNKNOWN; Windows Time Service was stopped, offset unverified |
| Long-duration reliability / useful edge | INSUFFICIENT DATA |

The active run at the snapshot was20261024T124804274488Z-52ba48f0, PID19420.
Its frozen algorithm source hashes matched the current committed core files.
Measured process working set was67,694,592bytes (about64.6MiB), with8.50 cumulative
CPU seconds. This is one resource snapshot, not a benchmark or CPU-utilization claim.

## Genuine live capture and soak

The first bounded run began12:12:54Z and ended12:23:55Z (configured660 seconds),
with duration_complete recorded and its lock released. It exercised repeated
public requests, raw-first storage, deduplication, actual checkpoint execution
and preservation of incoming nominal-future KNMI reports. Subsequent scheduled
runs used the same database and preserved observations/predictions. Graceful
stop/restart was exercised twice without forced termination or database reset.

A real24-hour AWC verification request succeeded separately. It returned48 EDDM,
47 EHAM,48 EPWA and48 EGLL records, with routine observation minutes matching
20/50,25/55,00/30,20/50 respectively. This download was source verification,
not backfilled real-time prediction evidence.

At the snapshot the continuous database contained597 normalized PWS records,
including stale/flagged values;175 immutable predictions;163 matched predictions,
of which4 prototype forecasts were ineligible for prospective scoring. The
settlements span only **7 distinct airport/nominal-target cycles**. Multiple
methods/checkpoints are correlated and do not create163 independent trials.
There were12 pending predictions for EPWA13:00Z.

### Providers

| Provider | Operational evidence | Normalized rows | Observed cadence | Freshness / failures |
|---|---|---:|---|---|
| openSenseMap |176 raw responses;172 station polls |202 | Median of available station QC intervals296.812s | Mixed fresh and very stale records; median-of-station observation-age summaries about45.6days;0 request failures |
| Sensor.Community |259 raw responses;169 station polls |395 |147.5s median **server-ingest proxy**, not verified measurement cadence | Measurement age unknown (NULL); current ingest clocks available;0 request failures |
| AWC |39 raw responses |32 first-per-run/source report rows | Configured>=60s polling; routine schedules checked separately |2 genuine ReadTimeout errors; recovered while other sources continued |
| DWD10min |44 raw responses |293 first-per-run/source rows | Source10-minute product; polling>=60s | Actual product data can lag;0 captured errors |
| KNMI METAR |44 raw responses |6 first-per-run/source report rows | Source routine25/55; polling>=60s | Nominal-future report delivery observed;0 captured errors |
| Netatmo | DISABLED / authentication blocked |0 | Not measured | No credentials or paid access enabled |

Official normalized rows include restart snapshots, not independent routine-target
counts. HTTP polling intervals are not sensor update intervals. PWS duplicate
arrivals were retained without inflating unique normalized records:36 openSenseMap
and72 Sensor.Community duplicate arrivals at the snapshot.

HEALTHY means the source supplies some currently eligible data, not that every
station is fresh or reliable. The frozen research cohort includes stale sensors;
the QC reports expose them. No fabricated score or confidence level was filled in.

### Airport coverage

All times UTC on2026-10-24 unless a date is shown.

| Airport | Selected | Usable now | Latest sensor measurement | Latest server-ingest proxy | Last METAR nominal | Pending |
|---|---:|---:|---|---|---|---:|
| EDDM |8 |5 |12:50:50.419 |12:52:08 |12:50 |0 |
| EHAM |8 |4 |2026-07-05 12:35:02.284 (STALE) |12:52:30 |12:55 |0 |
| EPWA |8 |5 |12:51:45.712 |12:52:33 |12:30 |12 |
| EGLL |8 |5 |12:48:47.111 |12:52:19 |12:50 |0 |

The EHAM fresh inputs came from server-timestamped Sensor.Community data, not the
stale openSenseMap measurement shown. Stations are provider records, not proven
independent physical installations. Exact cohort identities and reasons are in
continuous_cohort/pws_selections and the CLI, not manually selected by outcome.

## Timing findings and defects corrected

KNMI's nominal EHAM12:25 report was received at about12:21:58Z. The first soak
exposed an existing-baseline-style error: excluding future-nominal reports from
baseline history also hid the fact that the target was already received.
The baseline gate now checks target receipt independently of nominal-time history.
Four affected prototype forecasts remain immutable, with valid_prospective=false,
and are excluded from accuracy/lead summaries. They were not deleted or repaired.

A target received ahead of its nominal time is settled when due even without a
new report identity. Corrections append versions; initial and latest views remain
separate. Ambiguous initial temperatures invalidate evaluation.

An audit of stored input IDs found **0 future-receipt input violations** against
their persisted cutoffs. This does not remove unknown sensor-clock semantics or
prove global information availability. Startup/gap-censored references and
unverified clock offset qualify lead summaries.

Windows canonicalizes registered XML: the trigger SID can become a domain account
name and default RunLevel can be omitted. Verification now confirms the expected
account/SID and independently queries native Limited privilege before accepting an
omitted XML field. Elevated or unrelated configurations still fail verification.
The installed task's command, config, directory, current account, InteractiveToken,
IgnoreNew, no time limit and3 restarts at1 minute were verified.

Primary schema references:
- https://learn.microsoft.com/en-us/windows/win32/taskschd/task-scheduler-schema
- https://learn.microsoft.com/en-us/windows/win32/taskschd/logontrigger-userid
- https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-runlevel-principaltype-element
- https://aviationweather.gov/data/api/

## Verification

- uv sync --locked: PASS;37 packages resolved/audited, lock unchanged.
- Baseline before edits:118 tests passed.
- Full pytest: **142 passed in13.79s**. The final report-status/interval change also passed all24 focused continuous tests in2.29s.
- Ruff check: PASS.
- Ruff format --check: PASS;59 files formatted.
- Strict mypy: PASS;30 source files.
- git diff --check: PASS.
- Live raw capture, normalization, repeated polling, real forecast creation,
  actual matching, hourly QC publication and task-driven restart: OBSERVED.
- Integrity and foreign-key checks: PASS.
- Saved Windows task verification: PASS.
- Active source fingerprints: PASS.
- No known unresolved test failures.

Synthetic fault tests cover HTTP timeout/429/authentication/malformed/empty
responses in existing adapters, provider isolation, timestamp/as-of cases,
duplicate arrivals, early nominal-future targets, SPECI/corrections, missed slots,
rollover, immutable predictions/settlements, rollback, bounded SQLite contention,
dead-process lock recovery and safe Windows rendering/ownership verification.
Synthetic fixtures are not counted as live measurements.

The first QC refresh completed for all four airports around12:40:20–21Z, and the
subsequent run also refreshed QC. Minimum scoring/calibration history is still
insufficient. No station is promoted merely from a short favorable sample.

## Artifacts and limitations

Ignored live research data:
- data/continuous-v1.sqlite3 and data/continuous-v1-raw/
- data/m16-verification/final_snapshot.json
- reports/continuous/ (health, freshness, coverage, initial/latest settlements,
  accuracy, matched comparisons/uncertainty, stability and lead)
- logs/continuous/collector.log and errors.log (final structured UTC logs)
- logs/continuous/*.bootstrap.log (preserved prototype text logs)

Database/WAL/related files totalled10,506,170bytes; raw JSON files2,293,376bytes
at the snapshot. Sizes grow while collecting; the health storage warning never
deletes research data. Reports are generated on request, not on every poll.

The system is configured to continue collecting; this is **not** a completed
48-hour or seven-day soak. Netatmo credentials, pre-login boot operation, EXP-B,
a trustworthy absolute UTC offset, sufficiently long calibration/evaluation data,
and a validated information edge remain unavailable or unverified. Public API
restrictions are not an entitlement to unlimited requests. AWC recovery requests
cover2 hours; settlement reference searches cover7 days, and scheduler downtime
enumeration is capped at7 days.

Local Qwen:6 actual substantive calls;3 partially adapted/accepted and3 rejected.
11217 returned tokens;35.655s known generation time plus one unavailable duration.
No cloud-token savings or measured end-to-end acceleration is claimed.
See LOCAL_QWEN_WORKFLOW.md and the appended sanitized audit.

Implementation commits:28e980a (core), cee43df (live task verification/reporting) and4647c4f (sample-status transition and descriptive intervals).
No merge to main was performed. Final documentation/audit commit and push result
are reported separately by the completion response.
