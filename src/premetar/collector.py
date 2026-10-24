import asyncio
import hashlib
import json
import logging
import platform
import random
import signal
import ssl
import subprocess
import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import httpx
import truststore
from rich.console import Console
from rich.live import Live
from rich.table import Table

from premetar import __version__
from premetar.continuous.reference_gate import ReferenceGate
from premetar.model import Observation, utc_now
from premetar.sources import STATIONS, HttpSource, next_report
from premetar.store import Store

if TYPE_CHECKING:
    from premetar.continuous.config import Config
    from premetar.pws.models import Settings

LOG = logging.getLogger("premetar")


def clock_status() -> dict[str, Any]:
    result: dict[str, Any] = {
        "system_time": utc_now().isoformat(),
        "local_timezone": str(datetime.now().astimezone().tzinfo),
        "platform": platform.platform(),
        "monotonic_clock": "perf_counter_ns",
        "monotonic_resolution_sec": time.get_clock_info("perf_counter").resolution,
        "synchronization_confirmed": False,
        "offset_sec": None,
    }
    if platform.system() == "Windows":
        try:
            response = subprocess.run(
                ["w32tm", "/query", "/status"], capture_output=True, timeout=5, check=False
            )
            # Keep OS diagnostic as evidence; do not infer an offset from dispersion or stale sync.
            result["ntp_query_exit_code"] = response.returncode
            result["ntp_status"] = response.stdout.decode(errors="replace")[:6000]
        except (OSError, subprocess.TimeoutExpired) as exc:
            result["ntp_query_error"] = type(exc).__name__
    result["warning"] = (
        "Absolute clock offset not independently verified; use within-run monotonic latency"
    )
    from premetar.clock_audit import cached_clock

    evidence = cached_clock()
    result["verification_status"] = evidence["verification_status"]
    result["clock_audit"] = evidence
    result["offset_sec"] = evidence.get("measured_offset_seconds")
    if result["offset_sec"] is not None:
        result["warning"] = (
            f"Approximate NTP offset {result['offset_sec']:+.3f}s; clock verification {evidence['verification_status']}. Automatic synchronization remains unverified."
        )
    return result


def retry_after(value: str | None, now: datetime) -> float:
    if not value:
        return 0
    try:
        return max(0, float(value))
    except ValueError:
        try:
            return max(0, (parsedate_to_datetime(value) - now).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 0


async def wait_or_stop(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass


async def poll_source(
    source: HttpSource,
    store: Store,
    client: httpx.AsyncClient,
    stop: asyncio.Event,
    state: dict[str, Any],
    reference_gate: ReferenceGate | None = None,
) -> None:
    initialized, failures, last_success = False, 0, None
    while not stop.is_set():
        packet: dict[str, Any] | None = None
        raw_id = None
        delay = source.interval_sec
        try:
            start_wall, start_mono = utc_now(), time.perf_counter_ns()
            response = await client.get(source.url)
            # httpx.get has buffered the complete payload before returning.
            end_mono, end_wall = time.perf_counter_ns(), utc_now()
            if reference_gate and source.name in {"awc", "knmi_metar"}:
                reference_gate.begin(source.name, set(source.stations), end_wall)
            packet = await store.capture(
                {
                    "source": source.name,
                    "request_url": source.url,
                    "http_status": response.status_code,
                    "headers": dict(response.headers),
                    "request_start": start_wall.isoformat(),
                    "request_end": end_wall.isoformat(),
                    "received_at": end_wall.isoformat(),
                    "request_start_monotonic_ns": start_mono,
                    "monotonic_ns": end_mono,
                },
                response.content,
            )
            raw_id = packet["id"]
            if response.status_code in (401, 403) or 300 <= response.status_code < 400:
                await store.error(
                    source.name, f"HTTP_{response.status_code}_adapter_disabled", raw_id
                )
                state[source.name] = {"error": f"HTTP_{response.status_code}; adapter disabled"}
                return
            if response.status_code == 429:
                delay = max(
                    source.interval_sec * 2,
                    retry_after(response.headers.get("Retry-After"), end_wall),
                )
                raise RuntimeError("RateLimited")
            if response.status_code not in (200, 204):
                raise RuntimeError(f"HTTP_{response.status_code}")
            gap = (
                last_success is not None
                and (end_mono - last_success) / 1e9 > source.interval_sec * 2.5
            )
            observations = await store.parse_and_save(
                packet,
                response.content if response.status_code != 204 else b"[]",
                source.parser,
                set(source.stations),
                not initialized,
                gap,
            )
            initialized, failures, last_success = True, 0, end_mono
            latest = max(observations, key=lambda o: o.event_time, default=None)
            state[source.name] = {
                "latest": latest,
                "by_station": {
                    icao: max(
                        (o for o in observations if o.station_icao == icao),
                        key=lambda o: o.event_time,
                        default=None,
                    )
                    for icao in source.stations
                },
                "receive": end_wall,
                "rows": len(observations),
                "error": None,
            }
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failures += 1
            # Never include exception text, request objects, auth headers or URLs in logs.
            name = type(exc).__name__
            if type(exc) is RuntimeError and str(exc) in (
                "RateLimited",
                "HTTP_500",
                "HTTP_502",
                "HTTP_503",
                "HTTP_504",
            ):
                name = str(exc)
            await store.error(source.name, name, raw_id)
            state[source.name] = {"error": name, "failures": failures}
            LOG.warning(
                json.dumps({"source": source.name, "error_class": name, "failures": failures})
            )
            delay = max(
                delay, min(3600, source.interval_sec * 2 ** min(failures, 6)) + random.uniform(0, 5)
            )
        finally:
            if reference_gate:
                reference_gate.end(source.name)
        await wait_or_stop(stop, delay)


def live_table(stations: set[str], state: dict[str, Any]) -> Table:
    now = utc_now()
    table = Table(title="PRE-METAR LIVE | " + now.strftime("%Y-%m-%d %H:%M:%SZ"))
    for column in ("STATION / NEXT", "SOURCE", "EVENT UTC", "RECEIVED UTC", "TEMP C / STATE"):
        table.add_column(column)
    for icao in sorted(stations):
        nxt = next_report(STATIONS[icao], now)
        table.add_row(f"{icao} {nxt:%H:%M}Z T-{int((nxt - now).total_seconds())}s", "", "", "", "")
        for source, data in state.items():
            obs: Observation | None = data.get("by_station", {}).get(icao)
            if obs is not None and obs.station_icao == icao:
                table.add_row(
                    "",
                    source,
                    obs.event_time.strftime("%H:%M:%S"),
                    data["receive"].strftime("%H:%M:%S.%f")[:-3],
                    str(obs.temperature_c),
                )
    for source, data in state.items():
        if data.get("error"):
            table.add_row("", source, "--", "--", data["error"])
    return table


async def collect(
    sources: list[HttpSource],
    stations: set[str],
    database: Path,
    raw_path: Path,
    duration: float | None,
    live: bool = True,
    transport: httpx.AsyncBaseTransport | None = None,
    pws_settings: "Settings | None" = None,
    pws_airports: set[str] | None = None,
    continuous_config: "Config | None" = None,
) -> str:
    if pws_settings is not None and (duration is None or not 0 < duration <= 86400):
        raise ValueError("Combined PWS collection requires a duration in (0,86400] seconds")
    run_id = utc_now().strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:8]
    stop = asyncio.Event()
    state: dict[str, Any] = {}
    reference_gate = ReferenceGate() if continuous_config is not None else None
    console = Console()
    clock = await asyncio.to_thread(clock_status)
    console.print("Clock warning: " + clock["warning"], style="yellow")
    protocol = files("premetar").joinpath("protocol.md").read_text(encoding="utf-8")
    manifest = {
        "run_id": run_id,
        "version": __version__,
        "clock": clock,
        "started_at": utc_now().isoformat(),
        "stations": sorted(stations),
        "sources": [
            {"name": s.name, "url": s.url, "interval_sec": s.interval_sec} for s in sources
        ],
        "protocol": protocol,
        "protocol_sha256": hashlib.sha256(protocol.encode()).hexdigest(),
    }
    if pws_settings is not None:
        manifest["pws_settings"] = pws_settings.model_dump()
        pws_protocol = files("premetar.pws").joinpath("protocol.md").read_text(encoding="utf-8")
        manifest["pws_protocol"] = pws_protocol
        manifest["pws_protocol_sha256"] = hashlib.sha256(pws_protocol.encode()).hexdigest()
    # One collector per DB, including across processes; a live lock is never stolen.
    await asyncio.to_thread(database.parent.mkdir, parents=True, exist_ok=True)
    lock = database.with_suffix(database.suffix + ".lock")
    from premetar.continuous.locking import acquire

    if continuous_config is not None:
        manifest["continuous_config"] = continuous_config.model_dump(mode="json")
        from dataclasses import asdict

        from premetar.pws.timestamps import policy

        manifest["timestamp_policy"] = asdict(policy())
        manifest["reference_receipt_barrier"] = "HTTP_COMPLETE_UNTIL_DURABLE_PARSE"

        continuous_protocol = (
            files("premetar.continuous").joinpath("protocol.md").read_text(encoding="utf-8")
        )
        manifest["continuous_protocol"] = continuous_protocol
        manifest["continuous_protocol_sha256"] = hashlib.sha256(
            continuous_protocol.encode()
        ).hexdigest()
        source_names = [
            "collector.py",
            "parsers.py",
            "pws/analysis.py",
            "pws/quality.py",
            "pws/timestamps.py",
            "pws/integrity.py",
            "continuous/reference_gate.py",
            "pws/providers.py",
            "continuous/config.py",
            "continuous/data.py",
            "continuous/engine.py",
            "continuous/polling.py",
        ]
        manifest["algorithm_source_sha256"] = {
            name: hashlib.sha256(files("premetar").joinpath(name).read_bytes()).hexdigest()
            for name in source_names
        }

    lock_file = acquire(lock, run_id, recover=continuous_config is not None)
    if pws_settings is not None or continuous_config is not None:
        from premetar.pws.repository import PWSStore

        store: Store = PWSStore(database, raw_path, run_id)
    else:
        store = Store(database, raw_path, run_id)
    store_open = False
    tasks: list[asyncio.Task[None]] = []
    previous_handlers = {}
    reason = "graceful_shutdown"
    try:
        if continuous_config is not None and continuous_config.stop_path.exists():
            continuous_config.stop_path.unlink()
        await store.open(manifest, {s.name: s.interval_sec for s in sources})
        store_open = True
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                previous_handlers[sig] = signal.signal(sig, lambda *_: stop.set())
            except ValueError:
                pass  # Tests or embedded calls can run outside the main thread.
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20),
            verify=context,
            follow_redirects=False,
            headers={"User-Agent": "michupl-pre-metar/" + __version__ + " prospective research"},
            transport=transport,
        ) as client:
            tasks = [
                asyncio.create_task(
                    poll_source(s, store, client, stop, state, reference_gate), name=s.name
                )
                for s in sources
            ]
            if pws_settings is not None:
                from premetar.pws.providers import PROVIDERS, PWSProvider, Transport
                from premetar.pws.repository import PWSStore
                from premetar.pws.service import collect as collect_pws

                assert isinstance(store, PWSStore)
                pws_store = store
                pws_http = Transport(client, pws_store)
                pws_providers: list[PWSProvider] = [
                    PROVIDERS[p](pws_http) for p in pws_settings.providers
                ]
                await pws_store._call(pws_store.register, pws_settings.airports, pws_providers)

                async def pws_loop() -> None:
                    assert pws_settings is not None and duration is not None
                    await collect_pws(
                        pws_store,
                        pws_providers,
                        pws_settings,
                        pws_airports or {a.icao for a in pws_settings.airports},
                        duration,
                        stop,
                    )

                tasks.append(asyncio.create_task(pws_loop(), name="pws"))
            if continuous_config is not None:
                from premetar.continuous.engine import run_jobs
                from premetar.pws.repository import PWSStore

                assert isinstance(store, PWSStore)
                tasks.append(
                    asyncio.create_task(
                        run_jobs(store, client, stop, continuous_config, reference_gate),
                        name="continuous",
                    )
                )
            started = time.monotonic()
            with Live(
                live_table(stations, state),
                console=console,
                refresh_per_second=1,
                auto_refresh=False,
                transient=not live,
            ) as display:
                while not stop.is_set():
                    if duration is not None and time.monotonic() - started >= duration:
                        reason = "duration_complete"
                        break
                    failed = [t for t in tasks if t.done() and t.exception() is not None]
                    if failed:
                        # Infrastructure failure (e.g. disk/DB) cannot silently abandon raw capture.
                        raise RuntimeError("Collector storage task failed") from failed[
                            0
                        ].exception()
                    if all(t.done() for t in tasks):
                        reason = "all_sources_disabled"
                        break
                    if continuous_config is not None and continuous_config.stop_path.exists():
                        reason = "stop_requested"
                        break
                    await store.heartbeat()
                    if live:
                        display.update(live_table(stations, state), refresh=True)
                    await wait_or_stop(stop, 1)
            stop.set()
            # Let buffered/raw writes finish; requests have a bounded timeout.
            await asyncio.gather(*tasks)
            console.print(live_table(stations, state))
    except BaseException:
        reason = "collector_failure"
        stop.set()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        raise
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
        try:
            if store_open:
                await store.close(reason)
            else:
                store.executor.shutdown(wait=True)
        finally:
            lock_file.close()
            lock.unlink()
    console.print(f"Run {run_id}: {reason}")
    if reason == "all_sources_disabled":
        raise RuntimeError("All source adapters disabled; inspect status")
    return run_id
