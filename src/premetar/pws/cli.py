import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from premetar.model import utc_now
from premetar.pws.analysis import predict
from premetar.pws.geometry import bounding_boxes
from premetar.pws.providers import PROVIDERS
from premetar.pws.repository import inventory
from premetar.pws.service import (
    collect,
    discover,
    quality_snapshot,
    session,
    settings,
    write_reports,
)

app = typer.Typer(no_args_is_help=True, help="Open PWS discovery and research QC; no trading.")
console = Console()
DB = Path("data/premetar.sqlite3")
RAW = Path("data/raw")


@app.command()
def sources() -> None:
    for name, provider in PROVIDERS.items():
        console.print(f"{name}: {provider.status} | {provider.capabilities.model_dump()}")
    console.print("CWOP: investigated roadmap only. Netatmo disabled pending runtime verification.")


async def execute(
    operation: str,
    airport: str,
    all_airports: bool,
    database: Path,
    raw_path: Path,
    config_path: Path | None,
    **kwargs: Any,
) -> Any:
    config = settings(config_path)
    airports = {a.icao for a in config.airports} if all_airports else {airport.upper()}
    if not airports.issubset({a.icao for a in config.airports}):
        raise ValueError("Unknown airport")
    unknown = set(config.providers) - set(PROVIDERS)
    if unknown:
        raise ValueError("Unknown configured provider")
    async with session(database, raw_path, config, operation) as (store, providers):
        if operation == "discover":
            radius = kwargs["radius"]
            bounding_boxes(0, 0, radius)
            return await discover(store, providers, config, airports, radius)
        if operation == "collect":
            return await collect(store, providers, config, airports, kwargs["duration"])
        if operation == "stations":
            return [
                r
                for a in sorted(airports)
                for r in await store._call(inventory, store.connection, a)
            ]
        if operation == "predict":

            def save_prediction() -> dict[str, Any]:
                with store.connection:
                    return predict(
                        store.connection,
                        airport.upper(),
                        kwargs["target"],
                        config.qc,
                        kwargs["method"],
                        run_id=store.run_id,
                    )

            return await store._call(save_prediction)
        if operation == "report":
            return await store._call(write_reports, store, airports, config, kwargs["output"])
        if operation == "select":

            def selection() -> list[dict[str, Any]]:
                now = utc_now()
                candidates = quality_snapshot(store, airport.upper(), config, now)
                manual = kwargs.get("station_id")
                top = kwargs.get("top", 10)
                if manual and manual not in {r["station_id"] for r in candidates}:
                    raise ValueError("Station not discovered for airport")
                chosen = (
                    [r for r in candidates if r["station_id"] == manual]
                    if manual
                    else [r for r in candidates if r["status"] == "CANDIDATE"][:top]
                )
                with store.connection:
                    for row in chosen:
                        store.connection.execute(
                            "INSERT INTO pws_selections VALUES(NULL,?,?,?,?,?)",
                            (
                                row["station_id"],
                                airport.upper(),
                                now.isoformat(),
                                not kwargs.get("exclude", False),
                                kwargs.get("reason")
                                or "Automatic candidate selection using prior OOS quality snapshot",
                            ),
                        )
                return chosen

            return await store._call(selection)
        return [
            r
            for a in sorted(airports)
            for r in await store._call(quality_snapshot, store, a, config, utc_now())
        ]


def run(
    operation: str,
    airport: str,
    all_airports: bool,
    database: Path,
    raw_path: Path,
    config: Path | None,
    **kwargs: Any,
) -> None:
    try:
        result = asyncio.run(
            execute(operation, airport, all_airports, database, raw_path, config, **kwargs)
        )
    except FileExistsError:
        raise typer.BadParameter(
            "Database lock exists; confirm owner has stopped before removing it"
        ) from None
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None
    except KeyboardInterrupt:
        return
    if operation == "report":
        console.print(f"{result['conclusion']} | station associations: {result['station_counts']}")
        console.print(str(kwargs["output"].resolve()))
    elif operation == "stations":
        table = Table("Station", "Provider", "Distance km", "Last observation")
        for row in result:
            table.add_row(
                row["station_id"],
                row["provider"],
                f"{row['distance_km']:.2f}",
                row["last_observation_time"] or "unknown",
            )
        console.print(table)
    elif operation in ("rank", "qc", "analyze"):
        table = Table("Station", "Provider", "Distance km", "Age s", "Score", "Status")
        for row in result:
            table.add_row(
                row["station_id"],
                row["provider"],
                f"{row['distance_km']:.2f}",
                str(row["observation_age_seconds"]),
                str(row["score"]),
                row["status"],
            )
        console.print(table)
    else:
        typer.echo(json.dumps(result, indent=2, default=str))


@app.command(name="discover")
def discover_command(
    airport: str = "EDDM",
    all_airports: bool = False,
    radius: Annotated[float, typer.Option(min=0.01, max=200)] = 20,
    database: Path = DB,
    raw_path: Path = RAW,
    config: Path | None = None,
) -> None:
    """Discover stations once. No observations or station selection is implied."""
    run("discover", airport, all_airports, database, raw_path, config, radius=radius)


@app.command(name="collect")
def collect_command(
    airport: str = "EDDM",
    all_airports: bool = False,
    duration: Annotated[float, typer.Option(min=1, max=86400)] = 300,
    database: Path = DB,
    raw_path: Path = RAW,
    config: Path | None = None,
) -> None:
    """Bounded collection of selected stations; conservative polling, no bursts."""
    run("collect", airport, all_airports, database, raw_path, config, duration=duration)


@app.command(name="stations")
def stations_command(
    airport: str = "EDDM",
    all_airports: bool = False,
    database: Path = DB,
    raw_path: Path = RAW,
    config: Path | None = None,
) -> None:
    run("stations", airport, all_airports, database, raw_path, config)


def quality_command(
    airport: str = "EDDM",
    all_airports: bool = False,
    database: Path = DB,
    raw_path: Path = RAW,
    config: Path | None = None,
) -> None:
    run("rank", airport, all_airports, database, raw_path, config)


for command in ("qc", "rank", "analyze"):
    app.command(name=command)(quality_command)


@app.command(name="select")
def select_command(
    airport: str = "EDDM",
    top: Annotated[int, typer.Option(min=1, max=100)] = 10,
    station_id: str | None = None,
    exclude: bool = False,
    reason: str | None = None,
    database: Path = DB,
    raw_path: Path = RAW,
    config: Path | None = None,
) -> None:
    """Auto-select candidates, or manually include/exclude one discovered station."""
    if exclude and not station_id:
        raise typer.BadParameter("--exclude requires --station-id")
    if station_id and not reason:
        raise typer.BadParameter("Manual selection/exclusion requires --reason")
    run(
        "select",
        airport,
        False,
        database,
        raw_path,
        config,
        top=top,
        station_id=station_id,
        exclude=exclude,
        reason=reason,
    )


@app.command(name="predict")
def predict_command(
    target: Annotated[datetime, typer.Argument(formats=["%Y-%m-%dT%H:%M:%S%z"])],
    airport: str = "EDDM",
    method: str = "equal_weights",
    database: Path = DB,
    raw_path: Path = RAW,
    config: Path | None = None,
) -> None:
    """Persist a prediction now for an explicitly supplied future UTC target."""
    run("predict", airport, False, database, raw_path, config, target=target, method=method)


@app.command(name="report")
def report_command(
    airport: str = "EDDM",
    all_airports: bool = False,
    output: Path = Path("reports/pws"),
    database: Path = DB,
    raw_path: Path = RAW,
    config: Path | None = None,
) -> None:
    run("report", airport, all_airports, database, raw_path, config, output=output)


@app.command(name="today")
def today_command(
    airport: str = "EPWA",
    date: str | None = None,
    limit: Annotated[int, typer.Option(min=1, max=10000)] = 50,
    bucket_minutes: int = 5,
    database: Path = Path("data/continuous-v1.sqlite3"),
    output: Path = Path("reports/daily"),
) -> None:
    """Read-only local-day measurements, timestamp quarantine and METAR comparison."""
    from contextlib import closing
    from datetime import date as CalendarDate

    from premetar.continuous.reporting import connect
    from premetar.pws.daily import make_report

    try:
        day = CalendarDate.fromisoformat(date) if date else None
        with closing(connect(database)) as conn:
            conn.execute("BEGIN")
            result = make_report(conn, airport, day, output, bucket_minutes)
            conn.rollback()
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None
    console.print(
        f"{result['airport']} {result['date']} [{result['timezone']}] - {result['total_valid_observations']} valid observations, {result['usable_stations']} usable stations"
    )
    table = Table(
        "Sensor",
        "Provider",
        "Distance km",
        "Last valid measurement",
        "Last received",
        "Age at receipt s",
        "QC",
        "Eligible now",
    )
    for r in result["stations"]:
        table.add_row(
            r["sensor_id"],
            r["provider"],
            f"{r['distance_km']:.2f}",
            r["last_valid_measurement_local"] or "UNKNOWN",
            r["last_received_local"] or "UNKNOWN",
            str(r["observation_age_at_last_receipt"]),
            r["qc_status"],
            str(r["eligible_now"]),
        )
    console.print(table)
    timeline = Table("Measurement local", "Received local", "Sensor", "Celsius", "Age s", "QC")
    for r in result["observations"][-limit:]:
        timeline.add_row(
            r["measurement_time_local"],
            r["received_time_local"],
            r["sensor_id"],
            str(r["temperature_c"]),
            f"{r['observation_age_seconds']:.3f}",
            r["qc"],
        )
    console.print(timeline)
    buckets = Table(
        "Bucket local",
        "Provider stations",
        "Conservative groups",
        "Median C",
        "Min C",
        "Max C",
        "MAD C",
    )
    for r in result["buckets"][-12:]:
        buckets.add_row(
            r["start_local"],
            str(r["provider_stations"]),
            str(r["conservative_spatial_groups"]),
            f"{r['median_c']:.2f}",
            f"{r['min_c']:.2f}",
            f"{r['max_c']:.2f}",
            f"{r['median_absolute_deviation_c']:.2f}",
        )
    console.print(buckets)
    console.print(
        "Physical independence UNVERIFIED; no forward-fill; one vote per station/200m group."
    )
    if not result["observations"]:
        console.print("INSUFFICIENT DATA: no timestamp-verified observations for this local day")
    console.print(
        f"Immutable predictions: {result['valid_predictions']} eligible, {result['excluded_predictions']} excluded; {result['matched_outcomes']} valid matched outcomes across {result['distinct_metar_cycles']} actual METAR cycles."
    )
    console.print(str((output / f"{result['airport']}_{result['date']}.md").resolve()))


@app.command(name="timestamp-audit")
def timestamp_audit_command(
    database: Path = Path("data/continuous-v1.sqlite3"), output: Path = Path("reports/integrity")
) -> None:
    """Read-only audit; never mutates raw observations or prediction history."""
    from contextlib import closing

    from premetar.continuous.reporting import connect
    from premetar.pws.integrity_report import timestamp_audit

    with closing(connect(database)) as conn:
        conn.execute("BEGIN")
        result = timestamp_audit(conn, output)
        conn.rollback()
    console.print_json(json.dumps(result))
