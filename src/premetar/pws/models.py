import math
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timezone-aware UTC timestamps required")
    return value.astimezone(UTC)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Airport(Model):
    icao: str = Field(pattern=r"^[A-Z]{4}$")
    name: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    elevation_m: float | None = None
    reference: str


class Sensor(Model):
    provider_sensor_id: str
    phenomenon: str = "temperature"
    unit: str | None = None
    sensor_type: str | None = None
    sensor_model: str | None = None
    manufacturer: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Station(Model):
    provider: str
    provider_station_id: str
    station_name: str | None = None
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    elevation_m: float | None = None
    elevation_verified: bool = False
    exposure: str | None = None
    mobile: bool | None = None
    declared_update_interval: float | None = Field(default=None, gt=0)
    sensors: list[Sensor] = Field(default_factory=list)
    provider_metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def station_id(self) -> str:
        return f"{self.provider}:{self.provider_station_id}"


class Reading(Model):
    provider_sensor_id: str
    observation_time: datetime | None = None
    source_publish_time: datetime | None = None
    provider_timestamp: datetime | None = None
    provider_timestamp_kind: str | None = None
    temperature_c: float | None = None
    relative_humidity: float | None = None
    raw_temperature: str | None = None
    raw_unit: str | None = None
    source_precision: float | None = None
    quality_flags: list[str] = Field(default_factory=list)
    evidence_class: Literal["REALTIME_CAPTURED", "HISTORICAL_EVENT_ONLY"] = "REALTIME_CAPTURED"
    timestamp_provenance: Literal[
        "SENSOR_MEASUREMENT_TIME",
        "PROVIDER_INGEST_TIME",
        "PROVIDER_PUBLICATION_TIME",
        "COLLECTOR_RECEIVE_TIME",
        "UNKNOWN_TIME",
    ] = "UNKNOWN_TIME"
    timestamp_semantics_verified: bool = False

    @field_validator("observation_time", "source_publish_time", "provider_timestamp")
    @classmethod
    def clocks(cls, value: datetime | None) -> datetime | None:
        return utc(value) if value is not None else None


class Capabilities(Model):
    geographic_discovery: bool = False
    latest_observation: bool = False
    historical_observations: bool = False
    temperature: bool = False
    humidity: bool = False
    elevation: bool = False
    sensor_metadata: bool = False


class QCConfig(Model):
    min_temperature_c: float = -95
    max_temperature_c: float = 65
    stale_seconds: float = Field(default=1800, gt=0)
    max_future_seconds: float = Field(default=120, ge=0)
    stuck_seconds: float = Field(default=21600, gt=0)
    jump_c_per_min: float = Field(default=2, gt=0)
    spatial_radius_km: float = Field(default=10, gt=0)
    spatial_threshold_c: float = Field(default=3, gt=0)
    peer_minimum: int = Field(default=3, ge=2)
    min_samples: int = Field(default=100, ge=10)
    min_evaluation_days: int = Field(default=7, ge=1)
    calibration_window: int = Field(default=100, ge=10)
    calibration_minimum: int = Field(default=20, ge=5)
    calibration_method: Literal["median", "mean"] = "median"
    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "predictive": 0.30,
            "temporal": 0.20,
            "freshness": 0.15,
            "spatial": 0.15,
            "geographic": 0.10,
            "metadata": 0.10,
        }
    )

    @model_validator(mode="after")
    def valid_config(self) -> "QCConfig":
        if (
            self.min_temperature_c >= self.max_temperature_c
            or self.calibration_minimum > self.calibration_window
        ):
            raise ValueError("Invalid temperature limits or calibration window")
        names = {"predictive", "temporal", "freshness", "spatial", "geographic", "metadata"}
        if (
            set(self.weights) != names
            or any(not math.isfinite(w) or w < 0 for w in self.weights.values())
            or not math.isclose(sum(self.weights.values()), 1)
        ):
            raise ValueError("Six nonnegative score weights must sum to one")
        return self


class Settings(Model):
    airports: list[Airport]
    radii_km: list[float] = [1, 3, 5, 10, 20]
    providers: list[str] = ["opensensemap", "sensor_community"]
    poll_seconds: float = Field(default=300, ge=300)
    discovery_seconds: float = Field(default=86400, ge=3600)
    qc: QCConfig = Field(default_factory=QCConfig)

    @model_validator(mode="after")
    def valid_settings(self) -> "Settings":
        if not self.airports or len({a.icao for a in self.airports}) != len(self.airports):
            raise ValueError("Unique nonempty airport list required")
        if not self.providers or len(set(self.providers)) != len(self.providers):
            raise ValueError("Unique nonempty provider list required")
        if not self.radii_km or any(
            not math.isfinite(r) or not 0 < r <= 200 for r in self.radii_km
        ):
            raise ValueError("Search radii must be in (0,200] km")
        return self
