import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from premetar.analysis import analyze as generate_report
from premetar.collector import collect as run_collector
from premetar.continuous.cli import app as continuous_app
from premetar.continuous.cli import predictions as predictions_app
from premetar.continuous.cli import service as service_app
from premetar.model import utc_now
from premetar.pws.cli import app as pws_app
from premetar.sources import OPTIONAL_SOURCES, STATIONS, configured_sources

app = typer.Typer(no_args_is_help=True, help="Prospective pre-METAR research; no trading.")
console = Console()
app.add_typer(pws_app, name="pws")

app.add_typer(continuous_app, name="continuous")
app.add_typer(service_app, name="service")
app.add_typer(predictions_app, name="predictions")
DEFAULT_DB = Path("data/premetar.sqlite3")


def comma_set(value: str) -> set[str]:
    result = {item.strip() for item in value.split(",") if item.strip()}
    if not result:
        raise ValueError("Empty selection")
    return result


@app.command()
def collect(
    stations: str = "EDDM,EHAM",
    sources: str = "awc,dwd_10min,knmi_metar",
    poll_interval: Annotated[float, typer.Option(min=60)] = 60,
    database: Path = DEFAULT_DB,
    raw_path: Path = Path("data/raw"),
    duration: Annotated[
        float | None, typer.Option(min=1, help="Optional bounded smoke-test duration in seconds")
    ] = None,
    live: bool = True,
    pws: bool = False,
    pws_config: Path | None = None,
    pws_airports: str = "EDDM,EHAM,EPWA,EGLL",
) -> None:
    """Run isolated public collectors until Ctrl+C (or --duration)."""
    try:
        selected = {s.upper() for s in comma_set(stations)}
        adapters = configured_sources(selected, comma_set(sources), poll_interval)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    try:
        from premetar.pws.service import settings as load_pws_settings

        pws_settings = load_pws_settings(pws_config) if pws else None
        if pws and (duration is None or duration > 86400):
            raise typer.BadParameter("--pws requires --duration between 1 and 86400 seconds")
        if pws_settings and not comma_set(pws_airports).issubset(
            {a.icao for a in pws_settings.airports}
        ):
            raise typer.BadParameter("Unknown PWS airport")
        asyncio.run(
            run_collector(
                adapters,
                selected,
                database,
                raw_path,
                duration,
                live,
                pws_settings=pws_settings,
                pws_airports=comma_set(pws_airports) if pws else None,
            )
        )
    except FileExistsError:
        console.print(
            "Collector lock exists. Confirm its process has stopped before removing the lock.",
            style="red",
        )
        raise typer.Exit(1) from None
    except KeyboardInterrupt:
        pass


@app.command()
def analyze(database: Path = DEFAULT_DB, output: Path = Path("reports")) -> None:
    """Write reproducible Markdown, JSON, CSV and Parquet from captured observations."""
    if not database.is_file():
        raise typer.BadParameter("Database does not exist; run collect first")
    result = generate_report(database, output)
    console.print(
        f"{result['conclusion']} | observations={result['observations']} paired_rows={result['paired_rows']}"
    )
    console.print(str((output / "latest.md").resolve()))


@app.command(name="sources")
def show_sources() -> None:
    """Configured endpoints, intervals and disabled optional adapters."""
    for source in configured_sources(set(STATIONS), {"awc", "dwd_10min", "knmi_metar"}, 60):
        console.print(f"{source.name}: enabled | >= {source.interval_sec:g}s | {source.url}")
    for name, reason in OPTIONAL_SOURCES.items():
        console.print(f"{name}: {reason}")


@app.command(name="stations")
def show_stations() -> None:
    """Expected routine schedules (UTC), not publication guarantees."""
    for station in STATIONS.values():
        console.print(
            f"{station.icao}: UTC minutes {station.routine_minutes}; {station.timezone}; national={station.national_id}; WMO={station.wmo_id}"
        )
    console.print("EPWA, EGLL: roadmap only")


@app.command()
def status(database: Path = DEFAULT_DB, as_json: bool = False) -> None:
    """Counts, collector heartbeat, data/transport freshness and recent errors."""
    if not database.is_file():
        raise typer.BadParameter("Database does not exist")
    with sqlite3.connect(f"file:{database.resolve().as_posix()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        runs = [
            dict(row)
            for row in connection.execute(
                "SELECT id,started_at,ended_at,heartbeat,exit_reason FROM runs ORDER BY started_at DESC LIMIT 3"
            )
        ]
        counts = {
            table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in (
                "raw_payloads",
                "observations",
                "canonical_reports",
                "report_receipts",
                "errors",
            )
        }
        health = (
            [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM source_health WHERE run_id=?", (runs[0]["id"],)
                )
            ]
            if runs
            else []
        )
        errors = [
            dict(row)
            for row in connection.execute(
                "SELECT source,at,error_class,raw_id FROM errors ORDER BY id DESC LIMIT 10"
            )
        ]
    now = utc_now()
    for row in health:
        row["transport_stale"] = (
            row["last_success"] is None
            or (now - datetime.fromisoformat(row["last_success"])).total_seconds()
            > row["interval_sec"] * 2.5
        )
        row["event_age_sec"] = (
            None
            if row["last_event"] is None
            else (now - datetime.fromisoformat(row["last_event"])).total_seconds()
        )
        row["data_stale"] = row["event_age_sec"] is None or row["event_age_sec"] > (
            3600 if row["source"] == "dwd_10min" else 5400
        )
    uptime = None
    if runs:
        start = datetime.fromisoformat(runs[0]["started_at"])
        end = datetime.fromisoformat(runs[0]["ended_at"]) if runs[0]["ended_at"] else now
        uptime = (end - start).total_seconds()
        runs[0]["heartbeat_stale"] = (
            now - datetime.fromisoformat(runs[0]["heartbeat"])
        ).total_seconds() > 10
    size = sum(
        path.stat().st_size
        for path in (database, Path(str(database) + "-wal"), Path(str(database) + "-shm"))
        if path.exists()
    )
    result = {
        "database": str(database.resolve()),
        "database_bytes_including_wal": size,
        "uptime_sec": uptime,
        "counts": counts,
        "runs": runs,
        "sources": health,
        "last_errors": errors,
    }
    if as_json:
        typer.echo(json.dumps(result, indent=2))
        return
    console.print(f"PRE-METAR STATUS | uptime {uptime}s | DB+WAL {size:,} bytes")
    console.print(counts)
    table = Table(
        "Source", "Last event UTC", "Last receive UTC", "Transport / data stale", "Last error"
    )
    for row in health:
        table.add_row(
            row["source"],
            row["last_event"] or "--",
            row["last_success"] or "--",
            f"{row['transport_stale']} / {row['data_stale']}",
            row["last_error"] or "--",
        )
    console.print(table)
    if errors:
        console.print(errors)


if __name__ == "__main__":
    app()
