"""Actual sensor availability, append-only checks and prospective selection versions."""

import json
import sqlite3
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from premetar.model import utc_now
from premetar.pws.geometry import haversine_km
from premetar.pws.models import Reading, Station
from premetar.pws.recovery_state import transition
from premetar.pws.repository import parameter_available, rows
from premetar.pws.timestamps import assess_time, parse_utc
from premetar.pws.timestamps import policy as timestamp_policy


class AvailabilityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    version: str = "active-sensors-1.0"
    max_preflight_stations_per_airport: int = Field(default=200, ge=1, le=500)
    minimum_station_separation_km: float = Field(default=0.2, ge=0, le=5)
    radius_km: float = Field(default=20, gt=0, le=50)
    maximum_age_seconds: float = Field(default=300, gt=0, le=300)
    max_stations_per_airport: int = Field(default=4, ge=1, le=20)
    max_sensors_per_airport: int = Field(default=4, ge=1, le=40)
    max_sensors_per_station: int = Field(default=1, ge=1, le=2)
    request_spacing_seconds: float = Field(default=2, ge=1, le=30)
    inactive_recheck_seconds: float = Field(default=1800, ge=900)
    recovery_confirm_seconds: float = Field(default=300, ge=300)
    candidate_refresh_seconds: float = Field(default=3600, ge=900)
    failures_to_inactive: int = Field(default=3, ge=2, le=10)
    recoveries_to_active: int = Field(default=2, ge=2, le=10)


@lru_cache(maxsize=1)
def policy() -> AvailabilityPolicy:
    p = Path("configs/availability-v1.json")
    return (
        AvailabilityPolicy.model_validate_json(p.read_text(encoding="utf-8"))
        if p.exists()
        else AvailabilityPolicy()
    )


SCHEMA = """
CREATE TABLE IF NOT EXISTS availability_schema_version(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO availability_schema_version VALUES(1);
CREATE TABLE IF NOT EXISTS pws_availability_policies(version TEXT PRIMARY KEY,created_at TEXT NOT NULL,data_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pws_sensor_checks(
 id INTEGER PRIMARY KEY,run_id TEXT NOT NULL REFERENCES runs(id),sensor_id TEXT NOT NULL REFERENCES pws_sensors(sensor_id),
 station_id TEXT NOT NULL REFERENCES pws_stations(station_id),airport_icao TEXT NOT NULL REFERENCES pws_airports(icao),
 checked_at TEXT NOT NULL,status TEXT NOT NULL,outcome TEXT NOT NULL,
 raw_id TEXT REFERENCES raw_payloads(id),observation_id TEXT REFERENCES pws_observations(id),data_json TEXT NOT NULL,
 UNIQUE(sensor_id,airport_icao,raw_id));
CREATE INDEX IF NOT EXISTS availability_latest ON pws_sensor_checks(airport_icao,sensor_id,id);
CREATE TABLE IF NOT EXISTS pws_sensor_state(
 sensor_id TEXT PRIMARY KEY REFERENCES pws_sensors(sensor_id),checked_at TEXT NOT NULL,status TEXT NOT NULL,
 mode TEXT NOT NULL,data_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pws_selection_versions(
 id INTEGER PRIMARY KEY,airport_icao TEXT NOT NULL REFERENCES pws_airports(icao),provider TEXT NOT NULL,
 created_at TEXT NOT NULL,policy_version TEXT NOT NULL REFERENCES pws_availability_policies(version),
 reason TEXT NOT NULL,data_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS sensor_selection_asof ON pws_selection_versions(airport_icao,provider,created_at);
CREATE TABLE IF NOT EXISTS pws_preflight_runs(
 id INTEGER PRIMARY KEY,run_id TEXT NOT NULL REFERENCES runs(id),airport_icao TEXT NOT NULL,completed_at TEXT NOT NULL,data_json TEXT NOT NULL);
"""


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    if conn.execute("SELECT max(version) FROM availability_schema_version").fetchone()[0] != 1:
        raise RuntimeError("Unsupported availability schema")
    for table in (
        "pws_sensor_checks",
        "pws_selection_versions",
        "pws_preflight_runs",
        "pws_availability_policies",
    ):
        key = "version" if table == "pws_availability_policies" else "id"
        conn.executescript(f"""CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table}
        BEGIN SELECT RAISE(ABORT,'Availability history is append-only'); END;
        CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table}
        BEGIN SELECT RAISE(ABORT,'Availability history is append-only'); END;
        CREATE TRIGGER IF NOT EXISTS {table}_no_replace BEFORE INSERT ON {table}
        WHEN EXISTS(SELECT 1 FROM {table} WHERE {key}=NEW.{key})
        BEGIN SELECT RAISE(IGNORE); END;""")
    canonical = json.dumps(policy().model_dump(), sort_keys=True)
    old = conn.execute(
        "SELECT data_json FROM pws_availability_policies WHERE version=?", (policy().version,)
    ).fetchone()
    if old and old[0] != canonical:
        raise ValueError("Availability policy changed without version increment")
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO pws_availability_policies VALUES(?,?,?)",
            (policy().version, utc_now().isoformat(), canonical),
        )


def classify(
    station: Station, reading: Reading | None, received: datetime, at: datetime | None = None
) -> tuple[str, dict[str, Any]]:
    r = reading.model_dump(mode="json") if reading else {}
    r.update(
        provider=station.provider,
        station_id=station.station_id,
        first_receive_time=received.isoformat(),
        evidence_class="REALTIME_CAPTURED",
        exposure=station.exposure,
        mobile=station.mobile,
    )
    check = assess_time(r, at or received, maximum_age=policy().maximum_age_seconds)
    if reading is None or (reading.temperature_c is None and reading.raw_temperature in (None, "")):
        status = "NO_MEASUREMENT"
    elif "IMPLAUSIBLE_TEMPERATURE" in check.reasons:
        status = "INVALID"
    elif check.status == "STALE":
        status = "STALE"
    elif check.status == "UNKNOWN_TIMESTAMP_PROVENANCE":
        status = "UNVERIFIED"
    elif not check.eligible:
        status = "INVALID"
    elif station.exposure != "outdoor":
        status = "UNVERIFIED"
    else:
        status = "ACTIVE"
    reasons = list(check.reasons)
    if station.exposure not in ("outdoor", "indoor"):
        reasons.append("EXPOSURE_UNVERIFIED")
    r.update(
        measurement_time=r.get("observation_time"),
        age_seconds=check.age_at_receipt_seconds,
        reasons=sorted(set(reasons)),
        timestamp_policy_version=timestamp_policy().version,
    )
    return status, r


def record_check(
    conn: sqlite3.Connection,
    run_id: str,
    airport: str,
    station: Station,
    sensor_id: str,
    reading: Reading | None,
    packet: dict[str, Any] | None,
    context: str,
    observation_id: str | None = None,
    is_new: bool = False,
    error: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    at = parse_utc(now or utc_now())
    assert at is not None
    received = parse_utc(packet["received_at"]) if packet else at
    assert received is not None
    status, data = classify(station, reading, received, at)
    if error:
        status = "UNVERIFIED"
        data["reasons"] = [error]
    if packet:
        prior_check = rows(
            conn,
            "SELECT * FROM pws_sensor_checks WHERE sensor_id=? AND airport_icao=? AND raw_id=?",
            (sensor_id, airport, packet["id"]),
        )
        if prior_check:
            old_data = json.loads(prior_check[0]["data_json"])
            return dict(
                sensor_id=sensor_id,
                status=prior_check[0]["status"],
                outcome=prior_check[0]["outcome"],
                **old_data,
            )
    previous = conn.execute(
        "SELECT data_json FROM pws_sensor_state WHERE sensor_id=?", (sensor_id,)
    ).fetchone()
    old = json.loads(previous[0]) if previous else None
    state = transition(
        old, status, at, policy().failures_to_inactive, policy().recoveries_to_active
    )
    # A second request seconds later must not defeat recovery hysteresis.
    if old and old["mode"] == "INACTIVE" and status == "ACTIVE" and old.get("good_streak", 0):
        elapsed = (at - datetime.fromisoformat(old["last_checked"])).total_seconds()
        if elapsed < policy().recovery_confirm_seconds:
            state.update(mode="INACTIVE", good_streak=old["good_streak"])
    state["last_usable_at"] = (
        at.isoformat() if status == "ACTIVE" else (old or {}).get("last_usable_at")
    )
    outcome = (
        "PROVIDER_ERROR"
        if error
        else "NO_MEASUREMENT"
        if status == "NO_MEASUREMENT"
        else "STALE_MEASUREMENT"
        if status == "STALE"
        else "INVALID_MEASUREMENT"
        if status != "ACTIVE"
        else "SUCCESS_NEW_MEASUREMENT"
        if is_new
        else "SUCCESS_UNCHANGED_MEASUREMENT"
    )
    data.update(
        state,
        context=context,
        http_status=packet.get("http_status") if packet else None,
        request_start=packet.get("request_start") if packet else None,
        request_end=packet.get("request_end") if packet else None,
        raw_id=packet.get("id") if packet else None,
        observation_id=observation_id,
        policy_version=policy().version,
    )
    raw_id = packet.get("id") if packet else None
    with conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO pws_sensor_checks VALUES(NULL,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                sensor_id,
                station.station_id,
                airport,
                at.isoformat(),
                status,
                outcome,
                raw_id,
                observation_id,
                json.dumps(data),
            ),
        )
        if cur.rowcount:
            conn.execute(
                "INSERT INTO pws_sensor_state VALUES(?,?,?,?,?) ON CONFLICT(sensor_id) DO UPDATE SET checked_at=excluded.checked_at,status=excluded.status,mode=excluded.mode,data_json=excluded.data_json",
                (sensor_id, at.isoformat(), status, state["mode"], json.dumps(data)),
            )
    return dict(sensor_id=sensor_id, status=status, outcome=outcome, **data)


def selection_at(
    conn: sqlite3.Connection, airport: str, provider: str, at: datetime
) -> dict[str, Any] | None:
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='pws_selection_versions'"
    ).fetchone():
        return None
    found = rows(
        conn,
        "SELECT * FROM pws_selection_versions WHERE airport_icao=? AND provider=? AND julianday(created_at)<=julianday(?) ORDER BY id DESC",
        (airport, provider, at.isoformat()),
    )
    return next((r for r in found if datetime.fromisoformat(r["created_at"]) <= at), None)


def measurement_clocks(conn: sqlite3.Connection, sensor_id: str, at: datetime) -> list[datetime]:
    """Only clocks that were usable at first receipt estimate sensor cadence."""
    found = rows(
        conn,
        """SELECT o.*,s.station_id,st.provider,s.provider_sensor_id
        FROM pws_observations o JOIN pws_sensors s USING(sensor_id)
        JOIN pws_stations st USING(station_id) WHERE o.sensor_id=?
        AND o.first_receive_time<=? AND o.temperature_c IS NOT NULL
        AND o.observation_time IS NOT NULL ORDER BY o.observation_time DESC LIMIT 50""",
        (sensor_id, at.isoformat()),
    )
    clocks = set()
    for row in found:
        data = {**row, **json.loads(row["data_json"])}
        received = parse_utc(row["first_receive_time"])
        if received and received <= at and assess_time(data, received).eligible:
            event = parse_utc(row["observation_time"])
            if event:
                clocks.add(event)
    return sorted(clocks, reverse=True)


def candidates(conn: sqlite3.Connection, airport: str, at: datetime) -> list[dict[str, Any]]:
    data = rows(
        conn,
        """SELECT c.*,a.distance_km,s.data_json station_json FROM pws_sensor_checks c
        JOIN pws_airport_stations a ON a.station_id=c.station_id AND a.airport_icao=c.airport_icao
        JOIN pws_stations s ON s.station_id=c.station_id WHERE c.airport_icao=? AND c.id=(SELECT max(n.id) FROM pws_sensor_checks n WHERE n.sensor_id=c.sensor_id AND n.airport_icao=c.airport_icao AND julianday(n.checked_at)<=julianday(?) AND n.checked_at<=?)
        AND julianday(c.checked_at)<=julianday(?)""",
        (airport, at.isoformat(), at.isoformat(), at.isoformat()),
    )
    result = []
    for row in data:
        d = json.loads(row["data_json"])
        station = Station.model_validate_json(row["station_json"])
        valid = (
            row["status"] == "ACTIVE"
            and d["mode"] == "ACTIVE"
            and row["distance_km"] <= policy().radius_km
            and assess_time(d, at, maximum_age=policy().maximum_age_seconds).eligible
        )
        # Cadence is estimated from prior unique event times, never HTTP intervals/outcomes.
        clocks = measurement_clocks(conn, row["sensor_id"], at)
        intervals = sorted(
            (a - b).total_seconds() for a, b in zip(clocks, clocks[1:], strict=False) if a > b
        )
        cadence = intervals[len(intervals) // 2] if len(intervals) >= 3 else None
        last = conn.execute(
            "SELECT selected,reason FROM pws_selections WHERE station_id=? AND airport_icao=? AND created_at<=? ORDER BY id DESC LIMIT 1",
            (station.station_id, airport, at.isoformat()),
        ).fetchone()
        manual_excluded = bool(last and not last[0] and not last[1].startswith("AUTO_AVAILABILITY"))
        quality = rows(
            conn,
            "SELECT data_json FROM pws_quality_results WHERE station_id=? AND airport_icao=? AND created_at<=? ORDER BY created_at DESC,id DESC LIMIT 1",
            (station.station_id, airport, at.isoformat()),
        )
        qc = json.loads(quality[0]["data_json"]) if quality else {}
        if qc and not parameter_available(conn, qc, at):
            qc = {}
        operational_qc = None
        if (
            qc.get("timestamp_policy_version") == timestamp_policy().version
            and qc.get("sample_count", 0) >= 100
        ):
            operational_qc = qc.get("components", {}).get("temporal")
            if "STUCK_SENSOR" in qc.get("flags", []):
                valid = False
        metadata_confidence = sum(
            bool(v)
            for sensor in station.sensors
            for v in (sensor.sensor_type, sensor.sensor_model, sensor.manufacturer)
        )
        row.update(
            operational_qc=operational_qc,
            metadata_confidence=metadata_confidence,
            data=d,
            eligible=valid and not manual_excluded,
            station=station,
            cadence_seconds=cadence,
            manual_excluded=manual_excluded,
        )
        result.append(row)
    return result


def reconcile(conn: sqlite3.Connection, airport: str, at: datetime | None = None) -> int:
    at = at or utc_now()
    previous = selection_at(conn, airport, "opensensemap", at)
    old = json.loads(previous["data_json"]) if previous else {}
    prior_ids = set(old.get("selected_sensor_ids", []))
    pool = candidates(conn, airport, at)

    def retained(r: dict[str, Any]) -> bool:
        usable = parse_utc(r["data"].get("last_usable_at"))
        return bool(
            r["sensor_id"] in prior_ids
            and r["data"]["mode"] == "ACTIVE"
            and not r["manual_excluded"]
            and r["distance_km"] <= policy().radius_km
            and usable is not None
            and (at - usable).total_seconds() < policy().inactive_recheck_seconds
        )

    # Keep existing members during the bounded failure streak; no selection by target outcomes.
    def rank(r: dict[str, Any]) -> tuple[Any, ...]:
        held = retained(r)
        return (
            not held,
            not r["eligible"],
            r["data"].get("age_seconds") or 0,
            r["cadence_seconds"] or 3600,
            -(r["operational_qc"] if r["operational_qc"] is not None else 50),
            r["distance_km"],
            -r["metadata_confidence"],
            r["sensor_id"],
        )

    chosen: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for row in sorted(pool, key=rank):
        held = retained(row)
        if not row["eligible"] and not held:
            continue
        sid = row["station_id"]
        if (
            len(chosen) >= policy().max_sensors_per_airport
            or counts.get(sid, 0) >= policy().max_sensors_per_station
        ):
            continue
        if sid not in counts and len(counts) >= policy().max_stations_per_airport:
            continue
        if any(
            haversine_km(
                row["station"].latitude,
                row["station"].longitude,
                other["station"].latitude,
                other["station"].longitude,
            )
            < policy().minimum_station_separation_km
            for other in chosen
            if other["station_id"] != sid
        ):
            continue
        chosen.append(row)
        counts[sid] = counts.get(sid, 0) + 1
    sensor_ids = sorted(r["sensor_id"] for r in chosen)
    if previous and sensor_ids == sorted(prior_ids):
        return int(previous["id"])
    rationale = {
        r[
            "sensor_id"
        ]: f"Actual latest check {r['id']}; availability {r['status']}; age {r['data'].get('age_seconds')}s; cadence {r['cadence_seconds']}; distance {r['distance_km']:.3f}km; bounded hysteresis; no predictive outcome selection"
        for r in chosen
    }
    data = dict(
        selected_sensor_ids=sensor_ids,
        selected_station_ids=sorted(counts),
        rationale=rationale,
        previous_version_id=previous["id"] if previous else None,
        policy=policy().model_dump(),
        timestamp_policy_version=timestamp_policy().version,
    )
    with conn:
        cursor = conn.execute(
            "INSERT INTO pws_selection_versions VALUES(NULL,?,?,?,?,?,?)",
            (
                airport,
                "opensensemap",
                at.isoformat(),
                policy().version,
                "ACTIVE_PREFLIGHT_AND_HYSTERESIS",
                json.dumps(data),
            ),
        )
        version = int(cursor.lastrowid or 0)
        stations = rows(
            conn,
            "SELECT s.station_id FROM pws_stations s JOIN pws_airport_stations a USING(station_id) WHERE a.airport_icao=? AND s.provider='opensensemap'",
            (airport,),
        )
        for station in stations:
            last = conn.execute(
                "SELECT selected,reason FROM pws_selections WHERE station_id=? AND airport_icao=? ORDER BY id DESC LIMIT 1",
                (station["station_id"], airport),
            ).fetchone()
            wanted = int(station["station_id"] in counts)
            if (last and not last[0] and not last[1].startswith("AUTO_AVAILABILITY")) or (
                bool(last and last[0]) == bool(wanted)
            ):
                continue
            conn.execute(
                "INSERT INTO pws_selections VALUES(NULL,?,?,?,?,?)",
                (
                    station["station_id"],
                    airport,
                    at.isoformat(),
                    int(station["station_id"] in counts),
                    f"AUTO_AVAILABILITY version={version}",
                ),
            )
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='continuous_experiments'"
        ).fetchone():
            experiment = conn.execute(
                "SELECT experiment FROM continuous_experiments ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if experiment:
                for sid in counts:
                    conn.execute(
                        "INSERT OR IGNORE INTO continuous_cohort VALUES(?,?,?,?,?)",
                        (
                            experiment[0],
                            airport,
                            sid,
                            at.isoformat(),
                            f"AUTO_AVAILABILITY version={version}",
                        ),
                    )
    return version
