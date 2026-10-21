from datetime import UTC, datetime
from decimal import ROUND_FLOOR, Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


def icao_round_temperature(value: Decimal | float | str) -> int:
    """WMO FM15 section15.11: nearest integer, exact ties toward warmer."""
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("Temperature must be finite")
    return int((number + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR))


def encode_metar_temperature(value: Decimal | float | str) -> str:
    number = Decimal(str(value))
    rounded = icao_round_temperature(number)
    if abs(rounded) > 99:
        raise ValueError("Outside two-digit METAR range")
    return ("M" if number.is_signed() else "") + f"{abs(rounded):02d}"


def distance_to_boundary(value: Decimal | float | str) -> Decimal:
    number = Decimal(str(value))
    lower = number.to_integral_value(rounding=ROUND_FLOOR)
    return abs(number - (lower + Decimal("0.5")))


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    station_icao: str
    source: str
    product_type: Literal["METAR", "SPECI", "DWD_10MIN", "KNMI_10MIN", "D_ATIS", "HF_OBS", "OTHER"]
    event_time: datetime
    report_time: datetime | None = None
    source_publish_time: datetime | None = None
    source_receipt_time: datetime | None = None
    collector_request_start_time: datetime | None = None
    collector_request_end_time: datetime | None = None
    collector_receive_time: datetime | None = None
    receive_monotonic_ns: int | None = None
    request_start_monotonic_ns: int | None = None
    run_id: str | None = None
    temperature_c: Decimal | None = None
    dewpoint_c: Decimal | None = None
    temperature_precision: Decimal | None = None
    wind_speed: Decimal | None = None
    wind_direction: str | None = None
    pressure: Decimal | None = None
    raw_text: str
    raw_sha256: str = ""
    auto: bool = False
    cor: bool = False
    evidence_class: Literal["REALTIME_CAPTURED", "HISTORICAL_EVENT_ONLY"] = "REALTIME_CAPTURED"
    startup_censored: bool = True
    coverage_gap: bool = False
    metadata_json: dict[str, Any] = {}

    @field_validator(
        "event_time",
        "report_time",
        "source_publish_time",
        "source_receipt_time",
        "collector_request_start_time",
        "collector_request_end_time",
        "collector_receive_time",
    )
    @classmethod
    def utc_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("Naive timestamps are forbidden")
            return value.astimezone(UTC)
        return value
