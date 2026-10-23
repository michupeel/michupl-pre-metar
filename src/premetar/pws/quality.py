"""Deterministic flags: geographic disagreement is not proof of bad hardware."""

import math
from datetime import datetime
from statistics import median
from typing import Any

from astral import Observer
from astral.sun import elevation

from premetar.pws.geometry import haversine_km
from premetar.pws.models import QCConfig, Station, utc
from premetar.pws.temporal import temporal_metrics

VERSION = "pws-qc-1.0"
HARD_FLAGS = {
    "STUCK_SENSOR",
    "INVALID_TEMPERATURE",
    "UNKNOWN_UNIT",
    "INVALID_TIMESTAMP",
    "IMPOSSIBLE_TEMPERATURE",
    "FUTURE_OBSERVATION",
    "FUTURE_PUBLICATION",
    "INDOOR_SENSOR",
    "MOBILE_SENSOR",
    "CONFLICTING_DUPLICATE",
}


def physical_flags(row: dict[str, Any], now: datetime, config: QCConfig) -> set[str]:
    flags = set(row.get("quality_flags", []))
    value = row.get("temperature_c")
    if value is None or not math.isfinite(value):
        flags.add("INVALID_TEMPERATURE")
    elif not config.min_temperature_c <= value <= config.max_temperature_c:
        flags.add("IMPOSSIBLE_TEMPERATURE")
    humidity = row.get("relative_humidity")
    if humidity is not None and (not math.isfinite(humidity) or not 0 <= humidity <= 100):
        flags.add("INVALID_HUMIDITY")
    for key, flag in (
        ("observation_time", "FUTURE_OBSERVATION"),
        ("source_publish_time", "FUTURE_PUBLICATION"),
        ("provider_timestamp", "FUTURE_PUBLICATION"),
    ):
        value = row.get(key)
        if value:
            try:
                seconds = (utc(datetime.fromisoformat(value)) - utc(now)).total_seconds()
                if seconds > 0:
                    flags.add("CLOCK_ANOMALY")
                if seconds > config.max_future_seconds:
                    flags.add(flag)
            except (ValueError, TypeError):
                flags.add("INVALID_TIMESTAMP")
    return flags


def effective_time(row: dict[str, Any]) -> datetime | None:
    value = (
        row.get("observation_time")
        or row.get("provider_timestamp")
        or row.get("source_publish_time")
    )
    return utc(datetime.fromisoformat(value)) if value else None


def eligible(row: dict[str, Any], at: datetime, config: QCConfig) -> bool:
    at = utc(at)
    clock = effective_time(row)
    receive = row.get("first_receive_time")
    return bool(
        receive
        and utc(datetime.fromisoformat(receive)) <= at
        and row.get("evidence_class") == "REALTIME_CAPTURED"
        and clock
        and clock <= at
        and (at - clock).total_seconds() <= config.stale_seconds
        and not physical_flags(row, at, config).intersection(HARD_FLAGS)
    )


def peer_comparison(
    station: Station,
    value: float,
    at: datetime,
    peers: list[tuple[Station, dict[str, Any]]],
    config: QCConfig,
) -> dict[str, Any]:
    independent: list[tuple[Station, float, float]] = []
    for other, row in sorted(peers, key=lambda x: x[0].station_id):
        distance = haversine_km(
            station.latitude, station.longitude, other.latitude, other.longitude
        )
        if (
            other.station_id == station.station_id
            or distance < 0.2
            or distance > config.spatial_radius_km
        ):
            continue
        if other.exposure == "indoor" or other.mobile or not eligible(row, at, config):
            continue
        # Nearby cross-platform records may be duplicates; one vote per 200m cluster.
        if any(
            haversine_km(other.latitude, other.longitude, p.latitude, p.longitude) < 0.2
            for p, _, _ in independent
        ):
            continue
        temp = row["temperature_c"]
        if (
            station.elevation_verified
            and other.elevation_verified
            and station.elevation_m is not None
            and other.elevation_m is not None
        ):
            temp -= 0.0065 * (station.elevation_m - other.elevation_m)
        independent.append((other, temp, 1 / max(distance, 0.2)))
    if len(independent) < config.peer_minimum:
        return {"peer_count": len(independent), "difference_c": None, "flags": []}
    # Weighted median limits influence of a single close station.
    ordered = sorted(independent, key=lambda p: p[1])
    total = sum(w for _, _, w in ordered)
    cumulative = 0.0
    reference = ordered[-1][1]
    for _, temp, weight in ordered:
        cumulative += weight
        if cumulative >= total / 2:
            reference = temp
            break
    difference = value - reference
    return {
        "peer_count": len(independent),
        "difference_c": difference,
        "flags": ["SPATIAL_DISAGREEMENT", "MICROCLIMATE_OR_SENSOR_BIAS"]
        if abs(difference) > config.spatial_threshold_c
        else [],
    }


def solar_suspicion(
    station: Station, differences: list[tuple[datetime, float]], minimum: int = 20
) -> dict[str, Any]:
    day, night = [], []
    for at, difference in differences:
        solar = elevation(Observer(station.latitude, station.longitude), utc(at))
        if solar > 10:
            day.append(difference)
        elif solar < -6:
            night.append(difference)
    enough = (
        len(day) >= minimum
        and len(night) >= minimum
        and len({utc(t).date() for t, _ in differences}) >= 3
    )
    suspect = enough and median(day) > 2 and median(day) - median(night) > 2
    return {
        "daytime_difference_c": median(day) if len(day) >= minimum else None,
        "nighttime_difference_c": median(night) if len(night) >= minimum else None,
        "flags": ["SOLAR_HEATING_SUSPECT"] if suspect else [],
        "diagnosis": "HEURISTIC_ONLY",
    }


def assess(
    station: Station,
    data: list[dict[str, Any]],
    at: datetime,
    config: QCConfig,
    peers: list[tuple[Station, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    flags: set[str] = set()
    if station.exposure == "indoor":
        flags.add("INDOOR_SENSOR")
    if station.mobile or station.exposure == "mobile":
        flags.add("MOBILE_SENSOR")
    if not station.sensors:
        flags.add("NO_TEMPERATURE_SENSOR")
    metadata = (
        "VERIFIED_METADATA"
        if station.exposure == "outdoor"
        and station.elevation_verified
        and all(s.sensor_type for s in station.sensors)
        else (
            "PARTIAL_METADATA"
            if station.exposure or any(s.sensor_type for s in station.sensors)
            else "UNKNOWN_METADATA"
        )
    )
    sensor_results = {}
    for sensor in station.sensors:
        rows = [r for r in data if r["provider_sensor_id"] == sensor.provider_sensor_id]
        samples = []
        for row in rows:
            row_flags = physical_flags(row, at, config)
            flags.update(row_flags)
            clock = effective_time(row)
            if clock and not row_flags.intersection(HARD_FLAGS) and clock <= at:
                samples.append((clock, row["temperature_c"]))
        ordered_clocks = sorted({t for t, _ in samples})
        gaps = [
            (b - a).total_seconds()
            for a, b in zip(ordered_clocks, ordered_clocks[1:], strict=False)
        ]
        inferred = median(gaps) if len(gaps) >= 10 else None
        expected = station.declared_update_interval or inferred
        metrics = temporal_metrics(
            samples,
            at,
            expected,
            config.stale_seconds,
            config.stuck_seconds,
            config.jump_c_per_min,
        )
        flags.update(metrics["flags"])
        metrics["availability_basis"] = (
            "declared_cadence"
            if station.declared_update_interval
            else "inferred_median_cadence"
            if inferred
            else None
        )
        metrics["clock_basis"] = (
            "sensor" if any(r.get("observation_time") for r in rows) else "provider_server"
        )
        sensor_results[sensor.provider_sensor_id] = metrics
    valid = [r for r in data if eligible(r, at, config)]
    spatial: dict[str, Any] = {"difference_c": None, "flags": [], "peer_count": 0}
    if valid:
        latest = max(valid, key=lambda r: r["first_receive_time"])
        spatial = peer_comparison(station, latest["temperature_c"], at, peers or [], config)
        flags.update(spatial["flags"])
    return {
        "metadata_status": metadata,
        "flags": sorted(flags),
        "sensors": sensor_results,
        "spatial": spatial,
        "algorithm_version": VERSION,
        "created_at": utc(at).isoformat(),
        "sample_count": sum(m["sample_count"] for m in sensor_results.values()),
    }


def historical_peer_differences(
    station: Station,
    data: list[dict[str, Any]],
    histories: list[tuple[Station, list[dict[str, Any]]]],
    config: QCConfig,
) -> list[tuple[datetime, float]]:
    differences = []
    seen = set()
    # Bounded deterministic recent sample window; samples are checked as of their own receipts.
    for row in sorted(data, key=lambda r: r["first_receive_time"])[-1000:]:
        at = utc(datetime.fromisoformat(row["first_receive_time"]))
        clock = effective_time(row)
        if not clock or clock in seen or not eligible(row, at, config):
            continue
        seen.add(clock)
        peers = []
        for other, other_data in histories:
            candidates = [p for p in other_data if eligible(p, at, config)]
            if candidates:
                peers.append((other, max(candidates, key=lambda r: str(effective_time(r)))))
        comparison = peer_comparison(station, row["temperature_c"], at, peers, config)
        if comparison["difference_c"] is not None:
            differences.append((clock, comparison["difference_c"]))
    return differences


def score(
    components: dict[str, float | None],
    sample_count: int,
    evaluation_days: int,
    flags: list[str],
    config: QCConfig,
) -> dict[str, Any]:
    weights = config.weights
    names = {"predictive", "temporal", "freshness", "spatial", "geographic", "metadata"}
    if (
        set(weights) != names
        or any(not math.isfinite(w) or w < 0 for w in weights.values())
        or not math.isclose(sum(weights.values()), 1)
    ):
        raise ValueError("Six nonnegative score weights must sum to one")
    complete = all(components.get(k) is not None for k in names)
    sufficient = (
        sample_count >= config.min_samples and evaluation_days >= config.min_evaluation_days
    )
    if not complete or not sufficient:
        return {"score": None, "status": "UNVERIFIED", "components": components}
    for value in components.values():
        if value is not None and (not math.isfinite(value) or not 0 <= value <= 100):
            raise ValueError("Invalid score component")
    result = sum(weights[k] * float(components[k] or 0) for k in names)
    # TRUSTED requires manual promotion after independent held-out review; never automatic.
    status = (
        "UNRELIABLE"
        if set(flags).intersection(HARD_FLAGS)
        else "CANDIDATE"
        if result >= 70
        else "EXPERIMENTAL"
    )
    return {"score": round(result, 2), "status": status, "components": components}
