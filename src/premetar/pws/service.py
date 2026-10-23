"""Bounded PWS scheduling, quality snapshots and research report generation."""

import asyncio
import csv
import hashlib
import json
import ssl
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from statistics import median
from typing import Any
from uuid import uuid4

import httpx
import polars as pl
import truststore
from astral import Observer
from astral.sun import elevation

from premetar.collector import clock_status, wait_or_stop
from premetar.model import utc_now
from premetar.pws.analysis import (
    calibrate,
    correction,
    evaluate_predictions,
    make_pairs,
    precise_reference_comparison,
    walk_forward,
)
from premetar.pws.geometry import haversine_km
from premetar.pws.models import Settings, Station
from premetar.pws.providers import PROVIDERS, ProviderError, PWSProvider, Transport
from premetar.pws.quality import (
    VERSION,
    assess,
    eligible,
    historical_peer_differences,
    score,
    solar_suspicion,
)
from premetar.pws.repository import PWSStore, inventory, readings, rows, selected


def settings(path: Path | None = None) -> Settings:
    return Settings.model_validate_json(
        path.read_text(encoding="utf-8")
        if path
        else files("premetar.pws").joinpath("airports.json").read_text(encoding="utf-8")
    )


@asynccontextmanager
async def session(
    database: Path, raw_path: Path, config: Settings, operation: str
) -> AsyncIterator[tuple[PWSStore, list[PWSProvider]]]:
    database.parent.mkdir(parents=True, exist_ok=True)
    lock = database.with_suffix(database.suffix + ".lock")
    handle = lock.open("x", encoding="utf-8")
    run_id = "pws-" + utc_now().strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:8]
    store = PWSStore(database, raw_path, run_id)
    opened = False
    try:
        handle.write(run_id)
        handle.flush()
        protocol = files("premetar").joinpath("protocol.md").read_text(encoding="utf-8")
        pws_protocol = files("premetar.pws").joinpath("protocol.md").read_text(encoding="utf-8")
        manifest = {
            "run_id": run_id,
            "operation": operation,
            "settings": config.model_dump(),
            "clock": await asyncio.to_thread(clock_status),
            "pws_protocol": pws_protocol,
            "pws_protocol_sha256": hashlib.sha256(pws_protocol.encode()).hexdigest(),
            "metar_protocol": protocol,
        }
        await store.open(manifest, {"pws_" + p: config.poll_seconds for p in config.providers})
        opened = True
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20),
            follow_redirects=False,
            verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
            headers={
                "User-Agent": "michupl-pre-metar/0.1 (+https://github.com/michupeel/michupl-pre-metar)"
            },
        ) as client:
            transport = Transport(client, store)
            providers: list[PWSProvider] = [PROVIDERS[p](transport) for p in config.providers]
            await store._call(store.register, config.airports, providers)
            yield store, providers
    finally:
        try:
            if opened:
                await store.close("pws_session_closed")
            else:
                store.executor.shutdown(wait=True)
        finally:
            handle.close()
            lock.unlink()


async def discover(
    store: PWSStore,
    providers: list[PWSProvider],
    config: Settings,
    airports: set[str],
    radius: float,
) -> list[dict[str, Any]]:
    result = []
    for provider in providers:
        for airport in config.airports:
            if airport.icao not in airports:
                continue
            try:
                found = await provider.discover(airport.latitude, airport.longitude, radius)
                for station, packet in found:
                    await store._call(store.discover, airport, station, packet)
                result.append(
                    {
                        "airport": airport.icao,
                        "provider": provider.name,
                        "stations": len(found),
                        "temperature_stations": sum(bool(s.sensors) for s, _ in found),
                        "status": "OBSERVED",
                        "radius_km": radius,
                        "received_at": utc_now().isoformat(),
                    }
                )
            except (ProviderError, ValueError, KeyError, TypeError) as exc:
                code = str(exc) if isinstance(exc, ProviderError) else type(exc).__name__
                await store.error("pws_" + provider.name, code)
                result.append(
                    {
                        "airport": airport.icao,
                        "provider": provider.name,
                        "stations": None,
                        "status": code,
                    }
                )
    return result


async def collect(
    store: PWSStore,
    providers: list[PWSProvider],
    config: Settings,
    airports: set[str],
    duration: float,
    stop: asyncio.Event | None = None,
) -> dict[str, Any]:
    if not 0 < duration <= 86400:
        raise ValueError("Collection duration must be in (0,86400] seconds")
    stop = stop or asyncio.Event()
    deadline = time.monotonic() + duration
    initialized: set[str] = set()
    counts: dict[str, int] = {}

    async def loop(provider: PWSProvider) -> None:
        due: dict[str, float] = {}
        while time.monotonic() < deadline and not stop.is_set():
            for airport in config.airports:
                if time.monotonic() >= deadline or stop.is_set():
                    break
                if airport.icao not in airports:
                    continue
                items = await store._call(inventory, store.connection, airport.icao)
                latest = await store._call(
                    rows,
                    store.connection,
                    "SELECT max(at) latest FROM pws_discoveries d JOIN pws_stations s USING(station_id) WHERE s.provider=? AND d.airport_icao=?",
                    (provider.name, airport.icao),
                )
                if (
                    not latest[0]["latest"]
                    or (utc_now() - datetime.fromisoformat(latest[0]["latest"])).total_seconds()
                    >= config.discovery_seconds
                ):
                    if time.monotonic() >= due.get("discovery-" + airport.icao, 0):
                        await discover(
                            store, [provider], config, {airport.icao}, max(config.radii_km)
                        )
                        due["discovery-" + airport.icao] = (
                            time.monotonic() + config.discovery_seconds
                        )
                        items = await store._call(inventory, store.connection, airport.icao)
                for item in items:
                    if time.monotonic() >= deadline or stop.is_set():
                        break
                    if item["provider"] != provider.name or time.monotonic() < due.get(
                        item["station_id"], 0
                    ):
                        continue
                    active = await store._call(
                        selected, store.connection, item["station_id"], airport.icao, utc_now()
                    )
                    if not active:
                        continue
                    station = Station.model_validate_json(item["data_json"])
                    interval = max(config.poll_seconds, station.declared_update_interval or 0)
                    # Poll no faster than the observed sensor update cadence.
                    old = await store._call(
                        readings, store.connection, station.station_id, utc_now()
                    )
                    times = sorted(
                        {
                            str(
                                r.get("observation_time")
                                or r.get("provider_timestamp")
                                or r.get("source_publish_time")
                            )
                            for r in old
                            if r.get("observation_time")
                            or r.get("provider_timestamp")
                            or r.get("source_publish_time")
                        }
                    )
                    if len(times) >= 4:
                        interval = max(
                            interval,
                            median(
                                (
                                    datetime.fromisoformat(b) - datetime.fromisoformat(a)
                                ).total_seconds()
                                for a, b in zip(times, times[1:], strict=False)
                            ),
                        )
                    try:
                        observations = await provider.fetch_latest(station)
                        for reading, packet in observations:
                            await store._call(
                                store.ingest,
                                station,
                                reading,
                                packet,
                                station.station_id not in initialized,
                            )
                            counts[provider.name] = counts.get(provider.name, 0) + 1
                        initialized.add(station.station_id)
                    except (ProviderError, ValueError, KeyError, TypeError) as exc:
                        if isinstance(exc, ProviderError):
                            interval = max(interval, exc.retry_seconds)
                        await store.error(
                            "pws_" + provider.name,
                            str(exc) if isinstance(exc, ProviderError) else type(exc).__name__,
                        )
                    due[station.station_id] = time.monotonic() + interval
            await store.heartbeat()
            remaining = deadline - time.monotonic()
            if remaining > 0:
                await wait_or_stop(stop, min(1, remaining))

    await asyncio.gather(*(loop(p) for p in providers))
    return {"received_readings": counts, "duration_limit_seconds": duration}


def quality_snapshot(
    store: PWSStore, airport: str, config: Settings, at: datetime
) -> list[dict[str, Any]]:
    connection = store.connection
    items = inventory(connection, airport)
    histories = {i["station_id"]: readings(connection, i["station_id"], at) for i in items}
    peers = []
    for item in items:
        valid = [r for r in histories[item["station_id"]] if eligible(r, at, config.qc)]
        if valid:
            peers.append(
                (
                    Station.model_validate_json(item["data_json"]),
                    max(valid, key=lambda r: r["first_receive_time"]),
                )
            )
    output = []
    with connection:
        for item in items:
            station = Station.model_validate_json(item["data_json"])
            history = histories[item["station_id"]]
            qc = assess(station, history, at, config.qc, peers)
            history_peers = [
                (Station.model_validate_json(i["data_json"]), histories[i["station_id"]])
                for i in items
                if i["station_id"] != station.station_id
            ]
            differences = historical_peer_differences(station, history, history_peers, config.qc)
            qc["solar"] = solar_suspicion(station, differences)
            qc["flags"] = sorted(set(qc["flags"]) | set(qc["solar"]["flags"]))
            if (
                len(differences) >= 20
                and len({t.date() for t, _ in differences}) >= 3
                and abs(median(d for _, d in differences)) > config.qc.spatial_threshold_c
            ):
                qc["flags"] = sorted(
                    set(qc["flags"]) | {"PERSISTENT_SPATIAL_ANOMALY", "MICROCLIMATE_OR_SENSOR_BIAS"}
                )
            pairs = make_pairs(connection, airport, station.station_id, config.qc, at)
            predictive = walk_forward(pairs, config.qc)
            precise_reference = precise_reference_comparison(
                connection, airport, station.station_id, config.qc, at
            )
            predictive["temperature_bias_estimate"] = correction(pairs, at, config.qc)
            predictive["bias_uncertainty"] = "QUANTIZED_REFERENCE_NOT_EXACT_SENSOR_BIAS"
            for label, lower, upper in (
                ("daytime_performance", 10, 90),
                ("nighttime_performance", -90, -6),
            ):
                subset = [
                    p
                    for p in predictive["rows"]
                    if lower
                    <= elevation(
                        Observer(station.latitude, station.longitude),
                        datetime.fromisoformat(p["target_time"]),
                    )
                    <= upper
                ]
                predictive[label] = (
                    sum(p["calibrated_match"] for p in subset) / len(subset)
                    if len(subset) >= config.qc.calibration_minimum
                    else None
                )
            calibrate(connection, station.station_id, airport, pairs, at, config.qc)
            metrics = list(qc["sensors"].values())
            intervals = [
                s["median_update_interval"]
                for s in metrics
                if s["median_update_interval"] is not None
            ]
            ages = [s["observation_age"] for s in metrics if s["observation_age"] is not None]
            availability = [s["availability"] for s in metrics if s["availability"] is not None]
            components = {
                "predictive": 100 * predictive["integer_metar_match_rate"]
                if predictive["integer_metar_match_rate"] is not None
                else None,
                "temporal": max(
                    0,
                    100
                    - 25
                    * len(
                        set(qc["flags"])
                        & {
                            "IRREGULAR_UPDATES",
                            "MISSING_INTERVALS",
                            "STUCK_SUSPECT",
                            "STUCK_SENSOR",
                        }
                    ),
                )
                if qc["sample_count"] >= config.qc.min_samples
                else None,
                "freshness": 100
                * min(availability)
                * max(0, 1 - min(ages) / config.qc.stale_seconds)
                if availability and ages
                else None,
                "spatial": max(0, 100 - 20 * abs(qc["spatial"]["difference_c"]))
                if qc["spatial"]["difference_c"] is not None
                else None,
                "geographic": max(0, 100 * (1 - item["distance_km"] / max(config.radii_km))),
                "metadata": {
                    "VERIFIED_METADATA": 100,
                    "PARTIAL_METADATA": 60,
                    "UNKNOWN_METADATA": None,
                }[qc["metadata_status"]],
            }
            ranked = score(
                components,
                predictive["sample_count"],
                predictive["evaluation_days"],
                qc["flags"],
                config.qc,
            )
            row = {
                "station_id": station.station_id,
                "airport_icao": airport,
                "provider": station.provider,
                "distance_km": item["distance_km"],
                "observation_age_seconds": min(ages) if ages else None,
                "median_update_interval": median(intervals) if intervals else None,
                "availability": min(availability) if availability else None,
                "selected": selected(connection, station.station_id, airport, at),
                "predictive": {k: v for k, v in predictive.items() if k != "rows"},
                "precise_reference": precise_reference,
                **qc,
                **ranked,
            }
            connection.execute(
                "INSERT INTO pws_quality_results VALUES(NULL,?,?,?,?,?)",
                (station.station_id, airport, at.isoformat(), VERSION, json.dumps(row)),
            )
            output.append(row)
    return sorted(output, key=lambda r: (r["score"] is None, -(r["score"] or 0), r["distance_km"]))


def write_reports(
    store: PWSStore, airports: set[str], config: Settings, output: Path
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    at = utc_now()
    rankings = [r for a in sorted(airports) for r in quality_snapshot(store, a, config, at)]
    inventory_rows = []
    for airport in sorted(airports):
        for item in inventory(store.connection, airport):
            station = Station.model_validate_json(item["data_json"])
            inventory_rows.append(
                {
                    "station_id": station.station_id,
                    "provider": station.provider,
                    "provider_station_id": station.provider_station_id,
                    "station_name": station.station_name,
                    "latitude": station.latitude,
                    "longitude": station.longitude,
                    "elevation_m": station.elevation_m,
                    "exposure": station.exposure,
                    "airport_icao": airport,
                    "distance_km": item["distance_km"],
                    "temperature_sensor_count": len(station.sensors),
                    "first_discovered_at": item["first_discovered_at"],
                    "last_discovered_at": item["last_discovered_at"],
                    "last_observation_time": item["last_observation_time"],
                }
            )
    flat = [
        {
            **{k: v for k, v in r.items() if not isinstance(v, (dict, list))},
            **{"component_" + k: v for k, v in r["components"].items()},
            **{
                "predictive_" + k: v
                for k, v in r["predictive"].items()
                if not isinstance(v, (dict, list))
            },
            "quality_flags": ";".join(r["flags"]),
        }
        for r in rankings
    ]
    prediction_results = [
        r
        for airport in sorted(airports)
        for r in evaluate_predictions(store.connection, airport, at)
    ]
    duplicate_candidates = []
    for index, left in enumerate(inventory_rows):
        for right in inventory_rows[index + 1 :]:
            if (
                left["airport_icao"] != right["airport_icao"]
                or left["provider"] == right["provider"]
            ):
                continue
            distance = haversine_km(
                left["latitude"], left["longitude"], right["latitude"], right["longitude"]
            )
            if distance < 0.2:
                duplicate_candidates.append(
                    {
                        "airport_icao": left["airport_icao"],
                        "station_id_a": left["station_id"],
                        "station_id_b": right["station_id"],
                        "separation_km": distance,
                        "reason": "POSSIBLE_SHARED_SITE_NOT_MERGED",
                    }
                )
    latency = rows(
        store.connection,
        """SELECT s.provider,a.received_at,a.request_start,a.request_end,
        o.observation_time,o.source_publish_time,o.data_json,o.evidence_class FROM pws_arrivals a
        JOIN pws_observations o ON o.id=a.observation_id JOIN pws_sensors sn USING(sensor_id)
        JOIN pws_stations s USING(station_id)""",
    )
    for row in latency:
        details = json.loads(row.pop("data_json"))
        row["provider_timestamp"] = details.get("provider_timestamp")
        row["provider_timestamp_kind"] = details.get("provider_timestamp_kind")
        clock = row["observation_time"] or row["provider_timestamp"] or row["source_publish_time"]
        row["age_at_receive_seconds"] = (
            (
                datetime.fromisoformat(row["received_at"]) - datetime.fromisoformat(clock)
            ).total_seconds()
            if clock
            else None
        )
        row["age_basis"] = (
            "observation" if row["observation_time"] else "provider_server" if clock else "unknown"
        )
    for name, data in (
        ("station_inventory", inventory_rows),
        ("station_rankings", flat),
        ("provider_latency", latency),
        ("prediction_results", prediction_results),
        (
            "precise_reference",
            [
                {
                    "station_id": r["station_id"],
                    "airport_icao": r["airport_icao"],
                    **r["precise_reference"],
                }
                for r in rankings
            ],
        ),
        ("duplicate_candidates", duplicate_candidates),
    ):
        with (output / f"{name}.csv").open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(data[0]) if data else ["status"])
            writer.writeheader()
            writer.writerows(data)
        pl.DataFrame(data if data else {"status": []}, infer_schema_length=None).write_parquet(
            output / f"{name}.parquet"
        )
    counts = {a: sum(r["airport_icao"] == a for r in rankings) for a in sorted(airports)}
    summary: dict[str, Any] = {
        "created_at": at.isoformat(),
        "station_counts": counts,
        "rankings": rankings,
        "realtime_prediction_evaluation": prediction_results,
        "conclusion": "INSUFFICIENT DATA"
        if not any(r["score"] is not None for r in rankings)
        else "EXPLORATORY ONLY",
        "attribution": "openSenseMap contributors (data terms pending verification); Sensor.Community contributors (DbCL/ODbL).",
    }
    (output / "quality.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    text = f"# Open PWS research — {at.isoformat()}\n\n{summary['conclusion']}\n\nStation/airport associations: {counts}\n\n"
    text += f"Temperature stations: {sum(r['temperature_sensor_count'] > 0 for r in inventory_rows)}; selected associations: {sum(r['selected'] for r in rankings)}; fresh associations: {sum(r['observation_age_seconds'] is not None and r['observation_age_seconds'] <= config.qc.stale_seconds for r in rankings)}.\n\n"
    text += (
        "Raw and calibrated accuracy are quantized-reference exploratory replays. No held-out station selection validation or measured real-time information edge is established. Missing scores are UNVERIFIED, not failures. Availability is NULL without an expected cadence. Sensor.Community ages use its server clock, not a known measurement time. See CSV/Parquet and quality.json for flags/components.\n\n"
        + summary["attribution"]
        + "\n"
    )
    for name in ("discovery_summary", "quality_report", "predictive_value"):
        (output / f"{name}.md").write_text(text, encoding="utf-8")
    return summary
