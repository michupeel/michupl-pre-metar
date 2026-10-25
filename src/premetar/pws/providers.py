"""Documented read-only APIs. HTTP bytes are durably captured before decoding."""

import asyncio
import json
import math
import re
import time
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from premetar.collector import retry_after
from premetar.model import utc_now
from premetar.pws.geometry import bounding_boxes, haversine_km
from premetar.pws.models import Capabilities, Reading, Sensor, Station
from premetar.store import Store


class ProviderError(Exception):
    def __init__(self, code: str, retry_seconds: float = 0) -> None:
        super().__init__(code)
        self.retry_seconds = retry_seconds


class Transport:
    def __init__(
        self,
        client: httpx.AsyncClient,
        store: Store,
        *,
        request_spacing: float = 1,
        timeout_seconds: float = 20,
        max_attempts: int = 3,
    ) -> None:
        if (
            not math.isfinite(request_spacing)
            or request_spacing < 1
            or not 1 <= timeout_seconds <= 60
            or not 1 <= max_attempts <= 3
        ):
            raise ValueError("Unsafe provider transport policy")
        self.request_spacing, self.timeout_seconds, self.max_attempts = (
            request_spacing,
            timeout_seconds,
            max_attempts,
        )
        self.client, self.store = client, store
        self.next_request: dict[str, float] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        self.disabled: set[str] = set()
        self.last_packets: dict[str, dict[str, Any]] = {}

    async def get(
        self, provider: str, url: str, headers: dict[str, str] | None = None
    ) -> tuple[Any, dict[str, Any]]:
        async with self.locks.setdefault(provider, asyncio.Lock()):
            self.last_packets.pop(provider, None)
            if provider in self.disabled:
                raise ProviderError("PROVIDER_DISABLED")
            for attempt in range(self.max_attempts):
                delay = max(0, self.next_request.get(provider, 0) - time.monotonic())
                if delay > 30:
                    raise ProviderError("PROVIDER_COOLDOWN", delay)
                await asyncio.sleep(delay)
                start, mono = utc_now(), time.perf_counter_ns()
                self.next_request[provider] = time.monotonic() + self.request_spacing
                try:
                    response = await self.client.get(
                        url, headers=headers, timeout=self.timeout_seconds
                    )
                except (httpx.TimeoutException, httpx.NetworkError):
                    if attempt == self.max_attempts - 1:
                        raise ProviderError("TRANSPORT_FAILURE") from None
                    self.next_request[provider] = max(
                        self.next_request.get(provider, 0), time.monotonic() + 2**attempt
                    )
                    continue
                end, end_mono = utc_now(), time.perf_counter_ns()
                packet = await self.store.capture(
                    {
                        "source": "pws_" + provider,
                        "request_url": str(response.request.url),
                        "http_status": response.status_code,
                        "headers": dict(response.headers),
                        "request_start": start.isoformat(),
                        "request_end": end.isoformat(),
                        "received_at": end.isoformat(),
                        "request_start_monotonic_ns": mono,
                        "monotonic_ns": end_mono,
                    },
                    response.content,
                )
                self.last_packets[provider] = packet
                if response.status_code in (401, 403) or 300 <= response.status_code < 400:
                    self.disabled.add(provider)
                    raise ProviderError("AUTH_OR_REDIRECT_DISABLED")
                if response.status_code == 429:
                    delay = max(300, retry_after(response.headers.get("Retry-After"), end))
                    self.next_request[provider] = time.monotonic() + delay
                    raise ProviderError("RATE_LIMITED", delay)
                if response.status_code >= 500 and attempt < self.max_attempts - 1:
                    self.next_request[provider] = max(
                        self.next_request.get(provider, 0), time.monotonic() + 2**attempt
                    )
                    continue
                if response.status_code != 200:
                    raise ProviderError(f"HTTP_{response.status_code}")
                try:
                    return json.loads(response.content), packet
                except (ValueError, UnicodeError):
                    raise ProviderError("INVALID_JSON") from None
            raise ProviderError("RETRIES_EXHAUSTED")


class PWSProvider(Protocol):
    name: str
    status: str
    capabilities: Capabilities

    async def discover(
        self, latitude: float, longitude: float, radius_km: float
    ) -> list[tuple[Station, dict[str, Any]]]: ...
    async def fetch_latest(self, station: Station) -> list[tuple[Reading, dict[str, Any]]]: ...
    async def fetch_history(
        self, station: Station, start: datetime, end: datetime
    ) -> list[tuple[Reading, dict[str, Any]]]: ...


def timestamp(value: Any, *, server_utc: bool = False) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (float, int)):
        return datetime.fromtimestamp(value, UTC)
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        if not server_utc:
            raise ValueError("Undocumented naive timestamp")
        result = result.replace(tzinfo=UTC)
    return result.astimezone(UTC)


def reading(
    sensor_id: str,
    value: Any,
    unit: str | None,
    observed: Any,
    humidity: Any = None,
    published: Any = None,
    flags: list[str] | None = None,
) -> Reading:
    flags = list(flags or [])
    temp = rh = None
    try:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError
        if unit in ("°C", "C", "degC", "celsius"):
            temp = number
        elif unit in ("°F", "F"):
            temp = (number - 32) * 5 / 9
        elif unit == "K":
            temp = number - 273.15
        else:
            flags.append("UNKNOWN_UNIT")
    except (TypeError, ValueError):
        flags.append("INVALID_TEMPERATURE")
    if humidity is not None:
        try:
            rh = float(humidity)
            if not math.isfinite(rh):
                rh = None
                flags.append("INVALID_HUMIDITY")
        except (ValueError, TypeError):
            flags.append("INVALID_HUMIDITY")
    try:
        event = timestamp(observed)
        publish = timestamp(published)
    except (ValueError, TypeError, OverflowError, OSError):
        event = publish = None
        flags.append("INVALID_TIMESTAMP")
    if event is None:
        flags.append("UNKNOWN_OBSERVATION_TIME")
    return Reading(
        provider_sensor_id=sensor_id,
        observation_time=event,
        timestamp_provenance="SENSOR_MEASUREMENT_TIME" if event else "UNKNOWN_TIME",
        timestamp_semantics_verified=event is not None,
        source_publish_time=publish,
        temperature_c=temp,
        relative_humidity=rh,
        raw_temperature=None if value is None else str(value),
        raw_unit=unit,
        quality_flags=sorted(set(flags)),
    )


def identifier(value: Any) -> str:
    result = str(value)
    if not re.fullmatch(r"[A-Za-z0-9:_-]{1,160}", result):
        raise ValueError("Invalid provider identifier")
    return quote(result, safe="")


class OpenSenseMap:
    name = "opensensemap"
    status = "PARTIALLY_VERIFIED"
    capabilities = Capabilities(
        geographic_discovery=True,
        latest_observation=True,
        historical_observations=True,
        temperature=True,
        humidity=True,
        elevation=True,
        sensor_metadata=True,
    )

    def __init__(self, transport: Transport) -> None:
        self.http = transport

    @staticmethod
    def parse_station(box: dict[str, Any]) -> Station:
        coords = box["currentLocation"]["coordinates"]
        sensors = [
            Sensor(
                provider_sensor_id=identifier(s["_id"]),
                unit=s.get("unit"),
                sensor_type=s.get("sensorType"),
                metadata=s,
            )
            for s in box.get("sensors", [])
            if str(s.get("title", "")).casefold()
            in ("temperatur", "temperature", "air temperature", "lufttemperatur")
        ]
        return Station(
            provider="opensensemap",
            provider_station_id=identifier(box["_id"]),
            station_name=box.get("name"),
            latitude=coords[1],
            longitude=coords[0],
            elevation_m=coords[2] if len(coords) > 2 else None,
            exposure=box.get("exposure"),
            mobile=(box.get("exposure") == "mobile")
            if box.get("exposure") in ("indoor", "outdoor", "mobile")
            else None,
            sensors=sensors,
            provider_metadata=box,
        )

    async def discover(
        self, latitude: float, longitude: float, radius_km: float
    ) -> list[tuple[Station, dict[str, Any]]]:
        result = {}
        for bbox in bounding_boxes(latitude, longitude, radius_km):
            data, packet = await self.http.get(
                self.name, "https://api.opensensemap.org/boxes?bbox=" + ",".join(map(str, bbox))
            )
            if not isinstance(data, list):
                raise ProviderError("INVALID_DISCOVERY_SCHEMA")
            for box in data:
                try:
                    station = self.parse_station(box)
                except (KeyError, TypeError, ValueError, IndexError, AttributeError):
                    await self.http.store.error("pws_" + self.name, "INVALID_STATION", packet["id"])
                    continue
                if (
                    haversine_km(latitude, longitude, station.latitude, station.longitude)
                    <= radius_km
                ):
                    result[station.station_id] = (station, packet)
        return list(result.values())

    async def fetch_latest(self, station: Station) -> list[tuple[Reading, dict[str, Any]]]:
        self.last_packet = None
        try:
            data, packet = await self.http.get(
                self.name,
                f"https://api.opensensemap.org/boxes/{identifier(station.provider_station_id)}/sensors",
            )
        finally:
            self.last_packet = getattr(self.http, "last_packets", {}).get(self.name)
        self.last_packet = packet
        # Documented endpoint returns a box with sensors, not an untyped list of values.
        if not isinstance(data, dict) or not isinstance(data.get("sensors"), list):
            raise ProviderError("INVALID_LATEST_SCHEMA")
        if any(
            not isinstance(s, dict)
            or (s.get("lastMeasurement") is not None and not isinstance(s["lastMeasurement"], dict))
            for s in data["sensors"]
        ):
            raise ProviderError("INVALID_LATEST_SCHEMA")
        known = {s.provider_sensor_id for s in station.sensors}
        return [
            (
                reading(
                    s["_id"],
                    (s.get("lastMeasurement") or {}).get("value"),
                    s.get("unit"),
                    (s.get("lastMeasurement") or {}).get("createdAt"),
                ),
                packet,
            )
            for s in data["sensors"]
            if s.get("_id") in known
        ]

    async def fetch_history(
        self, station: Station, start: datetime, end: datetime
    ) -> list[tuple[Reading, dict[str, Any]]]:
        if (
            start.tzinfo is None
            or end.tzinfo is None
            or not 0 < (end - start).total_seconds() <= 28 * 86400
        ):
            raise ValueError("History requests must be aware and bounded to 28 days")
        result: list[tuple[Reading, dict[str, Any]]] = []
        for sensor in station.sensors:
            params = httpx.QueryParams(
                {"from-date": start.isoformat(), "to-date": end.isoformat(), "format": "json"}
            )
            data, packet = await self.http.get(
                self.name,
                f"https://api.opensensemap.org/boxes/{identifier(station.provider_station_id)}/data/{identifier(sensor.provider_sensor_id)}?{params}",
            )
            if not isinstance(data, list):
                raise ProviderError("INVALID_HISTORY_SCHEMA")
            if len(data) >= 10000:
                raise ProviderError("HISTORY_POSSIBLY_TRUNCATED")
            result.extend(
                (
                    reading(
                        sensor.provider_sensor_id,
                        row.get("value"),
                        sensor.unit,
                        row.get("createdAt"),
                    ).model_copy(update={"evidence_class": "HISTORICAL_EVENT_ONLY"}),
                    packet,
                )
                for row in data
            )
        return result


class SensorCommunity:
    name = "sensor_community"
    status = "PARTIALLY_VERIFIED"
    capabilities = Capabilities(
        geographic_discovery=True,
        latest_observation=True,
        temperature=True,
        humidity=True,
        sensor_metadata=True,
    )

    def __init__(self, transport: Transport) -> None:
        self.http = transport

    @staticmethod
    def parse_station(row: dict[str, Any]) -> Station:
        location, sensor = row["location"], row["sensor"]
        # A public location is a grouping, not proof of one physical device.
        sensors = [
            Sensor(
                provider_sensor_id=str(sensor["id"]),
                unit="°C",
                sensor_type=sensor.get("sensor_type", {}).get("name"),
                metadata=sensor,
            )
        ]
        return Station(
            provider="sensor_community",
            provider_station_id=str(location["id"]),
            latitude=location["latitude"],
            longitude=location["longitude"],
            exposure="indoor"
            if location.get("indoor") == 1
            else ("outdoor" if location.get("indoor") == 0 else None),
            sensors=sensors,
            provider_metadata={"location": location, "sensor": sensor},
        )

    async def discover(
        self, latitude: float, longitude: float, radius_km: float
    ) -> list[tuple[Station, dict[str, Any]]]:
        bounding_boxes(latitude, longitude, radius_km)
        data, packet = await self.http.get(
            self.name,
            f"https://data.sensor.community/airrohr/v1/filter/area={latitude},{longitude},{radius_km}",
        )
        if not isinstance(data, list):
            raise ProviderError("INVALID_DISCOVERY_SCHEMA")
        stations: dict[str, Station] = {}
        for row in data:
            try:
                if not any(v.get("value_type") == "temperature" for v in row["sensordatavalues"]):
                    continue
                station = self.parse_station(row)
                if (
                    haversine_km(latitude, longitude, station.latitude, station.longitude)
                    > radius_km
                ):
                    continue
                old = stations.get(station.station_id)
                if old:
                    if station.sensors[0].provider_sensor_id not in {
                        s.provider_sensor_id for s in old.sensors
                    }:
                        old.sensors.extend(station.sensors)
                else:
                    stations[station.station_id] = station
            except (KeyError, ValueError, TypeError, AttributeError):
                await self.http.store.error("pws_" + self.name, "INVALID_STATION", packet["id"])
        return [(s, packet) for s in stations.values()]

    async def fetch_latest(self, station: Station) -> list[tuple[Reading, dict[str, Any]]]:
        result: list[tuple[Reading, dict[str, Any]]] = []
        for sensor in station.sensors:
            data, packet = await self.http.get(
                self.name,
                f"https://data.sensor.community/airrohr/v1/sensor/{identifier(sensor.provider_sensor_id)}/",
            )
            if not isinstance(data, list):
                raise ProviderError("INVALID_LATEST_SCHEMA")
            for row in data:
                if str(row.get("sensor", {}).get("id")) != sensor.provider_sensor_id:
                    raise ProviderError("SENSOR_ID_MISMATCH")
                values = {v["value_type"]: v["value"] for v in row.get("sensordatavalues", [])}
                # Upstream server assigns this clock: never invent a measurement clock.
                try:
                    publish = timestamp(row.get("timestamp"), server_utc=True)
                except (ValueError, TypeError):
                    publish = None
                result.append(
                    (
                        reading(
                            sensor.provider_sensor_id,
                            values.get("temperature"),
                            "°C",
                            None,
                            values.get("humidity"),
                            None,
                            ["SERVER_TIMESTAMP_ONLY"],
                        ).model_copy(
                            update={
                                "provider_timestamp": publish,
                                "provider_timestamp_kind": "server_ingest",
                                "timestamp_provenance": "PROVIDER_INGEST_TIME",
                                "timestamp_semantics_verified": False,
                            }
                        ),
                        packet,
                    )
                )
        return result

    async def fetch_history(
        self, station: Station, start: datetime, end: datetime
    ) -> list[tuple[Reading, dict[str, Any]]]:
        raise NotImplementedError("Daily archive exists; archive import is not implemented")


class Netatmo:
    name = "netatmo"
    status = "BLOCKED"
    capabilities = Capabilities()

    def __init__(self, transport: Transport) -> None:
        self.http = transport
        from premetar.pws.netatmo_auth import NetatmoAuth

        self.auth = NetatmoAuth()

    async def discover(
        self, latitude: float, longitude: float, radius_km: float
    ) -> list[tuple[Station, dict[str, Any]]]:
        if not self.auth.access_token and not self.auth.refresh_token:
            raise ProviderError("NETATMO_CREDENTIALS_UNAVAILABLE")
        raise ProviderError("NETATMO_RUNTIME_UNVERIFIED")

    async def fetch_latest(self, station: Station) -> list[tuple[Reading, dict[str, Any]]]:
        raise ProviderError("NETATMO_RUNTIME_UNVERIFIED")

    async def fetch_history(
        self, station: Station, start: datetime, end: datetime
    ) -> list[tuple[Reading, dict[str, Any]]]:
        raise NotImplementedError("Public history not verified")


PROVIDERS: dict[str, type[OpenSenseMap] | type[SensorCommunity] | type[Netatmo]] = {
    "opensensemap": OpenSenseMap,
    "sensor_community": SensorCommunity,
    "netatmo": Netatmo,
}
