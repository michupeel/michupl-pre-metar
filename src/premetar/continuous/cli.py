"""Continuous operation and safe project-scoped Windows service commands."""

import asyncio
import json
import logging
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import typer
from rich.console import Console

from premetar.collector import collect
from premetar.continuous import windows
from premetar.continuous.config import load
from premetar.continuous.data import settle
from premetar.continuous.reporting import connect, report, snapshot
from premetar.pws.repository import rows
from premetar.sources import configured_sources

app = typer.Typer(no_args_is_help=True)
service = typer.Typer(no_args_is_help=True)
predictions = typer.Typer(no_args_is_help=True)
DEFAULT = Path("configs/experiments/continuous-v1.json")
console = Console()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            dict(
                at=datetime.fromtimestamp(record.created, UTC).isoformat(),
                level=record.levelname,
                logger=record.name,
                event=record.getMessage(),
            ),
            ensure_ascii=True,
        )


@app.command()
def start(config: Path = DEFAULT, duration: float | None = typer.Option(None, min=1)) -> None:
    """Collect until stopped; --duration bounds a genuine operational smoke test."""
    cfg = load(config)
    cfg.log_path.mkdir(parents=True, exist_ok=True)
    for filename, level in (("collector.log", logging.INFO), ("errors.log", logging.WARNING)):
        handler = RotatingFileHandler(
            cfg.log_path / filename, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        handler.setLevel(level)
        handler.setFormatter(JsonFormatter())
        logging.getLogger("premetar").addHandler(handler)
    logging.getLogger("premetar").setLevel(logging.INFO)
    sources = configured_sources(set(cfg.airports), {"awc", "dwd_10min", "knmi_metar"}, 60)
    # Small documented history window catches delayed/out-of-order routine/SPECI/COR.
    # First startup snapshot remains censored; history never supplies publication clocks.
    sources = [replace(s, url=s.url + "&hours=2") if s.name == "awc" else s for s in sources]
    logging.getLogger("premetar").info("continuous_start experiment=%s", cfg.experiment)
    try:
        asyncio.run(
            collect(
                sources,
                set(cfg.airports),
                cfg.database_path,
                cfg.raw_storage_path,
                duration,
                False,
                continuous_config=cfg,
            )
        )
    except BaseException as exc:
        logging.getLogger("premetar").error("continuous_failure error_class=%s", type(exc).__name__)
        raise
    finally:
        logging.getLogger("premetar").info("continuous_shutdown")


@app.command()
def status(config: Path = DEFAULT) -> None:
    """Read persistent heartbeat, coverage and errors without a collector dependency."""
    cfg = load(config)
    with connect(cfg.database_path) as conn:
        console.print_json(json.dumps(snapshot(conn), default=str))


@app.command()
def stations(config: Path = DEFAULT) -> None:
    cfg = load(config)
    with connect(cfg.database_path) as conn:
        console.print_json(
            json.dumps(rows(conn, "SELECT * FROM continuous_cohort ORDER BY airport,station_id"))
        )


@app.command()
def stop(config: Path = DEFAULT) -> None:
    """Request graceful shutdown; pending HTTP/raw writes finish before exit."""
    cfg = load(config)
    cfg.stop_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.stop_path.write_text("operator_requested", encoding="utf-8")
    console.print("Graceful stop requested")


@app.command(name="report")
def generate(config: Path = DEFAULT, output: Path = Path("reports/continuous")) -> None:
    cfg = load(config)
    with connect(cfg.database_path) as conn:
        report(conn, output)
    console.print(str(output.resolve()))


@predictions.command(name="list")
def list_predictions(
    config: Path = DEFAULT, limit: int = typer.Option(20, min=1, max=1000)
) -> None:
    with connect(load(config).database_path) as conn:
        console.print_json(
            json.dumps(
                rows(
                    conn, "SELECT * FROM pws_predictions ORDER BY created_at DESC LIMIT ?", (limit,)
                )
            )
        )


@predictions.command(name="settle")
def settle_predictions(config: Path = DEFAULT) -> None:
    # Writer uses same advisory collector lock; never contend with an active collector.
    cfg = load(config)
    if cfg.database_path.with_suffix(cfg.database_path.suffix + ".lock").exists():
        raise typer.BadParameter(
            "Collector performs automatic settlement; stop it before manual settlement"
        )
    with sqlite3.connect(cfg.database_path, timeout=5) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        console.print(f"New settlements: {settle(conn)}")


@service.command(name="install")
def install(config: Path = DEFAULT, dry_run: bool = True) -> None:
    """Preview by default; --no-dry-run registers the verified project-only logon task."""
    load(config)
    console.print(windows.install(Path.cwd(), config, True), markup=False)
    if not dry_run:
        console.print(windows.install(Path.cwd(), config, False), markup=False)


@service.command(name="status")
def task_status() -> None:
    console.print(windows.query() or "NOT INSTALLED", markup=False)


@service.command(name="remove")
def remove(config: Path = DEFAULT) -> None:
    windows.remove(Path.cwd(), config)
    console.print("Project logon task removed (collector stop is separate)")


@app.command(name="clock-audit")
def clock_audit_command(output: Path = Path("reports/integrity")) -> None:
    """Read Windows time settings and compare two trusted NTP servers; no configuration changes."""
    from premetar.clock_audit import run_audit

    result = run_audit(output)
    # Native localized command output may contain characters unavailable in cp1250.
    # Full evidence stays in UTF-8 files; the terminal receives a portable summary.
    console.print_json(json.dumps({k: v for k, v in result.items() if k != "evidence"}))
