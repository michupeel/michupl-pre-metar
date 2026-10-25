# Non-blocking analytical QC and sensor histories

The unchanged ingest-time strict timestamp/physical eligibility remains mandatory.
Deferred analytical QC never automatically certifies a newly ingested observation.

Hourly analysis now runs on one dedicated CPU thread with a private in-memory
SQLite backup. The live connection is read-only, opened/closed on that thread;
backup uses256-page steps, cooperative cancellation and a30-second snapshot
budget. After copying, no live read transaction remains during calculations.
Each airport is processed serially; jobs cannot overlap or accumulate. No broker,
process pool or extra live database writer is introduced. Memory holds one DB
snapshot at a time. A very large future database may require bounded table
snapshots; current measured copying is documented in the benchmark report.

The existing QC/calibration algorithms run on that private database. Identical
airport reference queries are shared within a calculation. Historical peer rows
are indexed by event time and prefiltered only when strict first-receipt
ineligibility proves they can never be usable at a later decision time; final
per-decision eligibility checks remain.187 real-data station results matched the
baseline exactly. Prepared and full-scan peer comparisons have regression tests.

Only completed results return to the existing serialized writer. Short publication
transactions acquire a write reservation before assigning publication timestamps.
QC publication uses a non-waiting lock attempt; bounded retries sleep outside the
writer. A separate immutable proof records a timestamp AFTER the parameter
transaction commits. As-of calibration/quality use and integrity audits require
that proof for new batches. A crash before proof publication cannot expose an
unproven model; repeat publication is idempotent. Prior predictions/results stay
immutable. Snapshot cutoff, completion, CPU/wall time, stage and batch ID persist.

Shutdown sets a cooperative thread flag, interrupts SQLite progress and exits
between stations/peer checks. It discards incomplete work and finishes in-flight
bounded writer operations. Restart resumes the existing scheduling cursor and
station selection; elapsed checkpoints remain missed rather than backdated.

`configs/performance-v1.json` controls detailed records, slow threshold, bounded
pending writer operations and bounded per-operation timing samples. Defaults:
64 pending operations,4096 recent samples/operation, detailed=false,100ms slow
threshold. Slow/error records are rate-limited per operation; performance.log
rotates at2MB with3 backups. Cumulative operation counts and recent-window p95/p99
appear in continuous health.data.performance. Queue wait includes backpressure
and executor waiting. db_execution_ms measures SQLite API calls including fetch
materialization and lock waits; it does not pretend to isolate lock wait from SQL
CPU. worker_execution_ms includes Python work and filesystem durability. Source
receipt clocks are unchanged and precede queue submission. No exception text,
raw bodies or secrets enter timing logs. REPORT_GENERATION is measured separately
in CLI report processes. Metrics are engineering diagnostics, not independent
scientific samples or clock-accuracy certification.

The receipt join index was added after EXPLAIN confirmed full receipt-table scans
in first-target lookup. Existing WAL/FULL durability and single-writer policy are
retained. The online backup avoids a long analytical reader pinning the live WAL.
See [SQLite backup](https://www.sqlite.org/backup.html),
[WAL concurrency/checkpoint constraints](https://www.sqlite.org/wal.html), and
[Python backup API](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup).

## Sensor inspection

```powershell
Set-Location D:\metar-execution-lab\michupl-pre-metar
uv sync --locked
uv run premetar pws sensor-history --station 61c1f4ff80a739001cda08bb --date 2026-10-25 --limit 30
uv run premetar pws sensor-history --station 61c1f4ff80a739001cda08bb --date 2026-10-25 --format csv
uv run premetar pws sensor-history --station 61c1f4ff80a739001cda08bb --date 2026-10-25 --format json
uv run premetar continuous status
```

The command uses the existing DB read-only and exports the complete day regardless
of terminal table limit. Matplotlib is a development/reporting dependency only;
collection does not import it. Day bounds use ZoneInfo calendar midnights;25Oct
2026 Warsaw spans22:00Z24Oct to23:00Z25Oct,25hours. Local offsets preserve repeated
02:xx clocks. Separate thermometers remain separate series; conflicting duplicate
measurements are excluded. Lines stop at gaps>15min and show actual sample points.
Nearest±5min METAR pairs are exploratory agreement, not prospective forecasts.
Receipt-cutoff comparisons and linked immutable predictions are separate. Initial
routine transitions, corrections and false-alarm record definitions are explicit.
A one-day warm offset is not proof of sensor heating or professional calibration.
