"""Strict, documented measurement-time eligibility; no ingestion/publication fallback."""

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

VERSION = "strict-measurement-time-1.0"
MEASUREMENT = "SENSOR_MEASUREMENT_TIME"
INGEST = "PROVIDER_INGEST_TIME"
PUBLICATION = "PROVIDER_PUBLICATION_TIME"
RECEIVE = "COLLECTOR_RECEIVE_TIME"
UNKNOWN = "UNKNOWN_TIME"
OSM_REFERENCE = "https://docs.opensensemap.org/#api-Measurements"
SC_REFERENCE = "https://github.com/opendata-stuttgart/meta/wiki/EN-APIs"


@dataclass(frozen=True)
class TimestampPolicy:
    version: str = VERSION
    maximum_age_seconds: float = 300
    provider_maximum_age_seconds: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            self.version != VERSION
            or not math.isfinite(self.maximum_age_seconds)
            or self.maximum_age_seconds <= 0
        ):
            raise ValueError("Unsupported or invalid timestamp policy")
        if any(not math.isfinite(v) or v <= 0 for v in self.provider_maximum_age_seconds.values()):
            raise ValueError("Invalid provider age threshold")

    def maximum_age(self, provider: str) -> float:
        return self.provider_maximum_age_seconds.get(provider, self.maximum_age_seconds)


@lru_cache(maxsize=1)
def policy() -> TimestampPolicy:
    path = Path("configs/timestamp-policy-v1.json")
    return (
        TimestampPolicy(**json.loads(path.read_text(encoding="utf-8")))
        if path.is_file()
        else TimestampPolicy()
    )


def parse_utc(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("UNKNOWN_TIMEZONE")
    return parsed.astimezone(UTC)


def provenance(row: dict[str, Any]) -> tuple[str, str | None]:
    provider = row.get("provider")
    explicit = row.get("timestamp_provenance")
    # Only the audited provider contract can certify semantics, not an arbitrary field name.
    if provider == "sensor_community":
        return INGEST, SC_REFERENCE
    if (
        provider == "opensensemap"
        and row.get("observation_time")
        and (
            explicit is None
            or (explicit == MEASUREMENT and row.get("timestamp_semantics_verified") is True)
        )
    ):
        return MEASUREMENT, OSM_REFERENCE
    return explicit or UNKNOWN, None


@dataclass(frozen=True)
class Assessment:
    status: str
    reasons: tuple[str, ...]
    measurement_time: datetime | None
    collector_receive_time: datetime | None
    age_at_receipt_seconds: float | None
    timestamp_provenance: str
    semantics_reference: str | None

    @property
    def eligible(self) -> bool:
        return self.status == "VALID"

    def json_data(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("measurement_time", "collector_receive_time"):
            if data[key] is not None:
                data[key] = data[key].isoformat()
        return data


def assess_time(
    row: dict[str, Any],
    at: datetime | None = None,
    *,
    maximum_age: float | None = None,
    minimum_temperature: float = -95,
    maximum_temperature: float = 65,
    settings: TimestampPolicy | None = None,
) -> Assessment:
    active = settings or policy()
    kind, reference = provenance(row)
    reasons = []
    measurement = received = None
    invalid = "INVALID_TIMESTAMP" in row.get("quality_flags", [])
    if invalid:
        reasons.append("ORIGINAL_INVALID_TIMESTAMP")
    try:
        measurement = parse_utc(row.get("observation_time"))
    except (ValueError, TypeError, OverflowError):
        reasons.append("INVALID_MEASUREMENT_TIMESTAMP")
        invalid = True
    try:
        received = parse_utc(row.get("first_receive_time") or row.get("collector_receive_time"))
    except (ValueError, TypeError, OverflowError):
        reasons.append("INVALID_RECEIVE_TIMESTAMP")
        invalid = True
    if measurement is None:
        reasons.append("MISSING_MEASUREMENT_TIME")
    if received is None:
        reasons.append("MISSING_RECEIVE_TIME")
    if kind != MEASUREMENT or reference is None:
        reasons.append("UNKNOWN_TIMESTAMP_PROVENANCE")
    if (
        not row.get("station_id")
        or not row.get("provider")
        or not (row.get("sensor_id") or row.get("provider_sensor_id"))
    ):
        reasons.append("MISSING_IDENTITY")
    try:
        value = float(row["temperature_c"])
        if (
            isinstance(row["temperature_c"], bool)
            or not math.isfinite(value)
            or not minimum_temperature <= value <= maximum_temperature
        ):
            raise ValueError
    except (ValueError, TypeError, KeyError, OverflowError):
        reasons.append("IMPLAUSIBLE_TEMPERATURE")
    if row.get("raw_unit") not in {"C", "degC", "celsius", "°C", "F", "°F", "K"}:
        reasons.append("UNKNOWN_UNIT")
    if row.get("evidence_class") != "REALTIME_CAPTURED":
        reasons.append("NOT_REALTIME_CAPTURED")
    age = (received - measurement).total_seconds() if received and measurement else None
    if age is not None and age < 0:
        reasons.append("FUTURE_MEASUREMENT_AT_RECEIPT")
        invalid = True
    limit = active.maximum_age(str(row.get("provider", "")))
    if maximum_age is not None:
        if not math.isfinite(maximum_age) or maximum_age <= 0:
            raise ValueError("Invalid maximum age")
        limit = min(limit, maximum_age)
    if age is not None and age > limit:
        reasons.append("STALE_AT_RECEIPT")
    decision = parse_utc(at) if at is not None else received
    if decision and received and received > decision:
        reasons.append("NOT_RECEIVED_AT_DECISION")
    if decision and measurement:
        if measurement > decision:
            reasons.append("FUTURE_MEASUREMENT_AT_DECISION")
            invalid = True
        elif (decision - measurement).total_seconds() > limit:
            reasons.append("STALE_AT_DECISION")
    blocking = {
        "CONFLICTING_DUPLICATE",
        "INDOOR_SENSOR",
        "MOBILE_SENSOR",
        "STUCK_SENSOR",
        "INVALID_TEMPERATURE",
        "IMPOSSIBLE_TEMPERATURE",
    }
    reasons.extend(sorted(blocking.intersection(row.get("quality_flags", []))))
    if row.get("exposure") == "indoor":
        reasons.append("INDOOR_SENSOR")
    if row.get("mobile") is True:
        reasons.append("MOBILE_SENSOR")
    status = (
        "INVALID_TIMESTAMP"
        if invalid
        else "UNKNOWN_TIMESTAMP_PROVENANCE"
        if "UNKNOWN_TIMESTAMP_PROVENANCE" in reasons or measurement is None
        else "STALE"
        if any(r.startswith("STALE") for r in reasons)
        else "QUARANTINED"
        if reasons
        else "VALID"
    )
    return Assessment(
        status, tuple(sorted(set(reasons))), measurement, received, age, kind, reference
    )
