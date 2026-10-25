"""Bounded operational timing; no exception text, provider bodies or credentials."""

import json
import logging
import sqlite3
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field

from premetar.timing_summary import summarize_timings

LOCAL = threading.local()
LOG = logging.getLogger("premetar.performance")


class TimingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    detailed: bool = False
    slow_ms: float = Field(default=100, gt=0)
    max_pending: int = Field(default=64, ge=4, le=256)
    samples_per_operation: int = Field(default=4096, ge=100, le=10000)


@lru_cache(maxsize=1)
def policy() -> TimingPolicy:
    path = Path("configs/performance-v1.json")
    return (
        TimingPolicy.model_validate_json(path.read_text(encoding="utf-8"))
        if path.exists()
        else TimingPolicy()
    )


def sql_call[T](fn: Callable[..., T], *args: Any) -> T:
    started = time.perf_counter_ns()
    try:
        return fn(*args)
    finally:
        LOCAL.sql_ns = getattr(LOCAL, "sql_ns", 0) + time.perf_counter_ns() - started


class TimedCursor(sqlite3.Cursor):
    def execute(self, sql: str, parameters: Any = (), /) -> Self:
        sql_call(super().execute, sql, parameters)
        return self

    def executemany(self, sql: str, parameters: Any, /) -> Self:
        sql_call(super().executemany, sql, parameters)
        return self

    def __next__(self) -> Any:
        return sql_call(super().__next__)

    def fetchmany(self, size: int | None = None) -> list[Any]:
        return sql_call(super().fetchmany) if size is None else sql_call(super().fetchmany, size)

    def fetchone(self) -> Any:
        return sql_call(super().fetchone)

    def fetchall(self) -> list[Any]:
        return sql_call(super().fetchall)


class TimedConnection(sqlite3.Connection):
    """SQLite API duration includes materialization and any SQLite lock waiting."""

    def execute(self, sql: str, parameters: Any = (), /) -> TimedCursor:
        return self.cursor(TimedCursor).execute(sql, parameters)

    def executemany(self, sql: str, parameters: Any, /) -> TimedCursor:
        return self.cursor(TimedCursor).executemany(sql, parameters)

    def executescript(self, sql: str, /) -> sqlite3.Cursor:
        return sql_call(super().executescript, sql)

    def commit(self) -> None:
        sql_call(super().commit)

    def rollback(self) -> None:
        sql_call(super().rollback)

    def __exit__(self, *args: Any) -> Literal[False]:
        sql_call(super().__exit__, *args)
        return False


class Timings:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.samples: dict[str, deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=policy().samples_per_operation)
        )
        self.counts: dict[str, int] = defaultdict(int)
        self.last_log: dict[str, float] = {}

    def record(self, item: dict[str, Any]) -> None:
        name = item["operation_name"]
        with self.lock:
            self.samples[name].append(item)
            self.counts[name] += 1
            now = time.monotonic()
            log = policy().detailed or (
                (not item["success"] or item["duration_ms"] >= policy().slow_ms)
                and now - self.last_log.get(name, 0) >= 10
            )
            if log:
                self.last_log[name] = now
        if log:
            LOG.info(json.dumps(item, default=str))

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            result: dict[str, Any] = summarize_timings(
                [r for group in self.samples.values() for r in group]
            )
            for name, item in result.items():
                item["total_operations"] = self.counts[name]
            return result


DEFAULT = Timings()


@contextmanager
def timed_operation(
    name: str, recorder: Timings | None = None, rows: int | None = None
) -> Iterator[dict[str, Any]]:
    started = time.perf_counter_ns()
    utc = datetime.now(UTC).isoformat()
    old_sql = getattr(LOCAL, "sql_ns", 0)
    item: dict[str, Any] = dict(rows_processed=rows, success=True, error=None)
    try:
        yield item
    except BaseException as exc:
        item.update(success=False, error=type(exc).__name__)
        raise
    finally:
        duration = (time.perf_counter_ns() - started) / 1e6
        item.update(
            operation_name=name,
            operation_start_utc=utc,
            operation_end_utc=datetime.now(UTC).isoformat(),
            duration_ms=duration,
            queue_wait_ms=0,
            worker_execution_ms=duration,
            db_execution_ms=(getattr(LOCAL, "sql_ns", 0) - old_sql) / 1e6,
        )
        (recorder or DEFAULT).record(item)
