"""Independent, research-only public wallet monitoring commands."""

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from premetar.research.trader_analytics import analyze_evidence
from premetar.research.trader_reports import generate_reports
from premetar.research.trader_store import read_events, read_status

app = typer.Typer(no_args_is_help=True, help="Public-wallet shadow research; no real orders.")
console = Console()
DEFAULT_DB = Path("data/trader/monitor.sqlite3")
PROJECT_ROOT = Path(__file__).resolve().parents[3]


@app.command()
def start(
    database: Path = DEFAULT_DB,
    weather_database: Path | None = None,
    duration: Annotated[float | None, typer.Option(min=1)] = None,
    poll_interval: Annotated[float, typer.Option(min=2)] = 3.0,
) -> None:
    """Start separate monitor until Ctrl+C or optional bounded duration."""
    from premetar.research.trader_monitor import run_monitor
    from premetar.research.trader_service import configured_weather_database

    try:
        asyncio.run(
            run_monitor(
                database,
                weather_database or configured_weather_database(PROJECT_ROOT),
                duration,
                poll_interval,
            )
        )
    except KeyboardInterrupt:
        pass


@app.command()
def status(database: Path = DEFAULT_DB) -> None:
    """Read last recorded heartbeat; stale heartbeat is not proof of a live process."""
    console.print_json(json.dumps(read_status(database), default=str))


@app.command()
def recent(
    database: Path = DEFAULT_DB,
    limit: Annotated[int, typer.Option(min=1, max=10000)] = 20,
) -> None:
    """Inspect first-receipt trade records."""
    console.print_json(json.dumps(read_events(database, "TRADE", limit), default=str))


@app.command()
def shadow(
    database: Path = DEFAULT_DB,
    limit: Annotated[int, typer.Option(min=1, max=10000)] = 20,
) -> None:
    """Inspect immutable simulated attempts, including unexecutable cases."""
    console.print_json(json.dumps(read_events(database, "SHADOW", limit), default=str))


@app.command()
def analyze(database: Path = DEFAULT_DB, output: Path = Path("reports/trader")) -> None:
    """Generate Markdown/CSV from independent research evidence."""
    result = generate_reports(database, output)
    result["analysis"] = analyze_evidence(database, output)
    console.print_json(json.dumps(result, default=str))


@app.command(name="service-install")
def service_install(preview: bool = True) -> None:
    """Preview separate least-privilege logon task; --no-preview registers it."""
    from premetar.research.trader_service import service

    console.print_json(json.dumps(service("install", PROJECT_ROOT, preview), default=str))


@app.command(name="service-status")
def service_status() -> None:
    """Read only the independent research task configuration."""
    from premetar.research.trader_service import service

    console.print_json(json.dumps(service("status", PROJECT_ROOT, False), default=str))


@app.command(name="service-remove")
def service_remove(preview: bool = True) -> None:
    """Remove only verified research registration; does not terminate the monitor."""
    from premetar.research.trader_service import service

    console.print_json(json.dumps(service("remove", PROJECT_ROOT, preview), default=str))


@app.command()
def stop(database: Path = DEFAULT_DB) -> None:
    """Request graceful shutdown of this research monitor only."""
    database.with_suffix(".trader.stop").write_text("EXP0011_STOP_REQUEST", encoding="utf-8")
    console.print("Research monitor stop requested; weather collector is unaffected.")
