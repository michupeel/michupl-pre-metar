"""Deferred analytical QC on private snapshots; only short publication uses the writer."""

import asyncio
import json
import logging
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from premetar.collector import wait_or_stop
from premetar.continuous.config import Config
from premetar.model import utc_now
from premetar.performance import DEFAULT, TimedConnection, Timings, sql_call, timed_operation
from premetar.pws.repository import PWSStore, rows
from premetar.pws.service import quality_snapshot, settings

LOG = logging.getLogger("premetar")
SCHEMA = """
CREATE INDEX IF NOT EXISTS receipt_observation_clock ON report_receipts(observation_id,collector_receive_time);
CREATE INDEX IF NOT EXISTS pws_quality_asof ON pws_quality_results(station_id,airport_icao,created_at,id);
CREATE TABLE IF NOT EXISTS analytical_schema_version(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO analytical_schema_version VALUES(1);
CREATE TABLE IF NOT EXISTS analytical_qc_batches(
 id TEXT PRIMARY KEY,run_id TEXT NOT NULL REFERENCES runs(id),airport_icao TEXT NOT NULL,
 input_cutoff_time TEXT NOT NULL,published_at TEXT NOT NULL,data_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS analytical_qc_publications(batch_id TEXT PRIMARY KEY REFERENCES analytical_qc_batches(id),committed_at TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS qc_batch_no_update BEFORE UPDATE ON analytical_qc_batches
 BEGIN SELECT RAISE(ABORT,'QC publication facts are immutable'); END;
CREATE TRIGGER IF NOT EXISTS qc_batch_no_delete BEFORE DELETE ON analytical_qc_batches
 BEGIN SELECT RAISE(ABORT,'QC publication facts are immutable'); END;
CREATE TRIGGER IF NOT EXISTS qc_batch_no_replace BEFORE INSERT ON analytical_qc_batches
 WHEN EXISTS(SELECT 1 FROM analytical_qc_batches WHERE id=NEW.id)
 BEGIN SELECT RAISE(IGNORE); END;
"""


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    if conn.execute("SELECT max(version) FROM analytical_schema_version").fetchone()[0] != 1:
        raise ValueError("Unsupported analytical schema")
    conn.executescript("""CREATE TRIGGER IF NOT EXISTS qc_proof_no_update BEFORE UPDATE ON analytical_qc_publications
        BEGIN SELECT RAISE(ABORT,'QC proof immutable'); END;
        CREATE TRIGGER IF NOT EXISTS qc_proof_no_delete BEFORE DELETE ON analytical_qc_publications
        BEGIN SELECT RAISE(ABORT,'QC proof immutable'); END;
        CREATE TRIGGER IF NOT EXISTS qc_proof_no_replace BEFORE INSERT ON analytical_qc_publications
        WHEN EXISTS(SELECT 1 FROM analytical_qc_publications WHERE batch_id=NEW.batch_id)
        BEGIN SELECT RAISE(IGNORE); END;""")


@dataclass
class SnapshotStore:
    connection: sqlite3.Connection


def calculate_quality(
    database: Path,
    airport: str,
    config: Config,
    cancel: threading.Event,
    recorder: Timings = DEFAULT,
) -> dict[str, Any]:
    """SQLite backup's bounded read locks avoid a multi-minute live read transaction."""
    started, cpu = time.perf_counter(), time.thread_time()
    with timed_operation("QC_HOURLY", recorder) as total:
        with closing(sqlite3.connect(":memory:", factory=TimedConnection)) as work:
            work.execute("PRAGMA foreign_keys=ON")
            with timed_operation("QC_DATABASE_READ", recorder) as read:
                deadline = time.monotonic() + 30
                with closing(
                    sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
                ) as source:

                    def progress(status: int, remaining: int, pages: int) -> None:
                        if cancel.is_set():
                            raise InterruptedError("QC stopped")
                        if time.monotonic() > deadline:
                            raise TimeoutError("QC snapshot budget exceeded")

                    sql_call(lambda: source.backup(work, pages=256, progress=progress, sleep=0.01))
                # Connection context managers commit, but close explicitly to release reader resources.
                cutoff = utc_now()
                read["rows_processed"] = work.execute(
                    "SELECT count(*) FROM pws_observations"
                ).fetchone()[0]
            work.set_progress_handler(lambda: int(cancel.is_set()), 10000)
            qid = work.execute("SELECT COALESCE(max(id),0) FROM pws_quality_results").fetchone()[0]
            cid = work.execute("SELECT COALESCE(max(id),0) FROM pws_calibrations").fetchone()[0]
            cfg = settings()
            cfg.qc = config.qc
            quality_snapshot(SnapshotStore(work), airport, cfg, cutoff, cancel.is_set)
            if cancel.is_set():
                raise InterruptedError("QC stopped")
            qualities = rows(work, "SELECT * FROM pws_quality_results WHERE id>?", (qid,))
            calibrations = rows(work, "SELECT * FROM pws_calibrations WHERE id>?", (cid,))
            total["rows_processed"] = len(qualities)
            result = dict(
                id=uuid4().hex,
                airport=airport,
                input_cutoff_time=cutoff.isoformat(),
                completed_at=utc_now().isoformat(),
                duration_ms=(time.perf_counter() - started) * 1000,
                cpu_ms=(time.thread_time() - cpu) * 1000,
                qualities=qualities,
                calibrations=calibrations,
                validation_stage="DEFERRED_ANALYTICAL_QC",
            )
        return result


def publish_quality(conn: sqlite3.Connection, run_id: str, batch: dict[str, Any]) -> int:
    timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    conn.execute("PRAGMA busy_timeout=0")
    try:
        return _publish_quality(conn, run_id, batch)
    finally:
        conn.execute(f"PRAGMA busy_timeout={int(timeout)}")


def _publish_quality(conn: sqlite3.Connection, run_id: str, batch: dict[str, Any]) -> int:
    if conn.execute("SELECT 1 FROM analytical_qc_batches WHERE id=?", (batch["id"],)).fetchone():
        if not conn.execute(
            "SELECT 1 FROM analytical_qc_publications WHERE batch_id=?", (batch["id"],)
        ).fetchone():
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "INSERT INTO analytical_qc_publications VALUES(?,?)",
                    (batch["id"], utc_now().isoformat()),
                )
        return 0
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        published = utc_now().isoformat()
        if datetime.fromisoformat(batch["input_cutoff_time"]) > datetime.fromisoformat(published):
            raise ValueError("QC clock regression")
        for item in batch["calibrations"]:
            data = json.loads(item["data_json"])
            data.update(
                created_at=published,
                published_at=published,
                input_cutoff_time=batch["input_cutoff_time"],
                qc_batch_id=batch["id"],
                validation_stage="DEFERRED_ANALYTICAL_QC",
            )
            conn.execute(
                "INSERT INTO pws_calibrations VALUES(NULL,?,?,?,?,?)",
                (
                    item["station_id"],
                    item["airport_icao"],
                    published,
                    item["trained_through"],
                    json.dumps(data),
                ),
            )
        for item in batch["qualities"]:
            data = json.loads(item["data_json"])
            data.update(
                created_at=published,
                published_at=published,
                input_cutoff_time=batch["input_cutoff_time"],
                qc_batch_id=batch["id"],
                validation_stage="DEFERRED_ANALYTICAL_QC",
            )
            conn.execute(
                "INSERT INTO pws_quality_results VALUES(NULL,?,?,?,?,?)",
                (
                    item["station_id"],
                    item["airport_icao"],
                    published,
                    item["algorithm_version"],
                    json.dumps(data),
                ),
            )
        summary = {k: v for k, v in batch.items() if k not in {"qualities", "calibrations"}}
        summary.update(
            quality_rows=len(batch["qualities"]), calibration_rows=len(batch["calibrations"])
        )
        conn.execute(
            "INSERT INTO analytical_qc_batches VALUES(?,?,?,?,?,?)",
            (
                batch["id"],
                run_id,
                batch["airport"],
                batch["input_cutoff_time"],
                published,
                json.dumps(summary),
            ),
        )
    # The proof is timestamped AFTER the parameter transaction actually committed.
    # A crash between transactions leaves parameters hidden from as-of prediction use.
    committed = utc_now().isoformat()
    with conn:
        conn.execute("INSERT INTO analytical_qc_publications VALUES(?,?)", (batch["id"], committed))
    return len(batch["qualities"])


class AnalyticalQC:
    def __init__(self, store: PWSStore, config: Config) -> None:
        self.store, self.config = store, config
        self.cancel = threading.Event()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="premetar-analysis")

    async def once(self, airport: str) -> None:
        batch = await asyncio.get_running_loop().run_in_executor(
            self.executor,
            calculate_quality,
            self.store.database,
            airport,
            self.config,
            self.cancel,
            self.store.timings,
        )
        deadline = time.monotonic() + 30
        while not self.cancel.is_set():
            try:
                await self.store._call(
                    publish_quality, self.store.connection, self.store.run_id, batch
                )
                return
            except sqlite3.OperationalError as exc:
                if (
                    getattr(exc, "sqlite_errorcode", 0) & 255
                    not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
                    or time.monotonic() >= deadline
                ):
                    raise
                await asyncio.sleep(0.25)  # Busy publication never sleeps on the critical writer.

    async def run(self, stop: asyncio.Event) -> None:
        task: asyncio.Task[None] | None = None
        try:
            await wait_or_stop(stop, self.config.minimum_poll_interval)
            while not stop.is_set():
                for airport in self.config.airports:
                    if stop.is_set():
                        break
                    try:
                        task = asyncio.create_task(self.once(airport))
                        stopping = asyncio.create_task(stop.wait())
                        done, _ = await asyncio.wait(
                            (task, stopping), return_when=asyncio.FIRST_COMPLETED
                        )
                        if stopping in done:
                            self.cancel.set()
                        stopping.cancel()
                        await asyncio.gather(stopping, return_exceptions=True)
                        await task
                    except Exception as exc:
                        if not stop.is_set():
                            await self.store.error("analytical_qc", type(exc).__name__)
                await wait_or_stop(stop, self.config.quality_seconds)
        finally:
            self.cancel.set()
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
            await asyncio.to_thread(self.executor.shutdown, wait=True, cancel_futures=True)
