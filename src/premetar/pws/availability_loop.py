"""One provider lifecycle: bounded preflight, selected polling and slow recovery."""

import asyncio
import json
import time
from datetime import datetime
from typing import Any

import httpx

from premetar.collector import wait_or_stop
from premetar.continuous.config import Config
from premetar.continuous.polling import next_interval
from premetar.model import utc_now
from premetar.pws.availability import (
    candidates,
    measurement_clocks,
    policy,
    reconcile,
    record_check,
    selection_at,
)
from premetar.pws.models import Reading, Station
from premetar.pws.providers import OpenSenseMap, ProviderError
from premetar.pws.repository import PWSStore, inventory, rows, sensor_key
from premetar.pws.service import settings


async def poll_station(
    store: PWSStore, provider: OpenSenseMap, station: Station, airport: str, context: str
) -> list[dict[str, Any]]:
    started = time.monotonic()
    data: list[tuple[Reading, dict[str, Any]]] = []
    error = None
    try:
        data = await provider.fetch_latest(station)
    except (ProviderError, ValueError, TypeError, KeyError, httpx.HTTPError) as exc:
        error = str(exc) if isinstance(exc, ProviderError) else type(exc).__name__
        await store.error("pws_" + provider.name, error)
    packet = data[0][1] if data else getattr(provider, "last_packet", None)
    bysensor = {r.provider_sensor_id: (r, p) for r, p in data}
    results = []
    for sensor in station.sensors:
        reading, capture = bysensor.get(sensor.provider_sensor_id, (None, packet))
        identity = None
        before = 0
        if reading is not None and capture is not None and not error:
            key = sensor_key(station.station_id, sensor.provider_sensor_id)
            before = await store._call(
                lambda key=key: store.connection.execute(
                    "SELECT count(*) FROM pws_observations WHERE sensor_id=?", (key,)
                ).fetchone()[0]
            )
            identity = await store._call(
                store.ingest, station, reading, capture, context == "PREFLIGHT", False, None
            )
        after = before
        if identity is not None:
            after = await store._call(
                lambda key=key: store.connection.execute(
                    "SELECT count(*) FROM pws_observations WHERE sensor_id=?",
                    (key,),
                ).fetchone()[0]
            )
        results.append(
            await store._call(
                record_check,
                store.connection,
                store.run_id,
                airport,
                station,
                sensor_key(station.station_id, sensor.provider_sensor_id),
                reading,
                capture,
                context,
                identity,
                after > before,
                error,
            )
        )

    def save_poll() -> None:
        if not store.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='continuous_polls'"
        ).fetchone():
            return
        with store.connection:
            store.connection.execute(
                "INSERT INTO continuous_polls VALUES(NULL,?,?,?,?,?,?,?,?,?)",
                (
                    store.run_id,
                    provider.name,
                    station.station_id,
                    utc_now().isoformat(),
                    time.monotonic() - started,
                    sum(r["outcome"] == "SUCCESS_NEW_MEASUREMENT" for r in results),
                    sum(r["outcome"] == "SUCCESS_UNCHANGED_MEASUREMENT" for r in results),
                    "DEGRADED"
                    if error
                    else "HEALTHY"
                    if any(r["status"] == "ACTIVE" for r in results)
                    else "STALE",
                    error,
                ),
            )

    await store._call(save_poll)
    return results


def selected_stations(store: PWSStore, airport: str) -> list[Station]:
    found = selection_at(store.connection, airport, "opensensemap", utc_now())
    if found is None:
        return []
    cohort = json.loads(found["data_json"])
    selected = set(cohort["selected_sensor_ids"])
    station_ids = set(cohort["selected_station_ids"])
    result = []
    for item in inventory(store.connection, airport):
        if item["station_id"] not in station_ids:
            continue
        station = Station.model_validate_json(item["data_json"])
        sensors = [
            s
            for s in station.sensors
            if sensor_key(station.station_id, s.provider_sensor_id) in selected
        ]
        if station.provider == "opensensemap" and sensors:
            result.append(station.model_copy(update={"sensors": sensors}))
    return result


async def preflight_airport(
    store: PWSStore,
    provider: OpenSenseMap,
    airport: str,
    stop: asyncio.Event,
    service_selected: Any = None,
) -> dict[str, Any]:
    cfg = policy()
    reference = next(a for a in settings().airports if a.icao == airport)
    # Discovery is metadata-only; individual latest requests carry measurement evidence.
    found = await provider.discover(reference.latitude, reference.longitude, cfg.radius_km)
    for station, packet in found:
        await store._call(store.discover, reference, station, packet)
    temperatures = sorted(
        (s for s, _ in found if s.sensors), key=lambda s: (s.exposure != "outdoor", s.station_id)
    )
    completed = 0
    for station in temperatures[: cfg.max_preflight_stations_per_airport]:
        if stop.is_set():
            return dict(status="INTERRUPTED", airport=airport)
        outcomes = await poll_station(store, provider, station, airport, "PREFLIGHT")
        if any(
            r["outcome"] == "PROVIDER_ERROR"
            and r["reasons"][0]
            in {
                "RATE_LIMITED",
                "AUTH_OR_REDIRECT_DISABLED",
                "PROVIDER_COOLDOWN",
                "PROVIDER_DISABLED",
            }
            for r in outcomes
        ):
            raise ProviderError("PREFLIGHT_PROVIDER_UNAVAILABLE")
        completed += 1
        if service_selected:
            await service_selected()
    # Early scan results can expire during a large preflight. Refresh a bounded shortlist,
    # never infer that the first receipt happened at discovery/selection time.
    pool = await store._call(candidates, store.connection, airport, utc_now())
    refresh = sorted(
        (
            r
            for r in pool
            if r["status"] == "ACTIVE"
            and not r["eligible"]
            and r["data"]["mode"] == "ACTIVE"
            and not r["manual_excluded"]
            and (utc_now() - datetime.fromisoformat(r["checked_at"])).total_seconds() >= 300
        ),
        key=lambda r: (r["distance_km"], r["sensor_id"]),
    )
    refreshed: set[str] = set()
    for row in refresh:
        if len(refreshed) >= cfg.max_stations_per_airport * 2 or stop.is_set():
            break
        if row["station_id"] in refreshed:
            continue
        await poll_station(store, provider, row["station"], airport, "PREFLIGHT_REFRESH")
        refreshed.add(row["station_id"])
    result = dict(
        airport=airport,
        status="COMPLETED",
        discovered_stations=len(found),
        temperature_stations=len(temperatures),
        temperature_sensors=sum(len(s.sensors) for s in temperatures),
        checked_stations=completed,
        preflight_capped=completed < len(temperatures),
        discovered_station_ids=[s.station_id for s, _ in found],
        radius_km=cfg.radius_km,
        completed_at=utc_now().isoformat(),
    )

    def save() -> None:
        with store.connection:
            store.connection.execute(
                "INSERT INTO pws_preflight_runs VALUES(NULL,?,?,?,?)",
                (store.run_id, airport, result["completed_at"], json.dumps(result)),
            )
        reconcile(store.connection, airport)

    await store._call(save)
    return result


def station_schedule(store: PWSStore, station: Station, config: Config) -> tuple[float, float]:
    now = utc_now()
    limits = config.polling(station.provider)
    clocks = []
    checked = []
    failures = 0
    for sensor in station.sensors:
        key = sensor_key(station.station_id, sensor.provider_sensor_id)
        clocks.extend(measurement_clocks(store.connection, key, now))
        state = store.connection.execute(
            "SELECT checked_at,data_json FROM pws_sensor_state WHERE sensor_id=?", (key,)
        ).fetchone()
        if state:
            checked.append(datetime.fromisoformat(state[0]))
            failures = max(failures, int(json.loads(state[1]).get("fail_streak", 0)))
    interval = next_interval(
        clocks, limits.minimum_poll_interval, limits.maximum_poll_interval, failures
    )
    age = (now - max(checked)).total_seconds() if checked else interval
    return interval, max(0, interval - age)


async def availability_loop(
    store: PWSStore, provider: OpenSenseMap, config: Config, stop: asyncio.Event
) -> None:
    due: dict[tuple[str, str], float] = {}

    async def selected_due() -> None:
        for airport in config.airports:
            for station in await store._call(selected_stations, store, airport):
                key = (airport, station.station_id)
                if key not in due:
                    _, delay = await store._call(station_schedule, store, station, config)
                    due[key] = time.monotonic() + delay
                if stop.is_set() or time.monotonic() < due[key]:
                    continue
                await poll_station(store, provider, station, airport, "MONITOR")
                interval, _ = await store._call(station_schedule, store, station, config)
                due[key] = time.monotonic() + interval
                await store._call(reconcile, store.connection, airport)

    # On restart, reuse a recent completed preflight; refresh selected members prospectively.
    for airport in config.airports:
        previous = await store._call(
            rows,
            store.connection,
            "SELECT completed_at FROM pws_preflight_runs WHERE airport_icao=? ORDER BY id DESC LIMIT 1",
            (airport,),
        )
        if (
            not previous
            or (utc_now() - datetime.fromisoformat(previous[0]["completed_at"])).total_seconds()
            >= config.discovery_seconds
        ):
            try:
                await preflight_airport(store, provider, airport, stop, selected_due)
            except (ProviderError, ValueError, KeyError, TypeError, httpx.HTTPError) as exc:
                await store.error("pws_" + provider.name, "PREFLIGHT_" + type(exc).__name__)
    while not stop.is_set():
        await selected_due()
        now = utc_now()
        for airport in config.airports:
            if stop.is_set():
                break
            selection_key = (airport, "selection")
            if time.monotonic() >= due.get(selection_key, 0):
                await store._call(reconcile, store.connection, airport)
                due[selection_key] = time.monotonic() + 60
            last = await store._call(
                rows,
                store.connection,
                "SELECT completed_at FROM pws_preflight_runs WHERE airport_icao=? ORDER BY id DESC LIMIT 1",
                (airport,),
            )
            if (
                not last
                or (now - datetime.fromisoformat(last[0]["completed_at"])).total_seconds()
                >= config.discovery_seconds
            ):
                # Failed discovery uses bounded retry, not a tight request loop.
                key = (airport, "discovery")
                if time.monotonic() >= due.get(key, 0):
                    due[key] = time.monotonic() + policy().inactive_recheck_seconds
                    try:
                        await preflight_airport(store, provider, airport, stop, selected_due)
                    except (ProviderError, ValueError, KeyError, TypeError, httpx.HTTPError) as exc:
                        await store.error("pws_" + provider.name, "PREFLIGHT_" + type(exc).__name__)
            selected_ids = {
                s.station_id for s in await store._call(selected_stations, store, airport)
            }
            items = await store._call(inventory, store.connection, airport)
            for item in items:
                if stop.is_set():
                    break
                station = Station.model_validate_json(item["data_json"])
                if (
                    station.provider != provider.name
                    or not station.sensors
                    or station.station_id in selected_ids
                    or item["distance_km"] > policy().radius_km
                ):
                    continue
                checks = await store._call(
                    rows,
                    store.connection,
                    "SELECT checked_at,data_json FROM pws_sensor_state WHERE sensor_id IN (SELECT sensor_id FROM pws_sensors WHERE station_id=?) ORDER BY checked_at DESC LIMIT 1",
                    (station.station_id,),
                )
                data = json.loads(checks[0]["data_json"]) if checks else {}
                interval = (
                    policy().inactive_recheck_seconds
                    if data.get("mode") != "ACTIVE"
                    else policy().candidate_refresh_seconds
                )
                if data.get("mode") == "INACTIVE" and data.get("good_streak", 0) > 0:
                    interval = policy().recovery_confirm_seconds
                if (
                    checks
                    and (now - datetime.fromisoformat(checks[0]["checked_at"])).total_seconds()
                    < interval
                ):
                    continue
                key = (airport, station.station_id)
                if time.monotonic() < due.get(key, 0):
                    continue
                recovered = await poll_station(store, provider, station, airport, "RECOVERY")
                if any(r["mode"] == "INACTIVE" and r.get("good_streak", 0) > 0 for r in recovered):
                    interval = policy().recovery_confirm_seconds
                due[key] = time.monotonic() + interval
                await store._call(reconcile, store.connection, airport)
                # Selected requests take priority even during a long inactive recovery scan.
                await selected_due()
        await wait_or_stop(stop, 1)
