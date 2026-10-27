"""Short, read-only queries of already recorded weather information."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from premetar.pws.timestamps import assess_time

AIRPORTS = {"munich": "EDDM", "amsterdam": "EHAM", "warsaw": "EPWA", "london": "EGLL"}


def weather_context(database: Path, trade: dict[str, Any], decision: datetime) -> dict[str, Any]:
    """Context at detection, NOT a reconstruction at historical trade/block time."""
    slug = str(trade.get("slug") or "").lower()
    airport = next((value for city, value in AIRPORTS.items() if city in slug), None)
    result: dict[str, Any] = {
        "trade_id": trade["trade_id"],
        "context_asof": decision.isoformat(),
        "airport": airport,
        "context_semantics": "RECORDED_AVAILABLE_AT_DETECTION_NOT_AT_SOURCE_TRADE_TIME",
        "forecast": None,
        "forecast_daily_max": None,
        "current_confirmed_daily_tmax": None,
        "tmax_note": "Routine METAR maximum does not establish settlement daily Tmax",
        "calibrations": [],
        "pws": [],
        "metar": [],
    }
    if airport is None or not database.is_file():
        result["status"] = "WEATHER_NOT_MONITORED" if airport is None else "DATABASE_UNAVAILABLE"
        return result
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.25)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    try:
        # Bounded recent indexed identity window; no multi-minute historical scan/live snapshot.
        metars = connection.execute(
            "SELECT id,event_time,collector_receive_time,temperature_c,source,raw_text,product_type "
            "FROM observations WHERE station_icao=? AND id>(SELECT COALESCE(MAX(id),0)-2000 FROM observations) "
            "ORDER BY id DESC LIMIT 100",
            (airport,),
        ).fetchall()
        for item in metars:
            row = dict(item)
            receive = row.get("collector_receive_time")
            event = row.get("event_time")
            if (
                receive
                and event
                and datetime.fromisoformat(receive) <= decision
                and datetime.fromisoformat(event) <= decision
            ):
                result["metar"].append(row)
        observations = connection.execute(
            "SELECT o.*,s.station_id,st.provider FROM pws_observations o JOIN pws_sensors s USING(sensor_id) "
            "JOIN pws_stations st ON st.station_id=s.station_id "
            "JOIN pws_airport_stations a ON a.station_id=s.station_id WHERE a.airport_icao=? "
            "AND o.first_receive_time>=? AND o.first_receive_time<=? "
            "ORDER BY o.first_receive_time DESC LIMIT 250",
            (airport, (decision - timedelta(minutes=6)).isoformat(), decision.isoformat()),
        ).fetchall()
        seen: set[str] = set()
        for item in observations:
            row = dict(item)
            merged = {**json.loads(row["data_json"]), **row}
            check = assess_time(merged, at=decision)
            if not check.eligible or row["sensor_id"] in seen:
                continue
            seen.add(row["sensor_id"])
            result["pws"].append(
                {
                    k: row[k]
                    for k in (
                        "id",
                        "sensor_id",
                        "station_id",
                        "observation_time",
                        "first_receive_time",
                        "temperature_c",
                    )
                }
            )
        # Attach only stored calibration versions already created/trained by decision.
        stations = {row["station_id"] for row in result["pws"]}
        for station in stations:
            try:
                calibration = connection.execute(
                    "SELECT id,created_at,trained_through,data_json FROM pws_calibrations "
                    "WHERE station_id=? AND airport_icao=? AND created_at<? AND trained_through<? "
                    "ORDER BY id DESC LIMIT 1",
                    (station, airport, decision.isoformat(), decision.isoformat()),
                ).fetchone()
            except sqlite3.OperationalError:
                calibration = None
            if calibration:
                parameters = json.loads(calibration["data_json"])
                result["calibrations"].append(
                    {
                        "station_id": station,
                        "calibration_id": calibration["id"],
                        "created_at": calibration["created_at"],
                        "trained_through": calibration["trained_through"],
                        "parameters": parameters,
                        "usage": "AS_OF_STORED_PARAMETERS_CONTEXT_ONLY_NOT_A_NEW_PRODUCTION_FORECAST",
                    }
                )
                if isinstance(parameters.get("bias"), (float, int)):
                    for reading in result["pws"]:
                        if reading["station_id"] == station:
                            reading["stored_causal_corrected_temperature_c"] = (
                                reading["temperature_c"] - parameters["bias"]
                            )
        result["status"] = "AVAILABLE_BOUNDED_CONTEXT"
        result["context_completed_at"] = datetime.now(UTC).isoformat()
        return result
    except (sqlite3.Error, ValueError, TypeError) as exc:
        result["status"] = "UNAVAILABLE"
        result["error_class"] = type(exc).__name__
        return result
    finally:
        connection.close()
