"""Additive quarantine/exclusion ledger; original observations/forecasts stay immutable."""

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from typing import Any

from premetar.model import utc_now
from premetar.pws.timestamps import assess_time, parse_utc, policy

SCHEMA = """
CREATE TABLE IF NOT EXISTS timestamp_schema_version(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO timestamp_schema_version VALUES(1);
CREATE TABLE IF NOT EXISTS timestamp_policies(version TEXT PRIMARY KEY,activated_at TEXT NOT NULL,data_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pws_observation_integrity(
 observation_id TEXT NOT NULL REFERENCES pws_observations(id),policy_version TEXT NOT NULL REFERENCES timestamp_policies(version),
 checked_at TEXT NOT NULL,status TEXT NOT NULL,provenance TEXT NOT NULL,reasons_json TEXT NOT NULL,data_json TEXT NOT NULL,
 PRIMARY KEY(observation_id,policy_version));
CREATE INDEX IF NOT EXISTS integrity_status ON pws_observation_integrity(policy_version,status);
CREATE TABLE IF NOT EXISTS prediction_exclusions(
 prediction_id TEXT NOT NULL REFERENCES pws_predictions(id),policy_version TEXT NOT NULL REFERENCES timestamp_policies(version),
 reason TEXT NOT NULL,input_id TEXT NOT NULL,recorded_at TEXT NOT NULL,
 PRIMARY KEY(prediction_id,policy_version,reason,input_id));
CREATE TRIGGER IF NOT EXISTS exclusions_immutable_update BEFORE UPDATE ON prediction_exclusions
 BEGIN SELECT RAISE(ABORT,'Exclusions are append-only'); END;
CREATE TRIGGER IF NOT EXISTS exclusions_immutable_delete BEFORE DELETE ON prediction_exclusions
 BEGIN SELECT RAISE(ABORT,'Exclusions are append-only'); END;
CREATE TRIGGER IF NOT EXISTS exclusions_no_replace BEFORE INSERT ON prediction_exclusions
 WHEN EXISTS(SELECT 1 FROM prediction_exclusions WHERE prediction_id=NEW.prediction_id AND policy_version=NEW.policy_version AND reason=NEW.reason AND input_id=NEW.input_id)
 BEGIN SELECT RAISE(IGNORE); END;
"""


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    if conn.execute("SELECT max(version) FROM timestamp_schema_version").fetchone()[0] != 1:
        raise RuntimeError("Unsupported timestamp schema")
    canonical = json.dumps(asdict(policy()), sort_keys=True)
    previous = conn.execute(
        "SELECT data_json FROM timestamp_policies WHERE version=?", (policy().version,)
    ).fetchone()
    if previous and previous[0] != canonical:
        raise ValueError("Timestamp policy changed without a new algorithm version")
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO timestamp_policies VALUES(?,?,?)",
            (policy().version, utc_now().isoformat(), canonical),
        )


def observation(conn: sqlite3.Connection, identity: str) -> dict[str, Any] | None:
    cursor = conn.execute(
        """SELECT o.*,s.station_id,s.provider_sensor_id,st.provider
        FROM pws_observations o JOIN pws_sensors s USING(sensor_id)
        JOIN pws_stations st USING(station_id) WHERE o.id=?""",
        (identity,),
    )
    r = cursor.fetchone()
    return _merged(cursor.description, r)


def _merged(description: Any, row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(zip([c[0] for c in description], row, strict=True))
    return {**data, **json.loads(data["data_json"])}


def record_observation(conn: sqlite3.Connection, identity: str) -> None:
    row = observation(conn, identity)
    if row is None:
        raise ValueError("Unknown normalized observation")
    check = assess_time(row)
    conn.execute(
        "INSERT OR IGNORE INTO pws_observation_integrity VALUES(?,?,?,?,?,?,?)",
        (
            identity,
            policy().version,
            utc_now().isoformat(),
            check.status,
            check.timestamp_provenance,
            json.dumps(check.reasons),
            json.dumps(check.json_data()),
        ),
    )


def first_target_receive(
    conn: sqlite3.Connection, airport: str, target: datetime
) -> datetime | None:
    values = []
    for event, received in conn.execute(
        """SELECT o.event_time,r.collector_receive_time
       FROM observations o JOIN report_receipts r ON r.observation_id=o.id
       WHERE o.station_icao=? AND o.product_type='METAR' AND julianday(o.event_time)=julianday(?)""",
        (airport, target.isoformat()),
    ):
        try:
            if parse_utc(event) == target and (clock := parse_utc(received)) is not None:
                values.append(clock)
        except (ValueError, TypeError, OverflowError):
            continue
    return min(values) if values else None


def prediction_issues(
    conn: sqlite3.Connection, prediction: dict[str, Any]
) -> list[tuple[str, str]]:
    reasons = []
    try:
        created = parse_utc(prediction.get("created_at"))
        cutoff = parse_utc(prediction.get("input_cutoff_time") or prediction.get("decision_time"))
        target = parse_utc(prediction.get("target_time"))
    except (ValueError, TypeError, OverflowError):
        return [("INVALID_PREDICTION_CLOCK", "")]
    if not created or not cutoff or not target or cutoff > created:
        return [("INVALID_PREDICTION_CLOCK", "")]
    if created >= target:
        reasons.append(("NOT_PRE_OBSERVATION", ""))
    first = first_target_receive(conn, prediction["airport_icao"], target)
    if first is not None and created >= first:
        reasons.append(("TARGET_ALREADY_RECEIVED", ""))
    inputs = prediction.get("input_observation_ids") or [
        c["observation_id"] for c in prediction.get("contributions", [])
    ]
    for identity in inputs:
        if isinstance(identity, int):
            r = conn.execute(
                "SELECT collector_receive_time,event_time FROM observations WHERE id=?", (identity,)
            ).fetchone()
            try:
                received = parse_utc(r[0]) if r else None
                event = parse_utc(r[1]) if r else None
                if received is None or event is None or received > cutoff or event > cutoff:
                    reasons.append(("INVALID_OFFICIAL_INPUT_CLOCK", str(identity)))
            except (ValueError, TypeError, OverflowError):
                reasons.append(("INVALID_OFFICIAL_INPUT_CLOCK", str(identity)))
            continue
        row = observation(conn, str(identity))
        if row is None:
            reasons.append(("MISSING_INPUT", str(identity)))
        else:
            check = assess_time(row, cutoff)
            if not check.eligible:
                reasons.extend((reason, str(identity)) for reason in check.reasons)
    from premetar.pws.repository import parameter_available

    for c in prediction.get("contributions", []):
        for key, table in (
            ("calibration_id", "pws_calibrations"),
            ("quality_id", "pws_quality_results"),
        ):
            if c.get(key) is not None:
                parameter = conn.execute(
                    f"SELECT data_json FROM {table} WHERE id=?", (c[key],)
                ).fetchone()
                if (
                    not parameter
                    or json.loads(parameter[0]).get("timestamp_policy_version") != policy().version
                ):
                    reasons.append(("UNVERIFIED_PARAMETER_TIMESTAMP_POLICY", f"{key}:{c[key]}"))
                elif not parameter_available(conn, json.loads(parameter[0]), cutoff):
                    reasons.append(("QC_PARAMETER_NOT_COMMITTED_AT_CUTOFF", f"{key}:{c[key]}"))
    return sorted(set(reasons))


def exclude_prediction(
    conn: sqlite3.Connection, prediction: dict[str, Any]
) -> list[tuple[str, str]]:
    reasons = prediction_issues(conn, prediction)
    for reason, identity in reasons:
        conn.execute(
            "INSERT OR IGNORE INTO prediction_exclusions VALUES(?,?,?,?,?)",
            (prediction["id"], policy().version, reason, identity, utc_now().isoformat()),
        )
    return reasons


def backfill(conn: sqlite3.Connection) -> dict[str, int]:
    migrate(conn)
    with conn:
        for (identity,) in conn.execute(
            """SELECT id FROM pws_observations WHERE NOT EXISTS(
            SELECT 1 FROM pws_observation_integrity i WHERE i.observation_id=pws_observations.id AND i.policy_version=?)""",
            (policy().version,),
        ).fetchall():
            record_observation(conn, identity)
        for (data,) in conn.execute("SELECT data_json FROM pws_predictions").fetchall():
            exclude_prediction(conn, json.loads(data))
    return dict(
        observations=conn.execute(
            "SELECT count(*) FROM pws_observation_integrity WHERE policy_version=?",
            (policy().version,),
        ).fetchone()[0],
        excluded_predictions=conn.execute(
            "SELECT count(DISTINCT prediction_id) FROM prediction_exclusions WHERE policy_version=?",
            (policy().version,),
        ).fetchone()[0],
    )
