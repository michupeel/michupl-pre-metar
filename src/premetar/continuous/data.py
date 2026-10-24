"""Additive scheduling and append-only settlement over existing predictions."""

import json
import sqlite3
import time
from datetime import datetime, timedelta
from functools import partial
from typing import Any
from uuid import uuid4

from premetar.continuous.config import Config
from premetar.continuous.reference_gate import ReferenceGate
from premetar.model import icao_round_temperature, utc_now
from premetar.pws.analysis import predict
from premetar.pws.integrity import exclude_prediction, first_target_receive
from premetar.pws.models import utc
from premetar.pws.repository import rows
from premetar.sources import STATIONS

VERSION = "continuous-v1"
METHODS = (
    "previous_metar",
    "temperature_persistence",
    "simple_recent_metar_trend",
    "nearest",
    "median",
    "inverse_distance",
    "quality_weighted",
)
SCHEMA = """
CREATE TABLE IF NOT EXISTS continuous_schema_version(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO continuous_schema_version VALUES(1);
CREATE TABLE IF NOT EXISTS continuous_checkpoints(
 experiment TEXT NOT NULL, airport TEXT NOT NULL, target TEXT NOT NULL, checkpoint INTEGER NOT NULL,
 model TEXT NOT NULL, attempted_at TEXT NOT NULL, status TEXT NOT NULL, reason TEXT,
 prediction_id TEXT REFERENCES pws_predictions(id),
 PRIMARY KEY(experiment,airport,target,checkpoint,model));
CREATE TABLE IF NOT EXISTS continuous_cohort(
 experiment TEXT NOT NULL, airport TEXT NOT NULL, station_id TEXT NOT NULL REFERENCES pws_stations(station_id),
 selected_at TEXT NOT NULL, reason TEXT NOT NULL, PRIMARY KEY(experiment,airport,station_id));
CREATE TABLE IF NOT EXISTS continuous_settlements(
 id INTEGER PRIMARY KEY, prediction_id TEXT NOT NULL REFERENCES pws_predictions(id),
 report_identity TEXT NOT NULL REFERENCES canonical_reports(identity), settled_at TEXT NOT NULL,
 reference_first_seen TEXT NOT NULL, official_integer INTEGER NOT NULL,
 correction INTEGER NOT NULL, data_json TEXT NOT NULL, UNIQUE(prediction_id,report_identity));
CREATE INDEX IF NOT EXISTS continuous_settlement_prediction ON continuous_settlements(prediction_id);
CREATE INDEX IF NOT EXISTS continuous_prediction_target ON pws_predictions(airport_icao,target_time);
CREATE INDEX IF NOT EXISTS continuous_reference_target ON observations(station_icao,product_type,event_time);
CREATE INDEX IF NOT EXISTS continuous_prediction_match ON pws_predictions(airport_icao,substr(target_time,1,19));
CREATE INDEX IF NOT EXISTS continuous_observation_match ON observations(station_icao,substr(event_time,1,19),product_type);
CREATE TABLE IF NOT EXISTS continuous_cursor(experiment TEXT PRIMARY KEY,last_tick TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS continuous_experiments(experiment TEXT PRIMARY KEY,created_at TEXT NOT NULL,config_json TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS settlements_no_replace BEFORE INSERT ON continuous_settlements
 WHEN EXISTS(SELECT 1 FROM continuous_settlements WHERE prediction_id=NEW.prediction_id AND report_identity=NEW.report_identity)
 BEGIN SELECT RAISE(IGNORE); END;
CREATE TABLE IF NOT EXISTS continuous_polls(
 id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), provider TEXT NOT NULL,
 station_id TEXT NOT NULL REFERENCES pws_stations(station_id), at TEXT NOT NULL, duration_seconds REAL NOT NULL,
 new_observations INTEGER NOT NULL, duplicate_observations INTEGER NOT NULL, state TEXT NOT NULL, error_class TEXT);
CREATE TABLE IF NOT EXISTS continuous_health(
 run_id TEXT PRIMARY KEY REFERENCES runs(id), pid INTEGER NOT NULL, updated_at TEXT NOT NULL, data_json TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS settlements_no_update BEFORE UPDATE ON continuous_settlements
 BEGIN SELECT RAISE(ABORT,'Settlements are append-only'); END;
CREATE TRIGGER IF NOT EXISTS settlements_no_delete BEFORE DELETE ON continuous_settlements
 BEGIN SELECT RAISE(ABORT,'Settlements are append-only'); END;
"""


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    if conn.execute("SELECT max(version) FROM continuous_schema_version").fetchone()[0] != 1:
        raise RuntimeError("Unsupported continuous schema version")
    conn.commit()


def freeze_experiment(conn: sqlite3.Connection, config: Config) -> None:
    canonical = json.dumps(config.model_dump(mode="json"), sort_keys=True)
    if conn.execute(
        "SELECT 1 FROM continuous_experiments WHERE experiment!=?", (config.experiment,)
    ).fetchone():
        raise ValueError("A new experiment requires a separate database")
    previous = conn.execute(
        "SELECT config_json FROM continuous_experiments WHERE experiment=?", (config.experiment,)
    ).fetchone()
    if previous and previous[0] != canonical:
        raise ValueError("Experiment configuration changed; choose a new experiment ID/database")
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO continuous_experiments VALUES(?,?,?)",
            (config.experiment, utc_now().isoformat(), canonical),
        )


def routine_reports(conn: sqlite3.Connection, airport: str, at: datetime) -> list[dict[str, Any]]:
    # SQL only narrows search; exact aware comparisons preserve submillisecond availability.
    candidates = rows(
        conn,
        """SELECT * FROM observations WHERE station_icao=?
      AND product_type='METAR' AND evidence_class='REALTIME_CAPTURED'
      AND julianday(collector_receive_time)<=julianday(?) AND julianday(event_time)>=julianday(?)""",
        (airport, at.isoformat(), (at - timedelta(days=7)).isoformat()),
    )
    result = []
    for row in candidates:
        event, received = (
            datetime.fromisoformat(row["event_time"]),
            datetime.fromisoformat(row["collector_receive_time"]),
        )
        if (
            received <= at
            and event <= at
            and event.minute in STATIONS[airport].routine_minutes
            and event.second == 0
            and row["temperature_c"] is not None
        ):
            result.append(row)
    return sorted(
        result,
        key=lambda r: (
            datetime.fromisoformat(r["event_time"]),
            datetime.fromisoformat(r["collector_receive_time"]),
            r["id"],
        ),
    )


def baseline(
    conn: sqlite3.Connection,
    airport: str,
    target: datetime,
    method: str,
    run_id: str,
    checkpoint: str,
    reference_gate: ReferenceGate | None = None,
) -> dict[str, Any]:
    at = utc_now()
    known = rows(
        conn,
        "SELECT event_time,collector_receive_time FROM observations WHERE station_icao=? AND product_type='METAR' AND julianday(event_time)=julianday(?) AND julianday(collector_receive_time)<=julianday(?)",
        (airport, target.isoformat(), at.isoformat()),
    )
    if any(
        datetime.fromisoformat(r["event_time"]) == target
        and datetime.fromisoformat(r["collector_receive_time"]) <= at
        for r in known
    ):
        raise ValueError("TARGET_ALREADY_RECEIVED")
    reports = routine_reports(conn, airport, at)
    prior: dict[datetime, dict[str, Any]] = {}
    for r in reports:
        if datetime.fromisoformat(r["event_time"]) < target:
            prior[datetime.fromisoformat(r["event_time"])] = r
    ordered = sorted(prior.items())
    if not ordered:
        raise ValueError("INSUFFICIENT_PRIOR_METAR")
    event, last = ordered[-1]
    if at - event > timedelta(hours=2):
        raise ValueError("STALE_PRIOR_METAR")
    estimate = float(last["temperature_c"])
    inputs = [last["id"]]
    if method == "simple_recent_metar_trend":
        if len(ordered) < 2:
            raise ValueError("INSUFFICIENT_TREND_HISTORY")
        previous, prev = ordered[-2]
        gap = (event - previous).total_seconds()
        if gap > 3600:
            raise ValueError("TREND_GAP")
        estimate += (
            (estimate - float(prev["temperature_c"])) * (target - event).total_seconds() / gap
        )
        inputs.append(prev["id"])
    completed = utc_now()
    if target <= completed or any(
        datetime.fromisoformat(r["event_time"]) == target for r in reports
    ):
        raise ValueError("TARGET_ALREADY_KNOWN_OR_ELAPSED")
    result = dict(
        id=uuid4().hex,
        run_id=run_id,
        airport_icao=airport,
        created_at=completed.isoformat(),
        creation_monotonic_ns=time.perf_counter_ns(),
        decision_time=at.isoformat(),
        input_cutoff_time=at.isoformat(),
        target_time=target.isoformat(),
        estimate_c=estimate,
        integer_temperature=icao_round_temperature(estimate),
        method=method,
        checkpoint=checkpoint,
        input_observation_ids=inputs,
        station_count=0,
        algorithm_version=VERSION,
        evidence_class="REALTIME_CAPTURED",
        experiment_class="PRE_OBSERVATION",
        quality_flags=["QUANTIZED_METAR_REFERENCE"],
        clock_synchronization="UNVERIFIED",
    )
    first_received = first_target_receive(conn, airport, target)
    if first_received is not None and first_received <= completed:
        raise ValueError("TARGET_ALREADY_RECEIVED")
    if reference_gate is not None:
        reference_gate.check(airport)
    conn.execute(
        "INSERT INTO pws_predictions VALUES(?,?,?,?,?,?,?)",
        (
            result["id"],
            airport,
            result["created_at"],
            result["decision_time"],
            result["target_time"],
            VERSION,
            json.dumps(result),
        ),
    )
    return result


def schedule(
    conn: sqlite3.Connection,
    config: Config,
    run_id: str,
    now: datetime | None = None,
    reference_gate: ReferenceGate | None = None,
) -> None:
    at = utc(now or utc_now())
    hour = at.replace(minute=0, second=0, microsecond=0)
    cursor = conn.execute(
        "SELECT last_tick FROM continuous_cursor WHERE experiment=?", (config.experiment,)
    ).fetchone()
    previous = datetime.fromisoformat(cursor[0]) if cursor else None
    if previous and at < previous:
        raise RuntimeError("Wall clock regressed; scheduling suspended")
    start = (
        max(hour - timedelta(days=7), previous.replace(minute=0, second=0, microsecond=0))
        if previous
        else hour
    )
    hours = range(int((hour - start).total_seconds() // 3600) + 2)
    with conn:
        for airport in config.airports:
            # Include current hour's elapsed slots on restart; record missed rather than replay.
            targets = [
                start + timedelta(hours=h, minutes=m)
                for h in hours
                for m in STATIONS[airport].routine_minutes
            ]
            for target in targets:
                for seconds in config.checkpoints:
                    due = target - timedelta(seconds=seconds)
                    if due > at:
                        continue
                    for method in METHODS:
                        key = (config.experiment, airport, target.isoformat(), seconds, method)
                        if conn.execute(
                            "SELECT 1 FROM continuous_checkpoints WHERE experiment=? AND airport=? AND target=? AND checkpoint=? AND model=?",
                            key,
                        ).fetchone():
                            continue
                        status = "MISSED"
                        reason: str | None = (
                            "CHECKPOINT_ELAPSED"
                            if previous and due >= previous
                            else "STARTUP_ELAPSED"
                        )
                        pid: str | None = None
                        if (
                            0 <= (at - due).total_seconds() <= config.checkpoint_tolerance
                            and at < target
                        ):
                            # Never inject 'now' as creation time: actual completion clock is persisted.
                            try:
                                if reference_gate:
                                    reference_gate.check(airport)
                                if method in METHODS[:3]:
                                    result = baseline(
                                        conn,
                                        airport,
                                        target,
                                        method,
                                        run_id,
                                        f"T-{seconds}s",
                                        reference_gate,
                                    )
                                else:
                                    result = predict(
                                        conn,
                                        airport,
                                        target,
                                        config.qc,
                                        method,
                                        run_id=run_id,
                                        checkpoint=f"T-{seconds}s",
                                        reference_guard=partial(reference_gate.check, airport)
                                        if reference_gate
                                        else None,
                                    )
                                status, reason, pid = "GENERATED", None, result["id"]
                            except ValueError:
                                status, reason = "UNAVAILABLE", "NO_ELIGIBLE_INPUT_OR_TARGET_KNOWN"
                        conn.execute(
                            "INSERT INTO continuous_checkpoints VALUES(?,?,?,?,?,?,?,?,?)",
                            (*key, utc_now().isoformat(), status, reason, pid),
                        )

        conn.execute(
            "INSERT INTO continuous_cursor VALUES(?,?) ON CONFLICT(experiment) DO UPDATE SET last_tick=excluded.last_tick",
            (config.experiment, at.isoformat()),
        )


def settle(
    conn: sqlite3.Connection, at: datetime | None = None, after_observation_id: int = 0
) -> int:
    at = utc(at or utc_now())
    count = 0
    reference_cache: dict[str, list[dict[str, Any]]] = {}
    with conn:
        for item in rows(
            conn,
            """SELECT DISTINCT p.* FROM observations o JOIN pws_predictions p
            ON p.airport_icao=o.station_icao AND substr(p.target_time,1,19)=substr(o.event_time,1,19)
            WHERE o.product_type='METAR' AND (o.id>? OR NOT EXISTS(SELECT 1 FROM continuous_settlements cs WHERE cs.prediction_id=p.id)) AND julianday(p.target_time)<=julianday(?)""",
            (after_observation_id, at.isoformat()),
        ):
            forecast = json.loads(item["data_json"])
            strict_issues = exclude_prediction(conn, forecast)
            target = datetime.fromisoformat(item["target_time"])
            if item["airport_icao"] not in reference_cache:
                reference_cache[item["airport_icao"]] = routine_reports(
                    conn, item["airport_icao"], at
                )
            refs = [
                r
                for r in reference_cache[item["airport_icao"]]
                if datetime.fromisoformat(r["event_time"]) == target
            ]
            # Collapse repeated/source receipts by full report identity; first receipt never rewritten.
            identities: dict[str, list[dict[str, Any]]] = {}
            for r in refs:
                identities.setdefault(r["identity"], []).append(r)
            for identity, copies in identities.items():
                ref = min(copies, key=lambda r: datetime.fromisoformat(r["collector_receive_time"]))
                report_first = datetime.fromisoformat(ref["collector_receive_time"])
                first_copy = min(
                    refs, key=lambda r: datetime.fromisoformat(r["collector_receive_time"])
                )
                first = datetime.fromisoformat(first_copy["collector_receive_time"])
                ambiguous = (
                    len(
                        {
                            float(r["temperature_c"])
                            for r in refs
                            if not json.loads(r["data_json"]).get("cor", False)
                        }
                    )
                    > 1
                )
                created = datetime.fromisoformat(item["created_at"])
                official = icao_round_temperature(float(ref["temperature_c"]))
                lead = (first - created).total_seconds()
                monotonic_lead = (
                    (first_copy["receive_monotonic_ns"] - forecast["creation_monotonic_ns"]) / 1e9
                    if first_copy["run_id"] == forecast.get("run_id")
                    and first_copy["receive_monotonic_ns"] is not None
                    and forecast.get("creation_monotonic_ns") is not None
                    else None
                )
                correction = bool(json.loads(ref["data_json"]).get("cor", False))
                result = dict(
                    prediction_id=item["id"],
                    report_identity=identity,
                    official_integer=official,
                    integer_error=forecast["integer_temperature"] - official,
                    continuous_interval_error=max(0, abs(forecast["estimate_c"] - official) - 0.5),
                    reference_first_seen=first.isoformat(),
                    lead_seconds=lead if lead > 0 else None,
                    within_run_monotonic_lead_seconds=monotonic_lead,
                    utc_wall_lead_seconds=lead,
                    lead_status="RELATIVE_TO_OUR_COLLECTOR_CLOCK_UNVERIFIED"
                    if lead > 0
                    else "NO_POSITIVE_LEAD",
                    startup_censored=bool(first_copy["startup_censored"]),
                    coverage_gap=bool(first_copy["coverage_gap"]),
                    experiment_class="PRE_OBSERVATION" if created < target else "POST_OBSERVATION",
                    valid_prospective=created < first
                    and created < target
                    and not ambiguous
                    and not strict_issues,
                    timestamp_integrity_rejections=strict_issues,
                    ambiguous_initial_reports=ambiguous,
                    report_version_first_seen=report_first.isoformat(),
                    correction=correction,
                    reference_observation_id=ref["id"],
                    reference_scope="FIRST_RECEIPT_AMONG_CONFIGURED_SOURCES_NOT_GLOBAL_PUBLICATION",
                )
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO continuous_settlements VALUES(NULL,?,?,?,?,?,?,?)",
                    (
                        item["id"],
                        identity,
                        at.isoformat(),
                        first.isoformat(),
                        official,
                        int(correction),
                        json.dumps(result),
                    ),
                )
                count += cursor.rowcount
    return count
