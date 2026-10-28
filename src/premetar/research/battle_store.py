"""Independent append-only shadow journal with atomic restart checkpoints.

Only this experiment's directory is written. Rotation copies the last committed
checkpoint before publishing a manifest. Discovery, not the advisory manifest,
recovers a segment committed immediately before a process interruption.
"""

import json
import re
import shutil
import sqlite3
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

PATTERN = re.compile(r"battle-([0-9]{6})\.sqlite3\Z")
SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL, at TEXT NOT NULL,
 payload TEXT NOT NULL, payload_hash TEXT NOT NULL, previous_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS battle_event_time ON events(at,id);
CREATE INDEX IF NOT EXISTS battle_event_kind ON events(kind,id);
CREATE TABLE IF NOT EXISTS checkpoint (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), commit_seq INTEGER NOT NULL,
 last_id INTEGER NOT NULL,last_hash TEXT NOT NULL,state TEXT NOT NULL,
 cursors TEXT NOT NULL,at TEXT,segment_day TEXT
);
CREATE TRIGGER IF NOT EXISTS battle_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT,'immutable shadow event'); END;
CREATE TRIGGER IF NOT EXISTS battle_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT,'immutable shadow event'); END;
CREATE TRIGGER IF NOT EXISTS battle_no_replace BEFORE INSERT ON events
WHEN EXISTS(SELECT 1 FROM events WHERE id=NEW.id)
BEGIN SELECT RAISE(ABORT,'immutable shadow event identity'); END;
"""


class StorageLimit(RuntimeError):
    """Stop before exceeding a declared storage/disk budget; never delete evidence."""


class EventRecords(list[dict[str, Any]]):
    """List-compatible results; callers must expose metadata when truncated."""

    def __init__(self, values: list[dict[str, Any]], metadata: dict[str, Any]) -> None:
        super().__init__(values)
        self.metadata = metadata


def _clock(value: datetime | str) -> str:
    if not isinstance(value, (datetime, str)):
        raise ValueError("Shadow journal requires a datetime or ISO timestamp")
    parsed = (
        datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Shadow journal requires timezone-aware timestamps")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds")


def _encode(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _paths(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    root = directory.resolve()
    return sorted(
        p
        for p in root.glob("battle-*.sqlite3")
        if PATTERN.fullmatch(p.name)
        and p.is_file()
        and p.resolve().parent == root
        and not p.is_symlink()
    )


def _readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.25)
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA busy_timeout=250")
    return connection


def read_battle(directory: Path, at: datetime | None = None, limit: int = 2000) -> EventRecords:
    """Read at most30 recent segments, disclose truncation, never create a database.

    Checkpoints are deliberately not returned: historical UI derives state from
    immutable events available by its cutoff, never from the latest checkpoint.
    """
    if not 1 <= limit <= 100_000:
        raise ValueError("Event limit must be1..100000")
    cutoff = _clock(at) if at is not None else None
    all_paths = _paths(directory)
    paths = all_paths[-30:]
    rows: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    has_more = False
    for path in reversed(paths):
        connection: sqlite3.Connection | None = None
        try:
            connection = _readonly(path)
            clause = " WHERE at<=?" if cutoff else ""
            params: tuple[Any, ...] = (cutoff, limit + 1) if cutoff else (limit + 1,)
            found = connection.execute(
                "SELECT id,kind,at,payload,payload_hash,previous_hash FROM events"
                + clause
                + " ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
            rows.extend(
                dict(
                    id=r[0],
                    kind=r[1],
                    at=r[2],
                    payload=json.loads(r[3]),
                    payload_hash=r[4],
                    previous_hash=r[5],
                )
                for r in found
            )
            if len(rows) > limit:
                has_more = True
                break
        except (sqlite3.Error, ValueError) as error:
            errors[path.name] = type(error).__name__
        finally:
            if connection is not None:
                connection.close()
    rows.sort(key=lambda r: r["id"])
    return EventRecords(
        rows[-limit:],
        dict(
            truncated=has_more or len(all_paths) > 30 or bool(errors),
            segment_limit_reached=len(all_paths) > 30,
            segments_available=len(all_paths),
            segments_considered=len(paths),
            errors=errors,
            limit=limit,
            cutoff=cutoff,
            semantics="IMMUTABLE_EVENTS_ONLY_CHECKPOINT_NOT_HISTORICAL_EVIDENCE",
        ),
    )


class BattleStore:
    """One caller-owned writer; commits journal + paper state + source cursors together."""

    def __init__(
        self,
        directory: Path,
        max_segment_bytes: int = 100_000_000,
        max_total_bytes: int = 2_000_000_000,
        min_free_bytes: int = 1_000_000_000,
    ) -> None:
        if min(max_segment_bytes, max_total_bytes) <= 0 or min_free_bytes < 0:
            raise ValueError("Invalid storage bounds")
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.max_segment_bytes, self.max_total_bytes = max_segment_bytes, max_total_bytes
        self.min_free_bytes = min_free_bytes
        self.connection: sqlite3.Connection
        self.path: Path
        self._checkpoint: dict[str, Any] = dict(
            commit_seq=0,
            last_id=0,
            last_hash="",
            state={},
            cursors={},
            at=None,
            segment_day=None,
        )
        latest: tuple[int, str, Path, dict[str, Any]] | None = None
        for path in self.paths():
            connection = _readonly(path)
            try:
                # An empty segment from interrupted initialization is not a reset.
                exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='checkpoint'"
                ).fetchone()
                row = (
                    connection.execute("SELECT * FROM checkpoint WHERE singleton=1").fetchone()
                    if exists
                    else None
                )
                if row is None:
                    continue
                checkpoint = dict(
                    commit_seq=row[1],
                    last_id=row[2],
                    last_hash=row[3],
                    state=json.loads(row[4]),
                    cursors=json.loads(row[5]),
                    at=row[6],
                    segment_day=row[7],
                )
                candidate = (int(row[1]), path.name, path, checkpoint)
                if latest is None or candidate[:2] > latest[:2]:
                    latest = candidate
            finally:
                connection.close()
        if latest is not None:
            self.path, self._checkpoint = latest[2], latest[3]
            self._open(self.path)
        else:
            self._new_segment(None)
        self._manifest()

    def paths(self) -> list[Path]:
        return _paths(self.directory)

    def _guard(self, incoming: int = 0) -> None:
        total = sum(
            p.stat().st_size for p in self.directory.iterdir() if p.is_file() and not p.is_symlink()
        )
        if total + incoming > self.max_total_bytes:
            raise StorageLimit("Shadow research total-storage budget reached; no data deleted")
        if shutil.disk_usage(self.directory).free - incoming < self.min_free_bytes:
            raise StorageLimit("Shadow research minimum free disk space reached")

    def _open(self, path: Path) -> None:
        self.connection = sqlite3.connect(path, timeout=2)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA busy_timeout=2000")
        self.connection.executescript(SCHEMA)

    def _new_segment(self, day: str | None) -> None:
        self._guard(65536)
        paths = self.paths()
        number = int(PATTERN.fullmatch(paths[-1].name)[1]) + 1 if paths else 1  # type: ignore[index]
        if number > 999999:
            raise StorageLimit("Shadow segment count limit reached")
        self.path = self.directory / f"battle-{number:06d}.sqlite3"
        self._open(self.path)
        checkpoint = {**self._checkpoint, "segment_day": day}
        with self.connection:
            self._write_checkpoint(checkpoint)
        self._checkpoint = checkpoint
        self._manifest()

    def _write_checkpoint(self, value: dict[str, Any]) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO checkpoint VALUES (1,?,?,?,?,?,?,?)",
            (
                value["commit_seq"],
                value["last_id"],
                value["last_hash"],
                _encode(value["state"]),
                _encode(value["cursors"]),
                value["at"],
                value["segment_day"],
            ),
        )

    def _manifest(self) -> None:
        target = self.directory / "manifest.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(
            _encode(
                dict(
                    version=1,
                    active=self.path.name,
                    segments=[p.name for p in self.paths()],
                    commit_seq=self._checkpoint["commit_seq"],
                    recovery="VALIDATED_SEGMENT_DISCOVERY_NOT_UNTRUSTED_MANIFEST",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)

    def restore(self) -> tuple[dict[str, Any], dict[str, Any]]:
        # Round-trip prevents caller mutation before a durable transaction.
        return json.loads(_encode(self._checkpoint["state"])), json.loads(
            _encode(self._checkpoint["cursors"])
        )

    def commit(
        self,
        events: list[dict[str, Any]],
        state: dict[str, Any],
        cursors: dict[str, Any],
        at: datetime,
    ) -> None:
        timestamp = _clock(at)
        if self._checkpoint["at"] is not None and timestamp < self._checkpoint["at"]:
            raise ValueError("Shadow journal commit clock moved backwards")
        encoded_state, encoded_cursors = _encode(state), _encode(cursors)
        if not isinstance(state, dict) or not isinstance(cursors, dict):
            raise ValueError("Checkpoint state and cursors must be objects")
        checkpoint = {
            **self._checkpoint,
            "state": json.loads(encoded_state),
            "cursors": json.loads(encoded_cursors),
            "at": timestamp,
            "commit_seq": self._checkpoint["commit_seq"] + 1,
        }
        prepared = []
        for event in events:
            kind = event.get("kind")
            if not isinstance(kind, str) or not kind or len(kind) > 80:
                raise ValueError("Invalid shadow event kind")
            event_at = _clock(event.get("at", at))
            if event_at > timestamp:
                raise ValueError("Future shadow journal event")
            payload = event.get("payload", {})
            if not isinstance(payload, dict):
                raise ValueError("Shadow event payload must be an object")
            extra = {k: v for k, v in event.items() if k not in {"kind", "at", "payload"}}
            if payload.keys() & extra.keys():
                raise ValueError("Ambiguous shadow event fields")
            encoded = _encode({**payload, **extra})
            if len(encoded.encode()) > 1_000_000:
                raise StorageLimit("Event exceeds bounded evidence size")
            checkpoint["last_id"] += 1
            previous = checkpoint["last_hash"]
            digest = sha256(
                _encode([checkpoint["last_id"], kind, event_at, encoded, previous]).encode()
            ).hexdigest()
            prepared.append((checkpoint["last_id"], kind, event_at, encoded, digest, previous))
            checkpoint["last_hash"] = digest
        estimate = 65536 + 3 * (
            len(encoded_state.encode())
            + len(encoded_cursors.encode())
            + sum(len(r[3].encode()) for r in prepared)
        )
        self._guard(estimate)
        day = timestamp[:10]
        size = sum(
            p.stat().st_size for p in (self.path, Path(str(self.path) + "-wal")) if p.exists()
        )
        if self._checkpoint["segment_day"] is not None and (
            self._checkpoint["segment_day"] != day or size >= self.max_segment_bytes
        ):
            self.connection.close()
            self._new_segment(day)
        checkpoint["segment_day"] = day
        with self.connection:
            self.connection.executemany("INSERT INTO events VALUES (?,?,?,?,?,?)", prepared)
            self._write_checkpoint(checkpoint)
        self._checkpoint = checkpoint

    def read_events(self, at: datetime | None = None, limit: int = 2000) -> EventRecords:
        return read_battle(self.directory, at, limit)

    def close(self) -> None:
        self.connection.close()
