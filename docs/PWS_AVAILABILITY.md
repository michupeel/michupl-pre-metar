# openSenseMap availability recovery —1.6.2

## Accounting and integrity

`/boxes?bbox=...` discovers metadata. `/boxes/{id}/sensors` supplies actual latest
values and clocks for all expected temperature sensors in one box request. The
root-cause investigation verified these existing endpoints; no endpoint or
strict timestamp rule changed. API-labelled measurement createdAt is accepted
under the existing documented contract, without a claim of device-clock attestation.
Sensor.Community timestamp restrictions remain in force.

Empty/missing lastMeasurement, missing sensor and absent temperature generate
NO_MEASUREMENT in append-only pws_sensor_checks; the original raw response remains
in immutable storage. No pws_observations row or arrival is created. Invalid
values/clocks produce explicit check diagnostics. A timestamped numeric reading
may remain quarantined in normalized history under existing strict policy.
Other outcomes: SUCCESS_NEW_MEASUREMENT, SUCCESS_UNCHANGED_MEASUREMENT,
STALE_MEASUREMENT, INVALID_MEASUREMENT and PROVIDER_ERROR. Checks are per sensor;
continuous_polls counts box requests; raw_payloads counts received HTTP responses
(including retries/discovery). Multiple sensors sharing a box share one capture.
Unique source temperature identity uses sensor, event UTC, normalized temperature
and evidence class. Raw formatting changes cannot manufacture new measurements;
conflicting temperatures retain separate evidence. First receipt is never updated.

## Prospective cohort

Additive availability schema1 preserves every historical weather row, prediction,
settlement and selection. New policy/check/preflight/selection facts prohibit
update/delete/replace. Only latest recovery state is mutable. New runs freeze
availability policy and source hashes in their existing manifest. The original
continuous-v1 experiment config stays unchanged. Policy content cannot change
under the same version. Selection versions and station-level selection history
are written together; new prediction contributions record selection_version_id.
As-of selection and strict clocks prevent future cohort/data leakage.

Daily discovery uses20km horizontal radius. Preflight is capped at200 boxes per
airport and requires outdoor exposure, valid physically plausible temperature,
verified timestamp provenance, event<=receipt, age<=300s, and strict eligibility.
The report separates ACTIVE at check from still eligible at display time. Never
checked instruments are UNVERIFIED. Unknown metadata is not a hardware defect.
A bounded shortlist can be refreshed after a long scan; selected requests retain
priority while later airports scan. One box request batches its instruments.

Selection cap defaults:4 sensors,4 provider stations,1 sensor per station,
minimum200m separation between different station records (not an identity merge).
Provider stations do not prove independent physical installations. Current
members are retained during a bounded failure streak; prior manual exclusions
remain honored. Ranking uses availability, freshness, past valid measurement
cadence, sufficiently sampled prior operational QC, distance, metadata and stable
ID tie-breaks; future prediction outcomes never enter ranking.

## Polling and recovery

At least2s global OSM request spacing, one in-flight request, existing bounded
retry/timeouts and Retry-After constraints. No numeric public quota is asserted;
these are conservative local limits, not a provider allowance. Selected cadence
uses prior unique strict-eligible event clocks, bounded300–1800s; failures back
off. Restart restores deadlines from stored check clocks, not an immediate poll.
Three consecutive empty/stale/invalid results mark an active sensor INACTIVE;
provider errors preserve sensor failure counters. Inactive boxes are rechecked
at1800s, other unselected candidates at3600s. First fresh recovery schedules a
confirmation after300s; two fresh confirmations restore selection eligibility.
A second request seconds later cannot bypass hysteresis. Unhealthy selected
members are replaced when fresh eligible alternatives exist. Cohort replacement
is append-only, and prior forecasts remain immutable. Manual station exclusion
still overrides automatic selection.

## Operations

Use the existing Windows task and database; never launch a second collector.
Read-only availability/status/daily commands work while collection runs. Before
an authorized deployment, online SQLite backup is mandatory; graceful stop,
confirmed task exit, another stopped-state backup, repeatable migration and
integrity/foreign-key checks precede starting the same registered task. Task
ownership/configuration is verified and never reinstalled for this change.
Clock settings are unchanged. The prior independent offset uncertainty still
limits latency interpretation. No accuracy or information-edge improvement is
claimed from station recovery.

Operational validation and actual airport counts are recorded separately in
`reports/integrity/recovery-1.6.2/` and `docs/PWS_RECOVERY_VALIDATION.md`.
