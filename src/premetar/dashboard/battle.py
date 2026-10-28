"""Read-only historical EXP0014/15 presentation. Checkpoints never leak into replay."""

from datetime import UTC, date, datetime
from typing import Any

from premetar.dashboard.service import DashboardService, forecast_view
from premetar.pws.daily_time import local_day_bounds
from premetar.research.battle_monitor import DIRECTORY
from premetar.research.battle_store import read_battle
from premetar.research.realization import evaluate_realization


def battle_view(service: DashboardService, day: date, at: datetime | None = None) -> dict[str, Any]:
    _, end = local_day_bounds(day, "Europe/Warsaw")
    cutoff = min(at or datetime.now(UTC), datetime.now(UTC), end).replace(microsecond=0)
    # Exclusive day-end: do not include next day's midnight events in a replay.
    if cutoff == end:
        from datetime import timedelta

        cutoff -= timedelta(microseconds=1)
    events = read_battle(DIRECTORY, cutoff, limit=20000)
    start, _ = local_day_bounds(day, "Europe/Warsaw")
    today = [e for e in events if start <= datetime.fromisoformat(e["at"]) <= cutoff]
    metric = next((e for e in reversed(events) if e["kind"] == "METRIC"), None)
    previous = next((e["payload"] for e in reversed(events) if e["kind"] == "CONFIDENCE"), None)
    forecasts = [e["payload"] for e in events if e["kind"] == "FORECAST"]
    raw = service.raw(day)
    realization = evaluate_realization(
        raw.get("metars", []),
        raw.get("forecasts", []) + forecasts,
        raw.get("pws", []),
        cutoff,
        previous,
    )
    realization["forecast_revision_c"] = forecast_view(
        raw.get("forecasts", []) + forecasts, day, cutoff
    ).get("delta_tmax")
    realization["view_semantics"] = "AS_OF_RECONSTRUCTION_NOT_AN_IMMUTABLE_LIVE_CONFIDENCE_EVENT"
    latest_rich = max(
        (f for f in forecasts if datetime.fromisoformat(f["first_received"]) <= cutoff),
        key=lambda f: f["first_received"],
        default=None,
    )
    realization["daily_api_tmax"] = None
    if latest_rich:
        from zoneinfo import ZoneInfo

        daily = latest_rich.get("daily_api") or {}
        for stamp, value in zip(
            daily.get("time", []), daily.get("temperature_2m_max", []), strict=False
        ):
            if (
                datetime.fromtimestamp(stamp, UTC).astimezone(ZoneInfo("Europe/Warsaw")).date()
                == day
            ):
                realization["daily_api_tmax"] = dict(
                    temperature_c=value,
                    first_received=latest_rich["first_received"],
                    semantics=latest_rich["daily_semantics"],
                    expected_peak_time=None,
                )
    payload = metric["payload"] if metric else {}
    health = dict(payload.get("health") or {"state": "NOT_STARTED"})
    if metric:
        health["last_metric_at"] = metric["at"]
        health["age_seconds"] = (cutoff - datetime.fromisoformat(metric["at"])).total_seconds()
        if health["age_seconds"] > 180:
            health["state"] = "STALE"
    equity_buckets = {}
    excluded: dict[tuple[Any, ...], str] = {}
    by_id = {e["id"]: e for e in events}
    for event in events:
        if event["kind"] == "ACCOUNTING_EXCLUSION":
            p = event["payload"]
            original = by_id.get(p.get("original_event_id"))
            if original:
                key = tuple(p.get(k) for k in ("family", "mode", "scenario", "latency_ms"))
                excluded[key] = min(excluded.get(key, original["at"]), original["at"])
    for event in today:
        if event["kind"] == "METRIC":
            for strategy in event["payload"].get("strategies", []):
                item = {
                    k: strategy.get(k)
                    for k in (
                        "family",
                        "mode",
                        "scenario",
                        "latency_ms",
                        "equity",
                        "realized_pnl",
                        "unrealized_pnl",
                        "drawdown",
                        "exposure_usd",
                    )
                }
                key = tuple(strategy.get(k) for k in ("family", "mode", "scenario", "latency_ms"))
                if key in excluded and event["at"] >= excluded[key]:
                    for name in ("equity", "realized_pnl", "unrealized_pnl", "drawdown"):
                        item[name] = None
                item["at"] = event["at"]
                bucket = int(datetime.fromisoformat(event["at"]).timestamp() // 300)
                equity_buckets[(*key, bucket)] = item
    return dict(
        asof=cutoff.isoformat(),
        cutoff=cutoff.isoformat(),
        realization=realization,
        strategies=payload.get("strategies", []),
        equity=list(equity_buckets.values()),
        equity_sampling="LATEST_RECORDED_METRIC_PER_5_MINUTE_BUCKET_NO_INTERPOLATION",
        events=[
            dict(
                e,
                **{
                    k: e["payload"].get(k)
                    for k in ("family", "mode", "scenario", "latency_ms", "condition_id")
                },
            )
            for e in today
            if e["kind"] not in {"FORECAST_RAW", "FALLBACK_WS_RAW", "METRIC"}
        ][-500:],
        health=health,
        sample_days=len(payload.get("sample_days", [])),
        coverage=payload.get("coverage", {}),
        completed_settlement_days=payload.get("completed_settlement_days", []),
        limits=events.metadata,
        limitations=[
            "SHADOW ONLY — brak prawdziwych zleceń",
            "Maker: nieznana pozycja w kolejce; brak identyfikowalnej gwarancji fillu",
            "Taker: warunkowa symulacja widocznej głębokości, nie potwierdzone wykonanie",
            "WEATHER SIGNAL-ONLY; brak zwalidowanej reguły kierunku kontraktu",
            "Otwarte pozycje bez świeżej pełnej płynności mają nieznane equity",
            "Brak dowodu przewagi; dni rozliczeniowe są jednostkami statystycznymi",
            "Metryki portfela są ostatnim utrwalonym stanem PRZED kursorem, nie bieżącym przeliczeniem cen",
            "Historia ograniczona limitami odczytu — szczegóły w limits",
        ],
    )
