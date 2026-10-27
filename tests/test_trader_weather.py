import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from premetar.research.trader_weather import weather_context

DECISION = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
TRADE = {"trade_id": "trade", "slug": "highest-temperature-in-warsaw-on-october-27"}


@pytest.fixture
def weather_db(tmp_path: Path) -> Path:
    path = tmp_path / "weather.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
        CREATE TABLE observations(id INTEGER PRIMARY KEY, station_icao TEXT,
            event_time TEXT, collector_receive_time TEXT, temperature_c REAL,
            source TEXT, raw_text TEXT, product_type TEXT);
        CREATE TABLE pws_stations(station_id TEXT PRIMARY KEY, provider TEXT);
        CREATE TABLE pws_sensors(sensor_id TEXT PRIMARY KEY,station_id TEXT);
        CREATE TABLE pws_airport_stations(station_id TEXT,airport_icao TEXT,distance_km REAL);
        CREATE TABLE pws_observations(id TEXT PRIMARY KEY,sensor_id TEXT,
            observation_time TEXT,first_receive_time TEXT,temperature_c REAL,
            evidence_class TEXT,data_json TEXT);
        INSERT INTO pws_stations VALUES('station','opensensemap');
        INSERT INTO pws_sensors VALUES('sensor','station');
        INSERT INTO pws_airport_stations VALUES('station','EPWA',2.5);
        """)
    return path


def insert_pws(
    path: Path,
    identity: str = "valid",
    *,
    event: str | None = None,
    receipt: str | None = None,
    provenance: str = "SENSOR_MEASUREMENT_TIME",
    verified: bool = True,
) -> None:
    data = {
        "raw_unit": "C",
        "quality_flags": [],
        "timestamp_provenance": provenance,
        "timestamp_semantics_verified": verified,
    }
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO pws_observations VALUES(?,?,?,?,?,?,?)",
            (
                identity,
                "sensor",
                event or (DECISION - timedelta(seconds=60)).isoformat(),
                receipt or (DECISION - timedelta(seconds=30)).isoformat(),
                10.4,
                "REALTIME_CAPTURED",
                json.dumps(data),
            ),
        )


def test_absent_airport_and_database(tmp_path: Path) -> None:
    assert (
        weather_context(tmp_path / "missing", TRADE, DECISION)["status"] == "DATABASE_UNAVAILABLE"
    )
    unknown = {**TRADE, "slug": "highest-temperature-in-taipei"}
    assert (
        weather_context(tmp_path / "missing", unknown, DECISION)["status"]
        == "WEATHER_NOT_MONITORED"
    )


def test_valid_pws_available_and_database_unchanged(weather_db: Path) -> None:
    insert_pws(weather_db)
    before = weather_db.read_bytes()
    result = weather_context(weather_db, TRADE, DECISION)
    assert result["status"] == "AVAILABLE_BOUNDED_CONTEXT"
    assert [row["id"] for row in result["pws"]] == ["valid"]
    assert result["forecast"] is None and result["calibrations"] == []
    assert weather_db.read_bytes() == before


@pytest.mark.parametrize(
    "kwargs",
    [
        {"receipt": (DECISION + timedelta(seconds=1)).isoformat()},
        {"event": (DECISION + timedelta(seconds=1)).isoformat()},
        {"event": (DECISION - timedelta(minutes=6)).isoformat()},
        {"event": "2026-10-27T11:59:00"},
        {"event": "not-a-timestamp"},
        {"provenance": "PROVIDER_INGEST_TIME", "verified": False},
        {"provenance": "UNKNOWN_TIME", "verified": False},
    ],
)
def test_ineligible_pws_excluded(weather_db: Path, kwargs: dict[str, object]) -> None:
    insert_pws(weather_db, **kwargs)  # type: ignore[arg-type]
    assert weather_context(weather_db, TRADE, DECISION)["pws"] == []


def test_latest_valid_per_sensor_and_no_future_receipt(weather_db: Path) -> None:
    insert_pws(
        weather_db,
        "old",
        event=(DECISION - timedelta(seconds=120)).isoformat(),
        receipt=(DECISION - timedelta(seconds=90)).isoformat(),
    )
    insert_pws(weather_db, "new")
    insert_pws(weather_db, "future", receipt=(DECISION + timedelta(seconds=1)).isoformat())
    result = weather_context(weather_db, TRADE, DECISION)
    assert [row["id"] for row in result["pws"]] == ["new"]


def test_metar_future_receipt_or_event_excluded(weather_db: Path) -> None:
    with sqlite3.connect(weather_db) as conn:
        for index, event, receipt in (
            (1, DECISION - timedelta(minutes=10), DECISION - timedelta(minutes=8)),
            (2, DECISION - timedelta(minutes=5), DECISION + timedelta(seconds=1)),
            (3, DECISION + timedelta(minutes=1), DECISION - timedelta(seconds=1)),
        ):
            conn.execute(
                "INSERT INTO observations VALUES(?,?,?,?,?,?,?,?)",
                (
                    index,
                    "EPWA",
                    event.isoformat(),
                    receipt.isoformat(),
                    10,
                    "imgw",
                    "EPWA METAR",
                    "METAR",
                ),
            )
    result = weather_context(weather_db, TRADE, DECISION)
    assert [row["id"] for row in result["metar"]] == [1]


def test_empty_weather_not_fabricated(weather_db: Path) -> None:
    result = weather_context(weather_db, TRADE, DECISION)
    assert result["metar"] == [] and result["pws"] == []
    assert result["current_confirmed_daily_tmax"] is None
