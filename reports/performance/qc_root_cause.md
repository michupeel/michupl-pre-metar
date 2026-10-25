# Hourly QC root cause — Milestone1.6.3

## Confirmed by source and a frozen real-data profile

Initial healthy run20261025T122608622365Z-3dec2c3c; live SQLite WAL/FULL,
integrityok; no FK errors. Read-only EPWA and database snapshot saved before code
changes at2026-10-25T19:57:33.271911Z. Initial exactstation77valid readings.
Existing task verified and remained running throughout diagnosis.

Store._call uses a ThreadPoolExecutor(max_workers=1). The hourly run_jobs path
submitted refresh_quality through that same executor and awaited all four
airports. The same queue serves raw capture/fsync, METAR parsing/inserts, PWS
ingest, prediction creation, settlement, discovery, selection and heartbeat.
Awaiting an executor does not itself stop asyncio; however its queued database
consumers could not complete while QC owned the worker. The coordinator also
stopped its own prediction/settlement/health ticks while awaiting QC. Independent
HTTP requests could finish, with receipt barriers active, but durable capture and
normalization queued behind QC. Receipt timestamps stayed at HTTP completion;
no claim is made that buffering/durable processing completed at that instant.

quality_snapshot wraps a complete airport calculation in `with connection`.
The first station/calibration INSERT starts a write transaction which stays open
while later stations perform CPU-heavy work. The EPWA copy profile measured:
211.769s wall,209.516s CPU; a211.141s transaction.32,871 SQL execute calls took
1.635s inside execute (this excludes later fetching/materialization). cProfile:
5,592,345 eligible calls;5,599,480 assess_time calls; historical_peer_differences
98.884s cumulative; make_pairs111.271s; repeated rows materialization103.503s.
Cumulative times overlap and must not be added.251,619,894 profiled calls.
The exact previous164s full-cycle observation used a smaller/earlier dataset;
we reproduced the mechanism, not an identical workload/time.

Repeated station/reference receipt reads plus whole peer-history eligibility
scans caused the work. The long transaction is a consequence and a potential
source of external writer contention, not evidence that the measured211s was
spent waiting for a SQLite lock. No external competing writer was observed.
The profiled run used a separate database copy without concurrent live writes.
CPU approximately wall time supports CPU/materialization as the dominant cause.
Python GIL interference remains possible; concurrency measurements quantify it.
No evidence supports an event-loop-wide synchronous211s sleep or network timeout
as the cause. Actual old queue p95/p99 were not instrumented and are not invented.

## Secondary confirmed settlement issue

The first-target receipt lookup joined observations to report_receipts without
an observation_id receipt index. EXPLAIN showed SCAN r. An initial concurrent
replay forced a full historical settlement pass and exposed54.278s worker
execution,51.462s in measured SQLite calls; all queued writes suffered.
On a separate identical copy,100 representative lookups took494.076ms before,
1.525ms after a covering report_receipts(observation_id,collector_receive_time)
index. EXPLAIN then used that covering index. A tested event-time expression
index was not retained because the planner did not use it. No blind index set
was added. Full cold settlement still costs about2.9s; it is reported separately
from steady-state incremental settlement. The initial failed replay is retained.

## Implemented solution

One separate analysis thread obtains a256-page-step online SQLite backup into
private memory, closes its read-only live connection, then computes unchanged
QC/calibration there. The analysis thread owns its own SQLite connections; it
never uses the writer connection. Jobs are serial, cancellable and bounded by a
30s copy budget. No long live read transaction pins WAL during calculation.
Only completed result rows use the existing writer. Busy publication fails
immediately and retries with sleeps outside the writer. New immutable batch and
post-commit proof facts protect as-of use, crash recovery and idempotence.
Predictions and integrity audits reject parameters lacking committed proof.
Strict ingestion validation remains synchronous and unchanged; deferred analysis
is explicitly labelled DEFERRED_ANALYTICAL_QC, not implicit verification.

Within the private calculation, identical reference rows are shared per airport;
peer histories have time-window indexes and only provably permanently invalid
first-receipt rows are prefiltered. Original final eligibility checks remain.
All187 real EPWA quality rows matched baseline exactly (publication metadata
excluded). Deterministic full-scan equivalence, shutdown, concurrent ingestion,
lock handling and immutable history tests pass. Published clock is recorded
after write reservation; actual parameter commit completion has a separate proof.
A crash between transactions leaves parameters unavailable until proof exists.

Instrumentation records operation UTC boundaries, monotonic duration, queue wait,
SQLite API time including materialization/lock waits, worker execution, processed
rows when known, changed rows, success and exception class only. Bounded metrics
and rotating logs avoid payload/secret logging. It does not infer clock precision
or separate SQL lock wait from SQLite CPU without further evidence.

Primary references: [SQLite online backup](https://www.sqlite.org/backup.html),
[WAL and checkpoint constraints](https://www.sqlite.org/wal.html),
[Python3.12 backup/thread ownership](https://docs.python.org/3.12/library/sqlite3.html).
See docs/NONBLOCKING_QC.md for implementation/operation details.


## Final live validation — 25 October 2026

The first deployed cycle also exposed a separate selection query: latest-as-of
quality lookup scanned/sorted the full quality table. EXPLAIN showed SCAN plus
temporary B-tree. `pws_quality_asof(station_id,airport_icao,created_at,id)` changed
the real EPWA candidate query from2176.909ms to25.152ms, returning the same107
sensor IDs. This index was added before final deployment; the failed/intermediate
live results are retained in live_first_deployment.json, not substituted for the
final run.

Final run20261025T203720939894Z-d9e7826e started20:37:21.968739Z through the
unchanged MichuplPreMetar-Continuous-v1 scheduled task. At20:44:02Z its heartbeat
was fresh, task RUNNING; 4 airport QC batches had actual post-commit proofs.
Ingestion validation remains synchronous and strict; deferred QC is explicitly
labeled and its parameters cannot be used before commit proof.

| Airport | Quality rows | QC wall ms | QC CPU ms |
|---|---:|---:|---:|
| EDDM | 56 | 10943.007 | 10390.625 |
| EHAM | 89 | 3827.775 | 3750.000 |
| EPWA | 187 | 6650.947 | 6406.250 |
| EGLL | 16 | 2851.554 | 2734.375 |

These calculations ran on private snapshots while the single writer continued
serving collection/scheduling. Publications occupied the writer for19–451ms;
the451ms transaction included an observed450ms SQLite API operation. No claim
that filesystem durability latency is eliminated. The 4 snapshot reads took
182–459ms. Capture/ingestion/heartbeat and scheduler calls continued during the
20:42:23–20:42:48Z cycle; this is actual live operation, not only replay evidence.

Whole-run metrics below INCLUDE cold-start outliers. Metrics summarize bounded
recent samples (4096/operation maximum); N is the retained sample count.

| Operation | N | Queue p95 ms | Queue p99 ms | Duration p95 ms |
|---|---:|---:|---:|---:|
| PWS_INGEST | 188 | 13.394 | 32.827 | 29.279 |
| METAR_INGEST | 20 | 462.008 | 468.331 | 480.233 |
| RAW_CAPTURE | 170 | 22.876 | 2493.468 | 49.423 |
| PREDICTION_CREATE | 355 | 3.522 | 18.059 | 32.076 |
| PREDICTION_SETTLE | 13 | 13.696 | 13.696 | 2834.068 |
| COLLECTOR_HEARTBEAT | 359 | 0.589 | 18.521 | 27.598 |
| QC_DATABASE_WRITE | 4 | 14.832 | 14.832 | 451.731 |

Targets are not all met: METAR queue p95 exceeds100ms; raw-capture p99 exceeds
500ms because startup full-history settlement occupied the writer for2833ms.
There were12 generated live checkpoints (EDDM/EGLL20:50 targets): actual
attempt-time lateness p95=1.111980s, narrowly above the1s target. This is scheduler
and per-method serial creation time, not a QC multi-minute stall. Cold-start
settlement, occasional durability writes and serial forecast creation are
remaining bounded latency work; no false all-targets-pass claim is made.

In6m41s the final process captured175 raw responses, normalized78 new unique PWS
measurements and138 official observation rows, and created12 immutable forecasts.
All operation summaries had0 failures. The first deployment appended30 actual
settlements at20:32:30Z; the final run had0 newly settled outcomes at20:44 because
its next forecast targets had not arrived. Its periodic settlement job executed
successfully13times. This is a short operational soak, not days of validation.

SQLite integrity=ok; foreign_key_check empty. SQL EXCEPT against the stopped
pre-index backup found0 prior rows changed/removed across observations, raw
captures, arrival events, predictions, selections, settlements, QC/calibrations
and batch/publication facts. Zero captured rows were dropped in the tested
replay; absence of missed external data during restart is not provable. Two
graceful stops were necessary (deployment, then measured index refinement), with
roughly30s and4s capture gaps. Existing task/logon policy and Windows clock
configuration were preserved. Clock remains unverified for absolute latency.

Verification: uv sync --locked passed (47packages); pytest219passed19.10s;
Ruff check passed; Ruff format84files unchanged; strict mypy45source files
passed. Runtime evidence: live_validation.json; deployment backup/row checks:
m163_deployment.json and m163_index_deployment.json. Backups/raw/profiles remain
ignored locally; selected sanitized reports are committed.
