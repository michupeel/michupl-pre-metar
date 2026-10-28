"""Synthetic sidecar regression tests: causality, isolation, restart and raw-first."""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from premetar.research import forecast_monitor as module  # noqa: E402
from premetar.research.trader_store import TraderStore  # noqa: E402

AT = datetime(2026, 10, 28, 12, tzinfo=UTC)


def test_hourly_forecast_cannot_leak_to_original_metar_receipt() -> None:
    f = {
        "first_received": AT.isoformat(),
        "points": [
            {"valid_time": (AT - timedelta(hours=1)).isoformat(), "temperature_c": 10},
            {"valid_time": AT.isoformat(), "temperature_c": 12},
        ],
    }
    assert module.forecast_at(f, AT - timedelta(seconds=1)) is None
    assert module.forecast_at(f, AT, AT - timedelta(minutes=1))["temperature_c"] == 10
    assert module.forecast_at(f, AT + timedelta(hours=2)) is None


def test_two_information_windows_preserve_nominal_target() -> None:
    assert AT in module.decision_targets("EPWA", AT)
    targets = module.decision_targets("EPWA", AT + timedelta(seconds=60))
    assert AT in targets
    assert AT + timedelta(minutes=30) in targets
    assert AT not in module.decision_targets("EPWA", AT + timedelta(seconds=91))


def test_london_station_mismatch_is_retained_not_substituted() -> None:
    market = dict(
        slug="highest-temperature-in-london-on-october-28-2026-15c",
        active=True,
        closed=False,
        acceptingOrders=True,
        conditionId="condition",
        version="v1",
        clobTokenIds='["1","2"]',
        outcomes='["Yes","No"]',
        description="Reference Airport (EGLC)",
    )
    result = module.market_identity(market, AT)
    assert result["station"] == "EGLC"
    assert result["airport"] == "EGLL"
    assert not result["station_match"]


@pytest.mark.asyncio
async def test_raw_capture_precedes_json_failure_and_rate_limit(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="not json", headers={"Retry-After": "120"})

    store = TraderStore(tmp_path / "research.sqlite3")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        observer = module.Observer(store, client)
        with pytest.raises(httpx.HTTPStatusError):
            await observer.get("https://api.open-meteo.com/v1/forecast")
        assert store.events("RAW")[0]["payload"]["body"] == "not json"
        with pytest.raises(RuntimeError, match="HOST_BACKOFF"):
            await observer.get("https://api.open-meteo.com/v1/forecast")
    store.close()


def test_compressed_raw_roundtrip_is_lossless(tmp_path: Path) -> None:
    import base64
    import zlib

    store = TraderStore(tmp_path / "research.sqlite3")
    observer = module.Observer(store, httpx.AsyncClient())
    original = '{"event_type":"price_change","price_changes":[]}'
    observer.emit("WS_RAW", {"text": original, "connection_id": "a"}, AT)
    raw = store.events("WS_RAW")[0]["payload"]
    assert zlib.decompress(base64.b64decode(raw["compressed_text"])).decode() == original
    observer.emit("WS_DELTA", {"price_changes": []}, AT)
    assert not store.events("WS_DELTA")
    store.close()


@pytest.mark.asyncio
async def test_outcomes_are_separate_idempotent_and_early_receipt_excluded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlite3

    db = tmp_path / "weather.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript(
        "create table observations(id,station_icao,product_type,event_time,identity,temperature_c,data_json); create table report_receipts(observation_id,collector_receive_time);"
    )
    conn.execute(
        "insert into observations values(1,'EPWA','METAR',?,'original',12,'{}')", (AT.isoformat(),)
    )
    conn.execute(
        "insert into report_receipts values(1,?)", ((AT - timedelta(seconds=5)).isoformat(),)
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(module, "WEATHER", db)
    monkeypatch.setattr(module, "now", lambda: AT + timedelta(minutes=1))
    store = TraderStore(tmp_path / "research.sqlite3")
    async with httpx.AsyncClient() as client:
        observer = module.Observer(store, client)
        inputs = dict(
            airport="EPWA",
            target=AT.isoformat(),
            predicted_metar_integer=12,
            previous_metar_integer=11,
        )
        store.append(
            "SIGNAL",
            dict(version=module.VERSION, created_at=AT.isoformat(), inputs=inputs),
            AT,
            "signal",
        )
        before = store.events("SIGNAL")
        await observer.outcomes_once()
        await observer.outcomes_once()
        outcomes = store.events("OUTCOME")
        assert len(outcomes) == 1
        assert outcomes[0]["payload"]["status"] == "EXCLUDED_ALREADY_RECEIVED"
        assert before == store.events("SIGNAL")
    store.close()


def test_restart_keeps_first_forecast_and_immutable_events(tmp_path: Path) -> None:
    path = tmp_path / "research.sqlite3"
    store = TraderStore(path)
    store.append("FORECAST", {"airport": "EPWA", "first_received": AT.isoformat()}, AT, "unique")
    assert not store.append(
        "FORECAST",
        {"airport": "EPWA", "first_received": (AT + timedelta(seconds=10)).isoformat()},
        AT,
        "unique",
    )
    store.close()
    store = TraderStore(path)
    with httpx.Client():
        observer = module.Observer(store, httpx.AsyncClient())
        assert observer.forecasts["EPWA"]["first_received"] == AT.isoformat()
        assert observer.prior_forecast("EPWA", AT - timedelta(microseconds=1)) is None
        assert observer.prior_forecast("EPWA", AT)["first_received"] == AT.isoformat()
    store.close()


@pytest.mark.asyncio
async def test_failure_does_not_terminate_independent_lifecycle(tmp_path: Path) -> None:
    store = TraderStore(tmp_path / "research.sqlite3")
    async with httpx.AsyncClient() as client:
        observer = module.Observer(store, client)

        async def fail() -> None:
            observer.stop.set()
            raise ValueError("synthetic")

        await observer.loop("FAULT", fail, 0.01)
        assert store.events("ERROR")[0]["payload"]["error_class"] == "ValueError"
    store.close()


@pytest.mark.asyncio
async def test_mismatched_station_never_becomes_control_period(tmp_path: Path) -> None:
    store = TraderStore(tmp_path / "research.sqlite3")
    async with httpx.AsyncClient() as client:
        observer = module.Observer(store, client)
        observer.markets = [
            {
                "identity": dict(
                    airport="EGLL",
                    station="EGLC",
                    station_match=False,
                    yes="1",
                    no="2",
                    condition_id="c",
                ),
                "metadata": {},
            }
        ]
        await observer.diagnostics_once()
        sample = store.events("BOOK_SAMPLE")[0]["payload"]
        assert sample["period"] == "STATION_MISMATCH_NOT_COMPARABLE"
    store.close()


def test_snapshot_is_consistent_and_source_unchanged(tmp_path: Path) -> None:
    import sqlite3

    src, dest = tmp_path / "source.sqlite3", tmp_path / "snapshot.sqlite3"
    c = sqlite3.connect(src)
    c.execute("create table evidence(value)")
    c.execute("insert into evidence values('original')")
    c.commit()
    c.close()
    before = src.read_bytes()
    result = module.backup_weather(src, dest)
    assert result["integrity"] == "ok"
    assert src.read_bytes() == before
    assert len(result["sha256"]) == 64


@pytest.mark.asyncio
async def test_early_reference_blocks_calibrated_signal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlite3

    db = tmp_path / "weather.sqlite3"
    c = sqlite3.connect(db)
    c.executescript(
        "create table observations(id,station_icao,product_type,event_time); create table report_receipts(observation_id,collector_receive_time);"
    )
    c.execute(
        "insert into observations values(1,'EHAM','METAR',?)",
        ((AT + timedelta(minutes=25)).isoformat(),),
    )
    c.execute("insert into report_receipts values(1,?)", (AT.isoformat(),))
    c.commit()
    c.close()
    monkeypatch.setattr(module, "WEATHER", db)
    store = TraderStore(tmp_path / "research.sqlite3")
    async with httpx.AsyncClient() as client:
        observer = module.Observer(store, client)
        observer.calibration_data = {"EHAM": {"sensors": {"s": {"dummy": True}}}}
        observer.calibrated_signal("EHAM", {"sensor_id": "s"}, [], AT + timedelta(minutes=24), None)
        assert not store.events("SIGNAL")
    store.close()


@pytest.mark.asyncio
async def test_startup_metar_is_context_and_has_no_future_forecast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "CITIES", {"warsaw": "EPWA"})
    monkeypatch.setattr(module, "now", lambda: AT)
    monkeypatch.setattr(
        module,
        "weather_context",
        lambda *_: {
            "metar": [
                {
                    "id": 1,
                    "collector_receive_time": (AT - timedelta(minutes=20)).isoformat(),
                    "event_time": (AT - timedelta(minutes=30)).isoformat(),
                }
            ]
        },
    )
    store = TraderStore(tmp_path / "research.sqlite3")
    store.append(
        "FORECAST", {"airport": "EPWA", "first_received": AT.isoformat(), "points": []}, AT
    )
    async with httpx.AsyncClient() as client:
        observer = module.Observer(store, client)
        await observer.weather_once()
        payload: dict[str, Any] = store.events("SIGNAL")[0]["payload"]
        assert payload["kind"] == "METAR_CONTEXT_DISCOVERED"
        assert payload["inputs"]["startup_censored"]
        assert payload["inputs"]["forecast"] is None
        assert json.loads(json.dumps(payload))["trading_instruction"] is False
    store.close()
