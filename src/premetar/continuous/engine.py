"""Continuous jobs layered over the existing raw-first collector and providers."""

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import Any, cast

import httpx

from premetar.collector import wait_or_stop
from premetar.continuous.config import Config
from premetar.continuous.data import freeze_experiment, migrate, schedule, settle
from premetar.continuous.polling import next_interval
from premetar.continuous.reference_gate import ReferenceGate
from premetar.model import utc_now
from premetar.pws.models import Station
from premetar.pws.providers import PROVIDERS, OpenSenseMap, ProviderError, PWSProvider, Transport
from premetar.pws.quality import eligible
from premetar.pws.repository import PWSStore, inventory, rows, selected
from premetar.pws.service import discover, settings

LOG = logging.getLogger("premetar")


def cohort(store: PWSStore, config: Config, provider: str, airport: str) -> list[Station]:
    conn = store.connection
    existing = rows(
        conn,
        "SELECT station_id FROM continuous_cohort WHERE experiment=? AND airport=?",
        (config.experiment, airport),
    )
    known = {r["station_id"] for r in existing}
    items = sorted(inventory(conn, airport), key=lambda r: (r["distance_km"], r["station_id"]))
    chosen = [
        Station.model_validate_json(r["data_json"])
        for r in items
        if r["station_id"] in known
        and r["provider"] == provider
        and selected(conn, r["station_id"], airport, utc_now())
    ]
    # Freeze initial cohort per provider/airport; explicit later exclusions remain honored.
    if any(r["station_id"].startswith(provider + ":") for r in existing):
        return chosen
    candidates = []
    for row in items:
        station = Station.model_validate_json(row["data_json"])
        if (
            station.provider != provider
            or not station.sensors
            or station.exposure == "indoor"
            or station.mobile is True
        ):
            continue
        last = conn.execute(
            "SELECT selected FROM pws_selections WHERE station_id=? AND airport_icao=? ORDER BY id DESC LIMIT 1",
            (station.station_id, airport),
        ).fetchone()
        if last and not last[0]:
            continue
        # Prefer outdoor, metadata-rich and fresh discovery readings; never use outcomes.
        fresh = False
        for sensor in station.sensors:
            measurement = sensor.metadata.get("lastMeasurement", {})
            if isinstance(measurement, dict) and measurement.get("createdAt"):
                try:
                    age = (
                        utc_now()
                        - datetime.fromisoformat(measurement["createdAt"].replace("Z", "+00:00"))
                    ).total_seconds()
                    fresh = fresh or 0 <= age <= 3600
                except (ValueError, TypeError):
                    pass
        candidates.append(
            (
                not fresh,
                station.exposure != "outdoor",
                -len(station.sensors),
                row["distance_km"],
                station.station_id,
                station,
            )
        )
    # Cycle compass quadrants before taking a second station from the same quadrant.
    import math

    reference = next(a for a in settings().airports if a.icao == airport)
    buckets: dict[int, list[Any]] = {}
    for entry in sorted(candidates):
        station = entry[-1]
        angle = math.atan2(
            station.latitude - reference.latitude,
            (station.longitude - reference.longitude) * math.cos(math.radians(reference.latitude)),
        )
        quadrant = int((angle + math.pi) / (math.pi / 2)) % 4
        buckets.setdefault(quadrant, []).append(entry)
    diversified = []
    while buckets:
        for key in list(buckets):
            diversified.append(buckets[key].pop(0))
            if not buckets[key]:
                del buckets[key]
    with conn:
        for entry in diversified[: config.max_stations_per_provider_airport]:
            station = entry[-1]
            at = utc_now().isoformat()
            reason = "DISCOVERY_CANDIDATE continuous-v1: provider-balanced; recent discovery metadata, exposure, sensor metadata, distance, compass quadrant diversity; no predictive selection"
            conn.execute(
                "INSERT OR IGNORE INTO continuous_cohort VALUES(?,?,?,?,?)",
                (config.experiment, airport, station.station_id, at, reason),
            )
            conn.execute(
                "INSERT INTO pws_selections VALUES(NULL,?,?,?,?,?)",
                (station.station_id, airport, at, 1, reason),
            )
            chosen.append(station)
    return chosen


def record_poll(
    store: PWSStore,
    provider: str,
    station: str,
    started: float,
    before: int,
    state: str,
    error: str | None,
    received: int,
) -> None:
    conn = store.connection
    after = conn.execute(
        "SELECT count(*) FROM pws_observations o JOIN pws_sensors s USING(sensor_id) WHERE s.station_id=?",
        (station,),
    ).fetchone()[0]
    with conn:
        conn.execute(
            "INSERT INTO continuous_polls VALUES(NULL,?,?,?,?,?,?,?,?,?)",
            (
                store.run_id,
                provider,
                station,
                utc_now().isoformat(),
                time.monotonic() - started,
                after - before,
                max(0, received - (after - before)),
                state,
                error,
            ),
        )


async def provider_loop(
    store: PWSStore, provider: PWSProvider, config: Config, stop: asyncio.Event
) -> None:
    if provider.name == "opensensemap":
        from premetar.pws.availability_loop import availability_loop

        await availability_loop(store, cast(OpenSenseMap, provider), config, stop)
        return
    pws = settings()
    pws.providers = config.providers
    pws.discovery_seconds = config.discovery_seconds
    policy = config.polling(provider.name)
    initialized: set[str] = set()
    due: dict[str, float] = {}
    empty: dict[str, int] = {}
    while not stop.is_set():
        for airport in config.airports:
            last = await store._call(
                rows,
                store.connection,
                "SELECT max(d.at) latest FROM pws_discoveries d JOIN pws_stations s USING(station_id) WHERE s.provider=? AND d.airport_icao=?",
                (provider.name, airport),
            )
            if (
                not last[0]["latest"]
                or (utc_now() - datetime.fromisoformat(last[0]["latest"])).total_seconds()
                >= config.discovery_seconds
            ) and time.monotonic() >= due.get("discover:" + airport, 0):
                await discover(store, [provider], pws, {airport}, 20)
                due["discover:" + airport] = time.monotonic() + config.discovery_seconds
            stations = await store._call(cohort, store, config, provider.name, airport)
            for station in stations:
                if stop.is_set():
                    return
                if time.monotonic() < due.get(station.station_id, 0):
                    continue
                started = time.monotonic()
                before = await store._call(
                    lambda station_id=station.station_id: store.connection.execute(
                        "SELECT count(*) FROM pws_observations o JOIN pws_sensors s USING(sensor_id) WHERE s.station_id=?",
                        (station_id,),
                    ).fetchone()[0]
                )
                count = 0
                state, error = "STALE", None
                retry = 0.0
                try:
                    data = await provider.fetch_latest(station)
                    for reading, packet in data:
                        await store._call(
                            store.ingest,
                            station,
                            reading,
                            packet,
                            station.station_id not in initialized,
                        )
                        count += 1
                    initialized.add(station.station_id)
                    state = (
                        "HEALTHY"
                        if any(
                            eligible(
                                {
                                    **r.model_dump(mode="json"),
                                    "first_receive_time": p["received_at"],
                                    "provider": station.provider,
                                    "station_id": station.station_id,
                                    "evidence_class": "REALTIME_CAPTURED",
                                },
                                utc_now(),
                                config.qc,
                            )
                            for r, p in data
                        )
                        else "STALE"
                    )
                except (ProviderError, ValueError, KeyError, TypeError, httpx.HTTPError) as exc:
                    error = str(exc) if isinstance(exc, ProviderError) else type(exc).__name__
                    state = (
                        "AUTH_FAILED"
                        if "AUTH" in error
                        else "RATE_LIMITED"
                        if "RATE" in error or "COOLDOWN" in error
                        else "DISABLED"
                        if "DISABLED" in error
                        else "DEGRADED"
                    )
                    retry = exc.retry_seconds if isinstance(exc, ProviderError) else 0
                    await store.error("pws_" + provider.name, error)
                    LOG.warning("provider=%s error_class=%s", provider.name, error)
                await store._call(
                    record_poll,
                    store,
                    provider.name,
                    station.station_id,
                    started,
                    before,
                    state,
                    error,
                    count,
                )
                history = await store._call(
                    rows,
                    store.connection,
                    """SELECT data_json FROM pws_observations
                    WHERE sensor_id=(SELECT min(sensor_id) FROM pws_sensors WHERE station_id=?)
                    ORDER BY first_receive_time DESC LIMIT 512""",
                    (station.station_id,),
                )
                recent = [json.loads(r["data_json"]) for r in history]
                times = [
                    datetime.fromisoformat(t)
                    for r in recent
                    if (t := r.get("observation_time") or r.get("provider_timestamp"))
                ]
                empty[station.station_id] = (
                    empty.get(station.station_id, 0) + 1 if count == 0 else 0
                )
                interval = next_interval(
                    times,
                    policy.minimum_poll_interval,
                    policy.maximum_poll_interval,
                    empty[station.station_id],
                )
                due[station.station_id] = time.monotonic() + max(
                    interval, retry, station.declared_update_interval or 0
                )
        await wait_or_stop(stop, 1)


def heartbeat(
    store: PWSStore, config: Config, started: float, storage: tuple[int, str] | None = None
) -> tuple[int, str]:
    raw_size, checked_at = (
        storage
        if storage is not None
        else (
            sum(p.stat().st_size for p in config.raw_storage_path.rglob("*.json")),
            utc_now().isoformat(),
        )
    )
    db_size = sum(
        p.stat().st_size
        for p in config.database_path.parent.glob(config.database_path.name + "*")
        if p.is_file()
    )
    data = dict(
        uptime_seconds=time.monotonic() - started,
        raw_bytes=raw_size,
        raw_size_checked_at=checked_at,
        database_bytes=db_size,
        performance=store.timings.snapshot(),
        storage_warning=raw_size + db_size >= config.storage_warning_bytes,
    )
    with store.connection:
        store.connection.execute(
            "INSERT INTO continuous_health VALUES(?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET updated_at=excluded.updated_at,data_json=excluded.data_json",
            (store.run_id, os.getpid(), utc_now().isoformat(), json.dumps(data)),
        )
    if data["storage_warning"]:
        LOG.warning("storage_warning threshold_bytes=%s", config.storage_warning_bytes)
    return raw_size, checked_at


def refresh_quality(store: PWSStore, airport: str, config: Config) -> None:
    """Publish QC/calibration only after calculation completes on the sole writer."""
    from premetar.pws.service import quality_snapshot

    conn = store.connection
    cutoff = utc_now()
    quality_id = conn.execute("SELECT COALESCE(max(id),0) FROM pws_quality_results").fetchone()[0]
    calibration_id = conn.execute("SELECT COALESCE(max(id),0) FROM pws_calibrations").fetchone()[0]
    policy = settings()
    policy.qc = config.qc
    quality_snapshot(store, airport, policy, cutoff)
    published = utc_now().isoformat()
    with conn:
        for table, old in (
            ("pws_quality_results", quality_id),
            ("pws_calibrations", calibration_id),
        ):
            # Table names are static internal constants, never provider input.
            for row in rows(conn, f"SELECT id,data_json FROM {table} WHERE id>?", (old,)):
                data = json.loads(row["data_json"])
                data["input_cutoff_time"] = cutoff.isoformat()
                data["published_at"] = published
                conn.execute(
                    f"UPDATE {table} SET created_at=?,data_json=? WHERE id=?",
                    (published, json.dumps(data), row["id"]),
                )


async def run_jobs(
    store: PWSStore,
    client: httpx.AsyncClient,
    stop: asyncio.Event,
    config: Config,
    reference_gate: ReferenceGate | None = None,
) -> None:
    await store._call(migrate, store.connection)
    await store._call(freeze_experiment, store.connection, config)
    pws = settings()
    from premetar.pws.availability import policy as availability_policy

    providers: list[PWSProvider] = [
        PROVIDERS[name](
            Transport(
                client,
                store,
                request_spacing=max(
                    config.polling(name).request_spacing,
                    availability_policy().request_spacing_seconds if name == "opensensemap" else 1,
                ),
                timeout_seconds=config.polling(name).timeout_seconds,
                max_attempts=config.polling(name).max_attempts,
            )
        )
        for name in config.providers
    ]
    await store._call(store.register, pws.airports, providers)
    tasks = [
        asyncio.create_task(provider_loop(store, p, config, stop), name="continuous-" + p.name)
        for p in providers
    ]
    started = time.monotonic()
    next_health = 0.0
    next_storage = 0.0
    storage: tuple[int, str] | None = None
    last_reference_id = -1
    next_settlement = 0.0
    from premetar.continuous.analytical_qc import AnalyticalQC
    from premetar.continuous.analytical_qc import migrate as migrate_analytical

    await store._call(migrate_analytical, store.connection)
    tasks.append(asyncio.create_task(AnalyticalQC(store, config).run(stop), name="analytical-qc"))
    try:
        while not stop.is_set():
            for task in tasks:
                if task.done():
                    task.result()  # infrastructure failure must stop the process for restart
                    raise RuntimeError("Provider loop unexpectedly stopped")
            await store._call(
                schedule, store.connection, config, store.run_id, None, reference_gate
            )
            reference_id = await store._call(
                lambda: store.connection.execute(
                    "SELECT COALESCE(max(id),0) FROM observations WHERE product_type='METAR'"
                ).fetchone()[0]
            )
            if reference_id != last_reference_id or time.monotonic() >= next_settlement:
                await store._call(settle, store.connection, None, max(0, last_reference_id))
                last_reference_id = reference_id
                next_settlement = time.monotonic() + 30
            if time.monotonic() >= next_health:
                storage = await store._call(
                    heartbeat,
                    store,
                    config,
                    started,
                    storage if time.monotonic() < next_storage else None,
                )
                if time.monotonic() >= next_storage:
                    next_storage = time.monotonic() + 3600
                next_health = time.monotonic() + 60
            await wait_or_stop(stop, 1)
    finally:
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)
