# QC performance before/after

Frozen real dataset: consistent SQLite backup captured2026-10-25T19:57:33Z on the Windows workstation, source revisionba16c63. EPWA187provider station records. Same input cutoff for direct algorithm comparison. Existing background workstation/collector load remained; no thermal/CPU isolation is claimed. Single measured run per profiled case, no statistical confidence interval.

| Measurement | Before | After |
|---|---:|---:|
| QC wall, both cProfile enabled | 211.769s | 10.983s |
| QC CPU, both cProfile enabled | 209.516s | 10.938s |
| Unprofiled snapshot calculation | Not measured | 5.455s |
| Entire calculation occupies ingestion writer | Yes | No |
| Station quality output comparison | Baseline187 | 187identical |
| Actual concurrent snapshot read | — | 1150.014ms |
| Actual concurrent private QC calculation | — | 7289.560ms |
| Result publication writer execution | — | 28.201ms |

The comparable profiled speedup is about19.3x. Unprofiled5.46s must not be compared directly against profiled211.77s as a measured speedup. Algorithmic savings reduce CPU; executor separation prevents CPU work holding the writer.

## Concurrent replay

isolated real-payload replay: PWS up to10/s METAR2/s scheduler1/s heartbeat1/s settlement/3s. Real stored payloads and schema, separate cloned DB/raw directory; benchmark clock/model outputs are explicitly synthetic replays and never prospective weather results. One scheduler warm-up/full cold-settlement pass precedes sampling; the normal persisted observation cursor is used afterward. The original replay without receipt indexing and with full-history settlement is retained as qc_concurrent_missing_index_metrics.json. Cold settlement after indexing measured2928.029ms and remains a startup limitation.

| Operation | N | Queue p95 ms | Queue p99 ms | Duration p95 ms |
|---|---:|---:|---:|---:|
| RAW_CAPTURE | 74 | 9.630 | 29.483 | 17.040 |
| PREDICTION_CREATE | 8 | 17.817 | 17.817 | 19.217 |
| COLLECTOR_HEARTBEAT | 8 | 6.566 | 6.566 | 17.625 |
| PREDICTION_SETTLE | 3 | 7.433 | 7.433 | 63.430 |
| PWS_INGEST | 60 | 14.265 | 63.568 | 23.723 |
| METAR_INGEST | 14 | 21.559 | 21.559 | 23.117 |
| QC_DATABASE_READ | 1 | 0.000 | 0.000 | 1150.014 |
| QC_HOURLY | 1 | 0.000 | 0.000 | 7289.560 |
| QC_DATABASE_WRITE | 1 | 0.089 | 0.089 | 28.290 |

PWS/METAR steady replay queue targets<100ms p95/<500ms p99 passed in this bounded workload. Small sample counts are prominent; these are not guarantees. PREDICTION_CREATE timing measures scheduler invocation, not necessarily a generated checkpoint. Actual checkpoint delay is measured separately from persisted live records. Integrityok, no FK errors, one complete QC batch. No input rows were dropped in this isolated replay; source measurement dedup and first receipts remain preserved.

## Reproduction/provenance

Commands executed before changing baseline source: `.venv/Scripts/python.exe data/benchmarks/profile_qc_before.py`; candidate profiled/unprofiled runs on the same initial backup; `.venv/Scripts/python.exe data/benchmarks/concurrent_qc.py`. The local scripts/backup remain ignored research artifacts. Baseline script must run against baseline revision, not the updated algorithm. Raw metrics and cProfile text are retained under reports/performance.

Live operational QC-cycle validation is appended below after deployment. Startup and steady-state latency are reported separately; no seven-day or48h soak is claimed.


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
