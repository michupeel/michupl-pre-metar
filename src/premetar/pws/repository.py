"""Additive PWS extension, sharing Store's single disk worker and raw envelopes."""

import hashlib
import json
import sqlite3
from datetime import datetime
from typing import Any

from premetar.pws.geometry import haversine_km
from premetar.pws.models import Airport, Reading, Station
from premetar.store import Store

SCHEMA = """
CREATE TABLE IF NOT EXISTS pws_schema_version(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO pws_schema_version VALUES(1);
CREATE TABLE IF NOT EXISTS pws_providers(name TEXT PRIMARY KEY, capabilities_json TEXT NOT NULL, status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pws_airports(icao TEXT PRIMARY KEY, data_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pws_stations(
 station_id TEXT PRIMARY KEY, provider TEXT NOT NULL REFERENCES pws_providers(name),
 provider_station_id TEXT NOT NULL, first_discovered_at TEXT NOT NULL, last_discovered_at TEXT NOT NULL,
 data_json TEXT NOT NULL, UNIQUE(provider,provider_station_id));
CREATE TABLE IF NOT EXISTS pws_airport_stations(
 station_id TEXT NOT NULL REFERENCES pws_stations(station_id),
 airport_icao TEXT NOT NULL REFERENCES pws_airports(icao), distance_km REAL NOT NULL,
 PRIMARY KEY(station_id,airport_icao));
CREATE TABLE IF NOT EXISTS pws_sensors(
 sensor_id TEXT PRIMARY KEY, station_id TEXT NOT NULL REFERENCES pws_stations(station_id),
 provider_sensor_id TEXT NOT NULL, data_json TEXT NOT NULL, UNIQUE(station_id,provider_sensor_id));
CREATE TABLE IF NOT EXISTS pws_discoveries(
 id INTEGER PRIMARY KEY, station_id TEXT NOT NULL REFERENCES pws_stations(station_id),
 airport_icao TEXT NOT NULL REFERENCES pws_airports(icao), at TEXT NOT NULL,
 raw_id TEXT NOT NULL REFERENCES raw_payloads(id), distance_km REAL NOT NULL, data_json TEXT NOT NULL,
 UNIQUE(station_id,airport_icao,raw_id));
CREATE TABLE IF NOT EXISTS pws_observations(
 id TEXT PRIMARY KEY, sensor_id TEXT NOT NULL REFERENCES pws_sensors(sensor_id),
 observation_time TEXT, source_publish_time TEXT, temperature_c REAL, first_receive_time TEXT,
 evidence_class TEXT NOT NULL CHECK(evidence_class IN ('REALTIME_CAPTURED','HISTORICAL_EVENT_ONLY')),
 data_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pws_arrivals(
 observation_id TEXT NOT NULL REFERENCES pws_observations(id), raw_id TEXT NOT NULL REFERENCES raw_payloads(id),
 received_at TEXT NOT NULL, request_start TEXT NOT NULL, request_end TEXT NOT NULL,
 startup_censored INTEGER NOT NULL, PRIMARY KEY(observation_id,raw_id));
CREATE INDEX IF NOT EXISTS pws_sensor_time ON pws_observations(sensor_id,observation_time);
CREATE INDEX IF NOT EXISTS pws_available ON pws_observations(first_receive_time);
CREATE TABLE IF NOT EXISTS pws_quality_results(
 id INTEGER PRIMARY KEY, station_id TEXT NOT NULL REFERENCES pws_stations(station_id),
 airport_icao TEXT NOT NULL REFERENCES pws_airports(icao), created_at TEXT NOT NULL,
 algorithm_version TEXT NOT NULL, data_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pws_calibrations(
 id INTEGER PRIMARY KEY, station_id TEXT NOT NULL REFERENCES pws_stations(station_id),
 airport_icao TEXT NOT NULL REFERENCES pws_airports(icao), created_at TEXT NOT NULL,
 trained_through TEXT NOT NULL, data_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pws_selections(
 id INTEGER PRIMARY KEY, station_id TEXT NOT NULL REFERENCES pws_stations(station_id),
 airport_icao TEXT NOT NULL REFERENCES pws_airports(icao), created_at TEXT NOT NULL,
 selected INTEGER NOT NULL, reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pws_predictions(
 id TEXT PRIMARY KEY, airport_icao TEXT NOT NULL REFERENCES pws_airports(icao),
 created_at TEXT NOT NULL, decision_time TEXT NOT NULL, target_time TEXT NOT NULL,
 algorithm_version TEXT NOT NULL, data_json TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS pws_predictions_immutable_update BEFORE UPDATE ON pws_predictions
 BEGIN SELECT RAISE(ABORT,'Historical predictions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS pws_predictions_immutable_delete BEFORE DELETE ON pws_predictions
 BEGIN SELECT RAISE(ABORT,'Historical predictions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS pws_predictions_immutable_insert BEFORE INSERT ON pws_predictions
 WHEN EXISTS(SELECT 1 FROM pws_predictions WHERE id=NEW.id)
 BEGIN SELECT RAISE(ABORT,'Historical predictions are immutable'); END;
CREATE VIEW IF NOT EXISTS pws_observation_provenance AS
 SELECT o.*,s.station_id,st.provider,ap.airport_icao,a.raw_id,
 a.received_at collector_receive_time,a.request_start collector_request_start_time,
 a.request_end collector_request_end_time,r.sha256 raw_payload_hash,
 a.startup_censored,r.run_id,r.monotonic_ns
 FROM pws_observations o JOIN pws_sensors s USING(sensor_id)
 JOIN pws_stations st USING(station_id) JOIN pws_airport_stations ap USING(station_id)
 JOIN pws_arrivals a ON a.observation_id=o.id JOIN raw_payloads r ON r.id=a.raw_id;
"""


def sensor_key(station_id: str, provider_sensor_id: str) -> str:
    return station_id + ":" + provider_sensor_id


class PWSStore(Store):
    def _open(self, manifest: dict[str, Any], intervals: dict[str, float]) -> None:
        super()._open(manifest, intervals)
        self.connection.executescript(SCHEMA)
        if (
            self.connection.execute("SELECT max(version) FROM pws_schema_version").fetchone()[0]
            != 1
        ):
            raise RuntimeError("Unsupported PWS extension version")
        from premetar.pws.integrity import backfill

        backfill(self.connection)

    def register(self, airports: list[Airport], providers: list[Any]) -> None:
        with self.connection:
            for airport in airports:
                self.connection.execute(
                    "INSERT INTO pws_airports VALUES(?,?) ON CONFLICT(icao) DO UPDATE SET data_json=excluded.data_json",
                    (airport.icao, airport.model_dump_json()),
                )
            for provider in providers:
                self.connection.execute(
                    "INSERT INTO pws_providers VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET capabilities_json=excluded.capabilities_json,status=excluded.status",
                    (provider.name, provider.capabilities.model_dump_json(), provider.status),
                )

    def discover(self, airport: Airport, station: Station, packet: dict[str, Any]) -> None:
        distance = haversine_km(
            airport.latitude, airport.longitude, station.latitude, station.longitude
        )
        at, data = packet["received_at"], station.model_dump_json()
        with self.connection:
            self.connection.execute(
                "INSERT INTO pws_stations VALUES(?,?,?,?,?,?) ON CONFLICT(station_id) DO UPDATE SET last_discovered_at=excluded.last_discovered_at,data_json=excluded.data_json",
                (station.station_id, station.provider, station.provider_station_id, at, at, data),
            )
            self.connection.execute(
                "INSERT INTO pws_airport_stations VALUES(?,?,?) ON CONFLICT(station_id,airport_icao) DO UPDATE SET distance_km=excluded.distance_km",
                (station.station_id, airport.icao, distance),
            )
            for sensor in station.sensors:
                self.connection.execute(
                    "INSERT INTO pws_sensors VALUES(?,?,?,?) ON CONFLICT(sensor_id) DO UPDATE SET data_json=excluded.data_json",
                    (
                        sensor_key(station.station_id, sensor.provider_sensor_id),
                        station.station_id,
                        sensor.provider_sensor_id,
                        sensor.model_dump_json(),
                    ),
                )
            self.connection.execute(
                "INSERT OR IGNORE INTO pws_discoveries VALUES(NULL,?,?,?,?,?,?)",
                (station.station_id, airport.icao, at, packet["id"], distance, data),
            )

    def ingest(
        self,
        station: Station,
        reading: Reading,
        packet: dict[str, Any],
        startup: bool = True,
        historical: bool = False,
    ) -> None:
        historical = historical or reading.evidence_class == "HISTORICAL_EVENT_ONLY"
        data = reading.model_dump_json()
        key = sensor_key(station.station_id, reading.provider_sensor_id)
        # Unknown clocks cannot deduplicate observation identity across requests.
        clock_key = (
            ""
            if reading.observation_time or reading.source_publish_time or reading.provider_timestamp
            else packet["id"]
        )
        ident = hashlib.sha256(
            (
                key
                + reading.model_dump_json(
                    exclude={"timestamp_provenance", "timestamp_semantics_verified"}
                )
                + clock_key
                + str(historical)
            ).encode()
        ).hexdigest()
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO pws_observations VALUES(?,?,?,?,?,?,?,?)",
                (
                    ident,
                    key,
                    reading.observation_time.isoformat() if reading.observation_time else None,
                    reading.source_publish_time.isoformat()
                    if reading.source_publish_time
                    else None,
                    reading.temperature_c,
                    None if historical else packet["received_at"],
                    "HISTORICAL_EVENT_ONLY" if historical else "REALTIME_CAPTURED",
                    data,
                ),
            )
            self.connection.execute(
                "INSERT OR IGNORE INTO pws_arrivals VALUES(?,?,?,?,?,?)",
                (
                    ident,
                    packet["id"],
                    packet["received_at"],
                    packet["request_start"],
                    packet["request_end"],
                    startup,
                ),
            )
            from premetar.pws.integrity import record_observation

            record_observation(self.connection, ident)


def rows(
    connection: sqlite3.Connection, query: str, args: tuple[Any, ...] = ()
) -> list[dict[str, Any]]:
    cursor = connection.execute(query, args)
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor]


def inventory(connection: sqlite3.Connection, airport: str) -> list[dict[str, Any]]:
    return rows(
        connection,
        """SELECT s.*,a.airport_icao,a.distance_km,
        (SELECT max(COALESCE(o.observation_time,o.source_publish_time)) FROM pws_observations o
         JOIN pws_sensors sn ON sn.sensor_id=o.sensor_id WHERE sn.station_id=s.station_id) last_observation_time
        FROM pws_stations s JOIN pws_airport_stations a USING(station_id) WHERE a.airport_icao=?""",
        (airport,),
    )


def readings(connection: sqlite3.Connection, station_id: str, at: datetime) -> list[dict[str, Any]]:
    data = rows(
        connection,
        """SELECT o.*,s.station_id,s.provider_sensor_id,st.provider FROM pws_observations o
        JOIN pws_sensors s USING(sensor_id) JOIN pws_stations st USING(station_id) WHERE s.station_id=? AND o.first_receive_time<=?
        AND o.evidence_class='REALTIME_CAPTURED' ORDER BY o.first_receive_time,o.id""",
        (station_id, at.isoformat()),
    )
    return [{**r, **json.loads(r["data_json"])} for r in data]


def selected(connection: sqlite3.Connection, station_id: str, airport: str, at: datetime) -> bool:
    row = connection.execute(
        """SELECT selected FROM pws_selections WHERE station_id=? AND airport_icao=?
        AND created_at<=? ORDER BY created_at DESC,id DESC LIMIT 1""",
        (station_id, airport, at.isoformat()),
    ).fetchone()
    return bool(row and row[0])
