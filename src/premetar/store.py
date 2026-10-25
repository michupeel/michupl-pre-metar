"""One disk worker: immutable fsynced raw -> parsing -> transactional SQLite."""

import asyncio
import base64
import hashlib
import json
import os
import sqlite3
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from premetar.model import Observation, utc_now
from premetar.performance import LOCAL, TimedConnection, Timings
from premetar.performance import policy as timing_policy

T = TypeVar("T")
SAFE_HEADERS = {
    "date",
    "last-modified",
    "etag",
    "cache-control",
    "age",
    "content-type",
    "retry-after",
    "x-cache",
}
SAFE_QUERY = {"ids", "format", "hours", "sorting", "maxKeys", "orderBy"}


def safe_url(url: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port:
        host += f":{parts.port}"
    query = urlencode(
        [(k, v if k in SAFE_QUERY else "REDACTED") for k, v in parse_qsl(parts.query)]
    )
    return urlunsplit((parts.scheme, host, parts.path, query, ""))


def report_identity(obs: Observation) -> str:
    # Provider whitespace and terminal delimiter differ; COR/AUTO/full content survive.
    canonical = " ".join(obs.raw_text.rstrip().rstrip("=").split())
    identity = f"{obs.station_icao}|{obs.product_type}|{obs.event_time.isoformat()}|{canonical}"
    return hashlib.sha256(identity.encode()).hexdigest()


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=FULL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO schema_version VALUES(1);
CREATE TABLE IF NOT EXISTS runs(
 id TEXT PRIMARY KEY, started_at TEXT NOT NULL, ended_at TEXT, heartbeat TEXT NOT NULL,
 manifest_json TEXT NOT NULL, exit_reason TEXT);
CREATE TABLE IF NOT EXISTS raw_payloads(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), source TEXT NOT NULL,
 received_at TEXT NOT NULL, monotonic_ns INTEGER NOT NULL, sha256 TEXT NOT NULL,
 path TEXT NOT NULL UNIQUE, http_status INTEGER NOT NULL, request_url TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS observations(
 id INTEGER PRIMARY KEY, identity TEXT NOT NULL, run_id TEXT NOT NULL REFERENCES runs(id),
 raw_id TEXT NOT NULL REFERENCES raw_payloads(id), station_icao TEXT NOT NULL, source TEXT NOT NULL,
 product_type TEXT NOT NULL, event_time TEXT NOT NULL, report_time TEXT,
 source_publish_time TEXT, source_receipt_time TEXT,
 collector_request_start_time TEXT, collector_request_end_time TEXT, collector_receive_time TEXT,
 receive_monotonic_ns INTEGER, request_start_monotonic_ns INTEGER,
 temperature_c REAL, dewpoint_c REAL, temperature_precision REAL,
 raw_text TEXT NOT NULL, raw_sha256 TEXT NOT NULL, evidence_class TEXT NOT NULL,
 startup_censored INTEGER NOT NULL, coverage_gap INTEGER NOT NULL, data_json TEXT NOT NULL,
 UNIQUE(run_id,source,identity));
CREATE INDEX IF NOT EXISTS observation_match ON observations(run_id,station_icao,event_time);
CREATE TABLE IF NOT EXISTS canonical_reports(
 identity TEXT PRIMARY KEY, station_icao TEXT NOT NULL, product_type TEXT NOT NULL,
 report_time TEXT NOT NULL, raw_text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS report_receipts(
 id INTEGER PRIMARY KEY, report_identity TEXT NOT NULL REFERENCES canonical_reports(identity),
 observation_id INTEGER NOT NULL REFERENCES observations(id), raw_id TEXT NOT NULL REFERENCES raw_payloads(id),
 run_id TEXT NOT NULL, source TEXT NOT NULL, collector_receive_time TEXT NOT NULL,
 receive_monotonic_ns INTEGER NOT NULL, source_receipt_time TEXT,
 UNIQUE(raw_id,observation_id));
CREATE INDEX IF NOT EXISTS receipt_observation_clock ON report_receipts(observation_id,collector_receive_time);
CREATE TABLE IF NOT EXISTS source_health(
 run_id TEXT NOT NULL REFERENCES runs(id), source TEXT NOT NULL, last_attempt TEXT,
 last_success TEXT, last_event TEXT, last_error TEXT, consecutive_errors INTEGER NOT NULL DEFAULT 0,
 interval_sec REAL NOT NULL, PRIMARY KEY(run_id,source));
CREATE TABLE IF NOT EXISTS errors(
 id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), source TEXT NOT NULL,
 at TEXT NOT NULL, error_class TEXT NOT NULL, raw_id TEXT REFERENCES raw_payloads(id));
"""


class Store:
    def __init__(self, database: Path, raw_path: Path, run_id: str) -> None:
        self.database, self.raw_path, self.run_id = database, raw_path, run_id
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="premetar-disk")
        self.connection: sqlite3.Connection
        self.timings = Timings()
        self.pending = asyncio.Semaphore(timing_policy().max_pending)

    async def _call(self, fn: Callable[..., T], *args: Any) -> T:
        queued = time.perf_counter_ns()
        queued_utc = utc_now().isoformat()
        names = {
            "ingest": "PWS_INGEST",
            "_parse_and_save": "METAR_INGEST",
            "schedule": "PREDICTION_CREATE",
            "settle": "PREDICTION_SETTLE",
            "publish_quality": "QC_DATABASE_WRITE",
            "_heartbeat": "COLLECTOR_HEARTBEAT",
            "heartbeat": "HEALTH_WRITE",
            "_capture": "RAW_CAPTURE",
        }
        name = names.get(getattr(fn, "__name__", ""), "DATABASE_OPERATION")

        def execute() -> T:
            start = time.perf_counter_ns()
            sql_before = getattr(LOCAL, "sql_ns", 0)
            changes = self.connection.total_changes if hasattr(self, "connection") else 0
            item: dict[str, Any] = dict(
                operation_name=name,
                operation_start_utc=queued_utc,
                worker_start_utc=utc_now().isoformat(),
                success=True,
                error=None,
                rows_processed=None,
            )
            try:
                result = fn(*args)
                item["rows_processed"] = (
                    len(result)
                    if isinstance(result, list)
                    else 1
                    if isinstance(result, str)
                    else None
                )
                return result
            except BaseException as exc:
                item.update(
                    success=False,
                    error=type(exc).__name__,
                    sqlite_error=getattr(exc, "sqlite_errorname", None),
                )
                raise
            finally:
                end = time.perf_counter_ns()
                try:
                    changed = (
                        self.connection.total_changes - changes
                        if hasattr(self, "connection")
                        else None
                    )
                except sqlite3.ProgrammingError:
                    changed = None  # Connection just closed.
                item.update(
                    operation_end_utc=utc_now().isoformat(),
                    duration_ms=(end - queued) / 1e6,
                    queue_wait_ms=(start - queued) / 1e6,
                    worker_execution_ms=(end - start) / 1e6,
                    db_execution_ms=(getattr(LOCAL, "sql_ns", 0) - sql_before) / 1e6,
                    rows_changed=changed,
                )
                self.timings.record(item)

        async with self.pending:
            future = asyncio.get_running_loop().run_in_executor(self.executor, execute)
            try:
                return await asyncio.shield(future)
            except asyncio.CancelledError:
                await (
                    future
                )  # Finish the bounded in-flight disk operation before releasing capacity.
                raise

    async def open(self, manifest: dict[str, Any], intervals: dict[str, float]) -> None:
        await self._call(self._open, manifest, intervals)

    def _open(self, manifest: dict[str, Any], intervals: dict[str, float]) -> None:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database, timeout=30, factory=TimedConnection)
        self.connection.executescript(SCHEMA)
        version = self.connection.execute("SELECT max(version) FROM schema_version").fetchone()[0]
        if version != 1:
            raise RuntimeError("Unsupported schema version")
        now = utc_now().isoformat()
        with self.connection:
            self.connection.execute(
                "INSERT INTO runs VALUES(?,?,NULL,?,?,NULL)",
                (self.run_id, now, now, json.dumps(manifest)),
            )
            for source, interval in intervals.items():
                self.connection.execute(
                    "INSERT INTO source_health(run_id,source,interval_sec) VALUES(?,?,?)",
                    (self.run_id, source, interval),
                )
        # Manifest lives outside SQLite too, permitting raw replay after DB loss.
        folder = self.raw_path / "manifests"
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / f"{self.run_id}.json").open("x", encoding="utf-8") as file:
            json.dump(manifest, file, indent=2)
            file.flush()
            os.fsync(file.fileno())

    async def capture(self, packet: dict[str, Any], body: bytes) -> dict[str, Any]:
        return await self._call(self._capture, packet, body)

    def _capture(self, packet: dict[str, Any], body: bytes) -> dict[str, Any]:
        packet = dict(packet)
        packet.update(id=uuid4().hex, run_id=self.run_id, sha256=hashlib.sha256(body).hexdigest())
        packet["request_url"] = safe_url(packet["request_url"])
        packet["headers"] = {
            k.lower(): v for k, v in packet["headers"].items() if k.lower() in SAFE_HEADERS
        }
        timestamp = datetime.fromisoformat(packet["received_at"])
        folder = self.raw_path / packet["source"] / timestamp.strftime("%Y/%m/%d")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{self.run_id}_{packet['id']}.json"
        # Raw response body preserved byte for byte, including compressed archives.
        with path.open("x", encoding="utf-8") as file:
            json.dump({**packet, "body_base64": base64.b64encode(body).decode("ascii")}, file)
            file.flush()
            os.fsync(file.fileno())
        packet["path"] = str(path.resolve())
        with self.connection:
            self.connection.execute(
                "INSERT INTO raw_payloads VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    packet["id"],
                    self.run_id,
                    packet["source"],
                    packet["received_at"],
                    packet["monotonic_ns"],
                    packet["sha256"],
                    packet["path"],
                    packet["http_status"],
                    packet["request_url"],
                ),
            )
        return packet

    async def parse_and_save(
        self,
        packet: dict[str, Any],
        body: bytes,
        parser: Callable[[bytes, datetime], list[Observation]],
        stations: set[str],
        startup: bool,
        gap: bool,
    ) -> list[Observation]:
        return await self._call(self._parse_and_save, packet, body, parser, stations, startup, gap)

    def _parse_and_save(
        self,
        packet: dict[str, Any],
        body: bytes,
        parser: Callable[[bytes, datetime], list[Observation]],
        stations: set[str],
        startup: bool,
        gap: bool,
    ) -> list[Observation]:
        # This method is only called after capture() has returned its durable ACK.
        received = datetime.fromisoformat(packet["received_at"])
        observations = parser(body, received)
        for obs in observations:
            if obs.station_icao not in stations:
                raise ValueError("Unexpected station")
            obs.run_id, obs.raw_sha256 = self.run_id, packet["sha256"]
            obs.collector_request_start_time = datetime.fromisoformat(packet["request_start"])
            obs.collector_request_end_time = datetime.fromisoformat(packet["request_end"])
            obs.collector_receive_time = received
            obs.receive_monotonic_ns = packet["monotonic_ns"]
            obs.request_start_monotonic_ns = packet["request_start_monotonic_ns"]
            obs.startup_censored, obs.coverage_gap = startup, gap
            obs.metadata_json["http_last_modified"] = packet["headers"].get("last-modified")
        with self.connection:
            for obs in observations:
                ident = report_identity(obs)
                data = obs.model_dump(mode="json")
                columns = [
                    "identity",
                    "run_id",
                    "raw_id",
                    "station_icao",
                    "source",
                    "product_type",
                    "event_time",
                    "report_time",
                    "source_publish_time",
                    "source_receipt_time",
                    "collector_request_start_time",
                    "collector_request_end_time",
                    "collector_receive_time",
                    "receive_monotonic_ns",
                    "request_start_monotonic_ns",
                    "temperature_c",
                    "dewpoint_c",
                    "temperature_precision",
                    "raw_text",
                    "raw_sha256",
                    "evidence_class",
                    "startup_censored",
                    "coverage_gap",
                    "data_json",
                ]
                values = (
                    [ident, self.run_id, packet["id"]]
                    + [data[c] for c in columns[3:-1]]
                    + [obs.model_dump_json()]
                )
                placeholders = ",".join("?" for _ in values)
                self.connection.execute(
                    f"INSERT OR IGNORE INTO observations({','.join(columns)}) VALUES({placeholders})",
                    values,
                )
                obs_id = self.connection.execute(
                    "SELECT id FROM observations WHERE run_id=? AND source=? AND identity=?",
                    (self.run_id, obs.source, ident),
                ).fetchone()[0]
                if obs.product_type in ("METAR", "SPECI"):
                    self.connection.execute(
                        "INSERT OR IGNORE INTO canonical_reports VALUES(?,?,?,?,?)",
                        (
                            ident,
                            obs.station_icao,
                            obs.product_type,
                            data["report_time"],
                            obs.raw_text,
                        ),
                    )
                    self.connection.execute(
                        "INSERT INTO report_receipts(report_identity,observation_id,raw_id,run_id,source,collector_receive_time,receive_monotonic_ns,source_receipt_time) VALUES(?,?,?,?,?,?,?,?)",
                        (
                            ident,
                            obs_id,
                            packet["id"],
                            self.run_id,
                            obs.source,
                            data["collector_receive_time"],
                            obs.receive_monotonic_ns,
                            data["source_receipt_time"],
                        ),
                    )
            latest = max((o.event_time.isoformat() for o in observations), default=None)
            self.connection.execute(
                "UPDATE source_health SET last_attempt=?, last_success=?, last_event=COALESCE(?,last_event), last_error=NULL, consecutive_errors=0 WHERE run_id=? AND source=?",
                (
                    packet["request_start"],
                    packet["received_at"],
                    latest,
                    self.run_id,
                    packet["source"],
                ),
            )
        return observations

    async def error(self, source: str, error_class: str, raw_id: str | None = None) -> None:
        await self._call(self._error, source, error_class, raw_id)

    def _error(self, source: str, error_class: str, raw_id: str | None) -> None:
        at = utc_now().isoformat()
        with self.connection:
            self.connection.execute(
                "INSERT INTO errors(run_id,source,at,error_class,raw_id) VALUES(?,?,?,?,?)",
                (self.run_id, source, at, error_class, raw_id),
            )
            self.connection.execute(
                "UPDATE source_health SET last_attempt=?, last_error=?, consecutive_errors=consecutive_errors+1 WHERE run_id=? AND source=?",
                (at, error_class, self.run_id, source),
            )

    async def heartbeat(self) -> None:
        await self._call(self._heartbeat)

    def _heartbeat(self) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE runs SET heartbeat=? WHERE id=?", (utc_now().isoformat(), self.run_id)
            )

    async def close(self, reason: str) -> None:
        await self._call(self._close, reason)
        self.executor.shutdown(wait=True)

    def _close(self, reason: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE runs SET ended_at=?,exit_reason=? WHERE id=?",
                (utc_now().isoformat(), reason, self.run_id),
            )
        self.connection.close()
