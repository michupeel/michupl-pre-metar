"""Bounded, read-only projections of existing EPWA collector evidence.

No collectors, schema changes, durable writes or outbound API requests. A query
budget interrupts expensive SQL instead of blocking an ingestion writer/UI.
As-of eligibility and temperature derivations belong to the service layer.
"""

import json
import sqlite3
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from premetar.pws.daily_time import local_day_bounds
from premetar.pws.timestamps import parse_utc

ZONE = ZoneInfo("Europe/Warsaw")


def decoded(value: Any) -> dict[str, Any]:
    try:
        obj = json.loads(value) if isinstance(value, str) else value
        return obj if isinstance(obj, dict) else {}
    except (TypeError, ValueError):
        return {}


class Reader:
    def __init__(self, weather: Path, research: Path, trader: Path) -> None:
        self.weather, self.research, self.trader = weather, research, trader
        self.errors: dict[str, str] = {}
        self.truncated: dict[str, bool] = {}
        self.timings: dict[str, float] = {}

    def _query(
        self,
        path: Path,
        scope: str,
        sql: str,
        params: tuple[Any, ...] = (),
        cap: int | None = None,
    ) -> list[dict[str, Any]]:
        if not path.is_file():
            self.errors[scope] = "DATABASE_UNAVAILABLE"
            return []
        started = time.monotonic()
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.25)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            conn.execute("PRAGMA busy_timeout=250")
            conn.set_progress_handler(lambda: int(time.monotonic() - started > 1), 1000)
            rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
            if cap is not None:
                self.truncated[scope] = len(rows) > cap
                rows = rows[:cap]
            return rows
        except sqlite3.Error as error:
            self.errors[scope] = (
                "QUERY_BUDGET_OR_BUSY"
                if time.monotonic() - started >= 0.25
                else type(error).__name__
            )
            return []
        finally:
            if conn is not None:
                conn.close()
            self.timings[scope] = round((time.monotonic() - started) * 1000, 3)

    def _events(
        self,
        kind: str,
        cap: int,
        scope: str,
        before: datetime | None = None,
        airport_path: str | None = None,
    ) -> list[dict[str, Any]]:
        clause = " AND julianday(received_at)<julianday(?)" if before else ""
        values: list[Any] = [kind]
        if before:
            values.append(before.isoformat())
        if airport_path:
            clause += " AND json_extract(payload,?)='EPWA'"
            values.append(airport_path)
        values.append(cap + 1)
        params = tuple(values)
        rows = self._query(
            self.research,
            scope,
            "SELECT id,kind,received_at,payload FROM events WHERE kind=?"
            + clause
            + " ORDER BY id DESC LIMIT ?",
            params,
            cap,
        )
        return [
            dict(event_id=r["id"], received_at=r["received_at"], **decoded(r["payload"]))
            for r in reversed(rows)
        ]

    def load_day(self, day: date) -> dict[str, Any]:
        self.errors, self.truncated, self.timings = {}, {}, {}
        start, end = local_day_bounds(day, "Europe/Warsaw")
        metars = self._metars(start, end)
        stations = self._stations()
        pws = self._pws(start, end)
        selections = self._query(
            self.weather,
            "selections",
            "SELECT * FROM pws_selections WHERE airport_icao='EPWA' ORDER BY id DESC LIMIT 5001",
            cap=5000,
        )
        calibrations = self._query(
            self.weather,
            "calibrations",
            "SELECT * FROM pws_calibrations WHERE airport_icao='EPWA' AND julianday(created_at)<julianday(?) ORDER BY id DESC LIMIT 501",
            (end.isoformat(),),
            cap=500,
        )
        for calibration in calibrations:
            calibration["parameters"] = decoded(calibration.pop("data_json", None))
        quality = self._query(
            self.weather,
            "quality",
            "SELECT * FROM pws_quality_results WHERE airport_icao='EPWA' AND julianday(created_at)<julianday(?) ORDER BY id DESC LIMIT 501",
            (end.isoformat(),),
            cap=500,
        )
        for row in quality:
            row["parameters"] = decoded(row.pop("data_json", None))
        forecasts = [
            r
            for r in self._events("FORECAST", 500, "forecasts", end, "$.airport")
            if r.get("airport") == "EPWA"
        ]
        samples = self._book_samples(day, start, end)
        markets = [
            r
            for r in self._events("MARKET", 1000, "markets", end, "$.identity.airport")
            if r.get("identity", {}).get("airport") == "EPWA"
        ]
        if not markets:
            markets = self._fallback_markets(end)
        tokens = {
            str(identity[side])
            for market in markets
            if isinstance((identity := market.get("identity")), dict)
            for side in ("yes", "no")
            if identity.get(side)
        }
        tokens.update(
            str(sample["identity"][side])
            for sample in samples
            for side in ("yes", "no")
            if sample["identity"].get(side)
        )
        trades = self._trades(start, end, tokens)
        signals = [
            r
            for r in self._events("SIGNAL", 1000, "signals", end, "$.inputs.airport")
            if r.get("version") == "EXP0013-v1.1"
            and r.get("inputs", {}).get("airport") == "EPWA"
            and self._in_day(r.get("created_at"), start, end)
        ]
        health = self._health()
        result: dict[str, Any] = dict(
            date=day.isoformat(),
            start_utc=start.isoformat(),
            end_utc=end.isoformat(),
            metars=metars,
            pws=pws,
            stations=stations,
            selections=list(reversed(selections)),
            calibrations=list(reversed(calibrations)),
            quality_results=list(reversed(quality)),
            forecasts=forecasts,
            book_samples=samples,
            trades=trades,
            markets=markets,
            signals=signals,
            health=health,
            inventory_last=self._inventory_last(stations, start),
        )
        result["limits"] = dict(
            truncated=dict(self.truncated),
            errors=dict(self.errors),
            query_duration_ms=dict(self.timings),
            rowcounts={k: len(v) for k, v in result.items() if isinstance(v, list)},
            query_budget_seconds=1,
            busy_timeout_ms=250,
            metadata_semantics="CURRENT_STATION_METADATA_SELECTION_HISTORY_SEPARATE",
        )
        return result

    @staticmethod
    def _in_day(value: Any, start: datetime, end: datetime) -> bool:
        try:
            at = parse_utc(value)
            return at is not None and start <= at < end
        except (ValueError, TypeError):
            return False

    def _metars(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        rows = self._query(
            self.weather,
            "metars",
            """SELECT o.id,o.identity,o.event_time,o.temperature_c,o.raw_text,o.product_type,o.data_json,
            o.startup_censored,o.coverage_gap,o.source,rr.collector_receive_time received
            FROM observations o JOIN report_receipts rr ON rr.observation_id=o.id
            WHERE o.station_icao='EPWA' AND o.product_type IN ('METAR','SPECI')
            AND julianday(o.event_time)>=julianday(?) AND julianday(o.event_time)<julianday(?)
            ORDER BY o.id DESC,rr.id DESC LIMIT 4001""",
            (start.isoformat(), end.isoformat()),
            cap=4000,
        )
        identities: dict[str, dict[str, Any]] = {}
        for row in rows:
            try:
                event, received = parse_utc(row["event_time"]), parse_utc(row["received"])
            except (ValueError, TypeError):
                continue
            if event is None or received is None:
                continue
            prior = identities.get(row["identity"])
            providers = sorted(set(prior["providers"] if prior else []) | {row["source"]})
            prior_received = parse_utc(prior["first_received_utc"]) if prior else None
            if prior and prior_received is not None and prior_received <= received:
                prior["providers"] = providers
                continue
            data = decoded(row["data_json"])
            identities[row["identity"]] = dict(
                id=row["id"],
                report_identity=row["identity"],
                observation_time_utc=event.isoformat(),
                observation_time_local=event.astimezone(ZONE).isoformat(),
                first_received_utc=received.isoformat(),
                first_received_local=received.astimezone(ZONE).isoformat(),
                temperature_c=row["temperature_c"],
                report_type=row["product_type"],
                correction=bool(data.get("cor")),
                auto=bool(data.get("auto")),
                providers=providers,
                raw_text=row["raw_text"],
                startup_censored=bool(row["startup_censored"]),
                coverage_gap=bool(row["coverage_gap"]),
            )
        return sorted(
            identities.values(),
            key=lambda r: (
                r["observation_time_utc"],
                r["first_received_utc"],
                r["report_identity"],
            ),
        )

    def _stations(self) -> list[dict[str, Any]]:
        rows = self._query(
            self.weather,
            "stations",
            """SELECT s.sensor_id,s.provider_sensor_id,s.data_json sensor_json,
            st.station_id,st.provider,st.provider_station_id,st.first_discovered_at metadata_known_since,st.data_json station_json,a.distance_km,
            sel.selected,sel.reason selection_reason,sel.created_at selection_created_at
            FROM pws_sensors s JOIN pws_stations st USING(station_id) JOIN pws_airport_stations a USING(station_id)
            LEFT JOIN pws_selections sel ON sel.id=(SELECT MAX(z.id) FROM pws_selections z WHERE z.station_id=st.station_id AND z.airport_icao='EPWA')
            WHERE a.airport_icao='EPWA' AND (sel.selected=1 OR EXISTS(SELECT 1 FROM pws_observations o WHERE o.sensor_id=s.sensor_id))
            ORDER BY a.distance_km,s.sensor_id LIMIT 501""",
            cap=500,
        )
        result = []
        for row in rows:
            metadata, sensor = (
                decoded(row.pop("station_json", None)),
                decoded(row.pop("sensor_json", None)),
            )
            if sensor.get("phenomenon") != "temperature":
                continue
            result.append(
                {
                    **row,
                    "station_name": metadata.get("station_name"),
                    "sensor_type": sensor.get("sensor_type"),
                    "sensor_model": sensor.get("sensor_model"),
                    "manufacturer": sensor.get("manufacturer"),
                    "sensor_metadata": sensor,
                    "latitude": metadata.get("latitude"),
                    "longitude": metadata.get("longitude"),
                    "exposure": metadata.get("exposure"),
                    "mobile": metadata.get("mobile"),
                    "selected": bool(row["selected"]),
                }
            )
        return result

    def _pws(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        rows = self._query(
            self.weather,
            "pws",
            """SELECT o.*,s.station_id,s.provider_sensor_id,s.data_json sensor_json,
            st.provider,st.data_json station_json,a.distance_km
            FROM pws_observations o JOIN pws_sensors s USING(sensor_id) JOIN pws_stations st USING(station_id)
            JOIN pws_airport_stations a USING(station_id) WHERE a.airport_icao='EPWA' AND
            ((julianday(o.observation_time)>=julianday(?) AND julianday(o.observation_time)<julianday(?)) OR
             (julianday(o.first_receive_time)>=julianday(?) AND julianday(o.first_receive_time)<julianday(?)))
            ORDER BY o.first_receive_time DESC LIMIT 20001""",
            (start.isoformat(), end.isoformat(), start.isoformat(), end.isoformat()),
            cap=20000,
        )
        result = []
        for row in rows:
            metadata, sensor = (
                decoded(row.pop("station_json", None)),
                decoded(row.pop("sensor_json", None)),
            )
            data = decoded(row.pop("data_json", None))
            if sensor.get("phenomenon") != "temperature":
                continue
            result.append(
                {
                    **data,
                    **row,
                    "station_name": metadata.get("station_name"),
                    "sensor_type": sensor.get("sensor_type"),
                    "sensor_model": sensor.get("sensor_model"),
                    "manufacturer": sensor.get("manufacturer"),
                    "exposure": metadata.get("exposure"),
                    "mobile": metadata.get("mobile"),
                }
            )
        return sorted(
            result,
            key=lambda r: (
                str(r.get("observation_time") or ""),
                str(r.get("first_receive_time") or ""),
                r["id"],
            ),
        )

    def _book_samples(self, day: date, start: datetime, end: datetime) -> list[dict[str, Any]]:
        columns = [
            "id event_id",
            "received_at",
            "json_extract(payload,'$.identity') identity_json",
            "json_extract(payload,'$.captured_at') captured_at",
            "json_extract(payload,'$.fee_status') fee_status",
            "json_extract(payload,'$.economic_status') economic_status",
        ]
        view_fields = (
            "status",
            "token_id",
            "market",
            "best_bid",
            "best_ask",
            "bid_size",
            "ask_size",
            "midpoint",
            "received_at",
            "connection_id",
            "sequence_completeness",
        )
        for side in ("yes", "no"):
            for field in view_fields:
                columns.append(f"json_extract(payload,'$.books.{side}.{field}') {side}_{field}")
        sql = (
            "SELECT "
            + ",".join(columns)
            + " FROM events WHERE kind='BOOK_SAMPLE' AND json_extract(payload,'$.identity.airport')='EPWA' AND json_extract(payload,'$.identity.local_date')=? AND julianday(received_at)>=julianday(?) AND julianday(received_at)<julianday(?) ORDER BY id DESC LIMIT 10001"
        )
        rows = self._query(
            self.research,
            "book_samples",
            sql,
            (day.isoformat(), start.isoformat(), end.isoformat()),
            cap=10000,
        )
        result = []
        for row in reversed(rows):
            identity = decoded(row.pop("identity_json", None))
            books = {
                side: {field: row.pop(f"{side}_{field}", None) for field in view_fields}
                for side in ("yes", "no")
            }
            result.append(dict(**row, identity=identity, books=books))
        return result

    def _fallback_markets(self, end: datetime) -> list[dict[str, Any]]:
        # Fallback supplies metadata only, never a fabricated executable book.
        rows = self._query(
            self.trader,
            "trader_markets",
            "SELECT id,received_at,payload FROM events WHERE kind='MARKET' AND julianday(received_at)<julianday(?) ORDER BY id DESC LIMIT 1001",
            (end.isoformat(),),
            cap=1000,
        )
        result = []
        for row in reversed(rows):
            market = decoded(row["payload"])
            if "warsaw" not in str(market.get("slug", "")):
                continue
            result.append(
                dict(
                    event_id=row["id"],
                    received_at=row["received_at"],
                    metadata=market,
                    identity=None,
                    source="TRADER_METADATA_FALLBACK_UNVERIFIED_STATION",
                )
            )
        return result

    def _inventory_last(
        self, stations: list[dict[str, Any]], start: datetime
    ) -> list[dict[str, Any]]:
        """Prior-day last known record for selected instruments, never invented current data."""
        result = []
        # Include known instruments independently of CURRENT selection so an
        # historical inspector can apply the separate selection history at T.
        self.truncated["inventory_last"] = len(stations) > 100
        for station in stations[:100]:
            found = self._query(
                self.weather,
                "inventory_last:" + station["sensor_id"],
                "SELECT * FROM pws_observations WHERE sensor_id=? AND julianday(first_receive_time)<julianday(?) ORDER BY observation_time DESC,first_receive_time DESC LIMIT 1",
                (station["sensor_id"], start.isoformat()),
            )
            if not found:
                continue
            row = found[0]
            data = decoded(row.pop("data_json", None))
            result.append(
                {
                    **data,
                    **row,
                    **{
                        k: station.get(k)
                        for k in (
                            "station_id",
                            "provider",
                            "station_name",
                            "distance_km",
                            "sensor_type",
                            "sensor_model",
                            "exposure",
                            "mobile",
                        )
                    },
                    "inventory_only_prior_day": True,
                }
            )
        return result

    def _trades(self, start: datetime, end: datetime, tokens: set[str]) -> list[dict[str, Any]]:
        rows = self._query(
            self.research,
            "trades",
            """SELECT id event_id,received_at,
            json_extract(payload,'$.token_id') token_id,json_extract(payload,'$.market') condition_id,
            json_extract(payload,'$.price') price,json_extract(payload,'$.size') size,
            json_extract(payload,'$.side') side,json_extract(payload,'$.source_timestamp') source_timestamp
            FROM events WHERE kind='WS_TRADE' AND julianday(received_at)>=julianday(?)
            AND julianday(received_at)<julianday(?) ORDER BY id DESC LIMIT 5001""",
            (start.isoformat(), end.isoformat()),
            cap=5000,
        )
        return [row for row in reversed(rows) if str(row["token_id"]) in tokens]

    def _health(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        run = self._query(
            self.weather,
            "weather_health",
            "SELECT id,started_at,ended_at,heartbeat,exit_reason FROM runs ORDER BY started_at DESC LIMIT 1",
        )
        health = self._query(
            self.weather,
            "weather_process",
            "SELECT pid,updated_at,data_json FROM continuous_health ORDER BY updated_at DESC LIMIT 1",
        )
        result["weather"] = {**(run[0] if run else {}), **(health[0] if health else {})}
        if health:
            result["weather"]["details"] = decoded(result["weather"].pop("data_json", None))
        for label, path in (("research", self.research), ("trader", self.trader)):
            rows = self._query(
                path,
                label + "_health",
                "SELECT id,received_at,payload FROM events WHERE kind='HEALTH' ORDER BY id DESC LIMIT 1",
            )
            result[label] = (
                dict(
                    event_id=rows[0]["id"],
                    received_at=rows[0]["received_at"],
                    **decoded(rows[0]["payload"]),
                )
                if rows
                else {}
            )
        stream = self._query(
            self.research,
            "websocket_health",
            "SELECT id,received_at,payload FROM events WHERE kind='STREAMHEALTH' ORDER BY id DESC LIMIT 1",
        )
        result["websocket"] = (
            dict(
                event_id=stream[0]["id"],
                received_at=stream[0]["received_at"],
                **decoded(stream[0]["payload"]),
            )
            if stream
            else {}
        )
        return result
