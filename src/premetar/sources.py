from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from premetar.model import Observation
from premetar.parsers import parse_awc, parse_dwd, parse_knmi_metar


@dataclass(frozen=True)
class Station:
    icao: str
    timezone: str
    routine_minutes: tuple[int, ...]
    national_id: str
    wmo_id: str


STATIONS = {
    "EDDM": Station("EDDM", "Europe/Berlin", (20, 50), "01262", "10870"),
    "EHAM": Station("EHAM", "Europe/Amsterdam", (25, 55), "240", "06240"),
    "EPWA": Station("EPWA", "Europe/Warsaw", (0, 30), "", "12375"),
    "EGLL": Station("EGLL", "Europe/London", (20, 50), "", "03772"),
}


def next_report(station: Station, now: datetime) -> datetime:
    hour = now.replace(minute=0, second=0, microsecond=0)
    return min(
        hour + timedelta(hours=h, minutes=m)
        for h in (0, 1)
        for m in station.routine_minutes
        if hour + timedelta(hours=h, minutes=m) > now
    )


@dataclass(frozen=True)
class HttpSource:
    name: str
    url: str
    stations: frozenset[str]
    parser: Callable[[bytes, datetime], list[Observation]]
    interval_sec: float = 60


OPTIONAL_SOURCES = {
    "knmi_10min": "Disabled: KNMI_API_KEY required; NetCDF and notification integration deferred, no data claimed",
    "metar_ws": "Disabled: separate explicitly configured key required; REST/WS adapter is Milestone 2",
    "d_atis": "Disabled: documented authorized provider and appropriate plan required; Milestone 3",
}


class AtisSource(Protocol):
    """Future adapters must retain letter, issue time, raw text and all receipt clocks."""

    async def receive(self) -> tuple[bytes, datetime]: ...


class MetarWsAtisSource(AtisSource, Protocol):
    """Interface only: no access or implementation is asserted in Milestone 1."""


def configured_sources(stations: set[str], names: set[str], interval: float) -> list[HttpSource]:
    unknown = stations - STATIONS.keys()
    if unknown:
        raise ValueError("Unknown configured airport")
    available = {"awc", "dwd_10min", "knmi_metar"}
    if names - available:
        raise ValueError("Requested source disabled or unknown; run premetar sources")
    # Conservative baseline floors. No automatic burst; no blanket claim that limit==permission.
    if interval < 60:
        raise ValueError("Milestone 1 polling floor is 60 seconds")
    result = []
    if "awc" in names:
        result.append(
            HttpSource(
                "awc",
                "https://aviationweather.gov/api/data/metar?ids="
                + ",".join(sorted(stations))
                + "&format=json",
                frozenset(stations),
                parse_awc,
                interval,
            )
        )
    if "dwd_10min" in names and "EDDM" in stations:
        result.append(
            HttpSource(
                "dwd_10min",
                "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes/air_temperature/now/10minutenwerte_TU_01262_now.zip",
                frozenset({"EDDM"}),
                parse_dwd,
                interval,
            )
        )
    if "knmi_metar" in names and "EHAM" in stations:
        result.append(
            HttpSource(
                "knmi_metar",
                "https://d2whtzszevhgqk.cloudfront.net/metar-EHAM-latest.xml",
                frozenset({"EHAM"}),
                parse_knmi_metar,
                interval,
            )
        )
    if not result:
        raise ValueError("No sources apply to selected stations")
    return result
