"""Loopback-only dashboard HTTP API. All database access is read-only."""

import asyncio
import json
import time
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from premetar.dashboard.reader import Reader
from premetar.dashboard.segments import SegmentReader
from premetar.dashboard.service import ZONE, DashboardService, clock

ROOT = Path(__file__).resolve().parents[3]
STATIC = Path(__file__).parent / "static"


def create_app(reader: Reader | None = None) -> FastAPI:
    service = DashboardService(
        reader
        or SegmentReader(
            ROOT / "data/continuous-v1.sqlite3",
            ROOT / "data/research/exp0013/observations.sqlite3",
            ROOT / "data/trader/monitor.sqlite3",
        )
    )
    application = FastAPI(title="MICHUPL EPWA — odczyt lokalny", docs_url=None, redoc_url=None)
    application.state.service = service

    @application.middleware("http")
    async def local_only(request: Request, call_next: Any) -> Any:
        # Reject DNS rebinding, cross-origin scripts and arbitrary Host headers.
        host = request.headers.get("host", "").split(":")[0]
        if host not in {"127.0.0.1", "localhost", "testserver"}:
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": "Loopback Host required"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": "Same-origin required"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def selected_day(value: str | None) -> date:
        try:
            day = date.fromisoformat(value) if value else datetime.now(ZONE).date()
        except ValueError:
            raise HTTPException(422, "Niepoprawna data ISO") from None
        today = datetime.now(ZONE).date()
        if not today - timedelta(days=365) <= day <= today + timedelta(days=10):
            raise HTTPException(422, "Data poza zakresem −365/+10 dni")
        return day

    def cutoff(value: str | None) -> datetime | None:
        if value is None:
            return None
        at = clock(value)
        if at is None:
            raise HTTPException(422, "Wymagany czas ISO z offsetem UTC")
        if at > datetime.now(UTC) + timedelta(seconds=1):
            raise HTTPException(422, "Nie można odtworzyć przyszłej dostępności")
        return at

    @application.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @application.get("/api/day")
    def day(date: str | None = None, asof: str | None = None) -> dict[str, Any]:
        return service.day(selected_day(date), cutoff(asof))

    @application.get("/api/asof")
    def asof(at: str, date: str | None = None, market: str | None = None) -> dict[str, Any]:
        point = cutoff(at)
        assert point is not None
        selected = selected_day(date)
        if point.astimezone(ZONE).date() != selected:
            raise HTTPException(422, "Czas inspekcji musi należeć do wybranego dnia lokalnego")
        if market and len(market) > 160:
            raise HTTPException(422, "Niepoprawny identyfikator kontraktu")
        return service.asof(selected, point, market)

    @application.get("/api/battle")
    def battle(date: str | None = None, at: str | None = None) -> dict[str, Any]:
        from premetar.dashboard.battle import battle_view

        selected, point = selected_day(date), cutoff(at)
        if point and point.astimezone(ZONE).date() != selected:
            raise HTTPException(422, "Czas inspekcji musi należeć do wybranego dnia")
        return battle_view(service, selected, point)

    @application.get("/api/tomorrow")
    def tomorrow(at: str | None = None) -> dict[str, Any]:
        from premetar.research.d1_monitor import view

        return view(cutoff(at) or datetime.now(UTC))

    @application.get("/api/events")
    async def events(request: Request) -> StreamingResponse:
        async def stream() -> AsyncIterator[str]:
            # Invalidation pulse only. Day cache is shared; no database query or
            # external network request is multiplied by SSE clients.
            for _ in range(720):
                if await request.is_disconnected():
                    break
                yield (
                    "event: refresh\ndata: "
                    + json.dumps(
                        {"utc": datetime.now(UTC).isoformat(), "version": int(time.time() // 5)}
                    )
                    + "\n\n"
                )
                await asyncio.sleep(5)

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
        )

    application.mount("/static", StaticFiles(directory=STATIC, check_dir=False), name="static")
    return application


def run(port: int = 8765) -> None:
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=port, access_log=False, log_level="warning")
