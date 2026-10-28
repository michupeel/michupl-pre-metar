"""Synthetic raw shapes and live-sidecar isolation; never calls external APIs."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from premetar.dashboard.app import create_app
from premetar.research import battle_monitor as module
from premetar.research.battle_store import BattleStore, read_battle
from premetar.research.trader_store import TraderStore

AT = datetime(2026, 10, 28, 12, tzinfo=UTC)


def test_prototype_unknown_accounting_is_audited_without_rewriting_events(tmp_path: Path) -> None:
    store = BattleStore(tmp_path / "journal", min_free_bytes=0)
    first = module.Monitor(store, config())
    p = first.engine.state["portfolios"]["SIMPLE:MAKER:EVIDENCE_SUPPORTED:1000"]
    order = dict(
        id="prototype",
        side="BUY",
        quantity="5",
        filled="0",
        limit=".95",
        state="REJECTED",
        day="2026-10-28",
        condition_id="c",
        token_id="2",
    )
    p["orders"].append(order)
    first.commit(
        [
            dict(
                kind="ORDER_REJECTED",
                at=AT.isoformat(),
                payload=dict(
                    family="SIMPLE",
                    mode="MAKER",
                    scenario="EVIDENCE_SUPPORTED",
                    latency_ms=1000,
                    order=order,
                    reason="ARRIVAL_BOOK_UNRESOLVED",
                ),
            )
        ]
    )
    second = module.Monitor(store, config())
    p2 = second.engine.state["portfolios"]["SIMPLE:MAKER:EVIDENCE_SUPPORTED:1000"]
    assert p2["reserved"] == "4.75"
    assert p2["orders"][0]["execution_unknown"]
    second.commit()
    events = read_battle(store.directory)
    assert events[0]["payload"]["order"]["state"] == "REJECTED"
    assert any(e["kind"] == "ACCOUNTING_EXCLUSION" for e in events)
    third = module.Monitor(store, config())
    assert (
        third.engine.state["portfolios"]["SIMPLE:MAKER:EVIDENCE_SUPPORTED:1000"]["reserved"]
        == "4.75"
    )
    store.close()


def config() -> dict:
    return json.loads(module.CONFIG.read_text(encoding="utf-8"))


def test_bootstrap_does_not_replay_old_quotes_or_trade_as_new(tmp_path: Path) -> None:
    source = TraderStore(tmp_path / "source.sqlite3")
    source.append(
        "STREAMHEALTH", dict(state="SUBSCRIBED", connection_id="epoch", tokens=["1", "2"]), AT
    )
    source.append("WS_RAW", dict(text='{"event_type":"last_trade_price"}'), AT)
    cursor, rows = module.source_rows(source.path, None)
    assert cursor == 2
    assert [r["kind"] for r in rows] == ["STREAMHEALTH"]
    assert all(r["bootstrap"] for r in rows)
    assert module.source_rows(source.path, cursor)[1] == []
    source.close()


def test_actual_market_local_date_schema_is_preserved(tmp_path: Path) -> None:
    store = BattleStore(tmp_path / "battle", min_free_bytes=0)
    monitor = module.Monitor(store, config())
    monitor.ingest(
        dict(
            kind="MARKET",
            received_at=AT.isoformat(),
            bootstrap=True,
            payload=dict(
                identity=dict(
                    airport="EPWA",
                    station_match=True,
                    local_date="2026-10-28",
                    condition_id="c",
                    yes="1",
                    no="2",
                ),
                metadata=dict(groupItemTitle="15°C"),
            ),
        )
    )
    assert monitor.markets["c"]["identity"]["day"] == "2026-10-28"
    assert monitor.markets["c"]["identity"]["outcome_label"] == "15°C"
    assert not any(p["orders"] for p in monitor.engine.state["portfolios"].values())
    store.close()


def test_live_tick_change_blocks_until_new_verified_metadata(tmp_path: Path) -> None:
    store = BattleStore(tmp_path / "battle", min_free_bytes=0)
    monitor = module.Monitor(store, config())
    payload = dict(
        identity=dict(
            airport="EPWA",
            station_match=True,
            local_date="2026-10-28",
            condition_id="c",
            yes="1",
            no="2",
        ),
        metadata=dict(orderPriceMinTickSize="0.01"),
    )
    monitor.ingest(dict(kind="MARKET", received_at=AT.isoformat(), payload=payload, bootstrap=True))
    monitor.inspect_tick(
        json.dumps(dict(event_type="tick_size_change", asset_id="2", new_tick_size="0.001")),
        AT + timedelta(seconds=1),
    )
    assert "2" in monitor.tick_blocks
    payload["metadata"]["orderPriceMinTickSize"] = "0.001"
    monitor.ingest(
        dict(
            kind="MARKET",
            received_at=(AT + timedelta(seconds=2)).isoformat(),
            payload=payload,
            bootstrap=True,
        )
    )
    assert not monitor.tick_blocks
    assert any(e["kind"] == "TICK_CHANGE_BLOCK" for e in read_battle(store.directory))
    store.close()


def test_forecast_separates_utc_points_from_warsaw_daily_aggregate() -> None:
    raw = dict(
        hourly_units=dict(time="unixtime", temperature_2m="°C"),
        hourly=dict(time=[int(AT.timestamp())], temperature_2m=[12.1], cloud_cover_low=[90]),
        daily=dict(time=[int(AT.timestamp())], temperature_2m_max=[13]),
    )
    result = module.normalize_forecast(raw, AT)
    assert result["points"][0]["temperature_c"] == 12.1
    assert result["points"][0]["cloud_cover_low"] == 90
    assert result["daily_api"]["temperature_2m_max"] == [13]
    assert result["hourly_maximum"] is None
    assert result["publication_time"] is None


@pytest.mark.asyncio
async def test_forecast_raw_is_durable_before_normalization_failure(tmp_path: Path) -> None:
    store = BattleStore(tmp_path / "battle", min_free_bytes=0)
    monitor = module.Monitor(store, config())
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text="bad-json"))
    ) as client:
        await monitor.enrich(client)
    events = read_battle(store.directory)
    assert [e["kind"] for e in events] == ["FORECAST_RAW", "ERROR"]
    assert events[0]["payload"]["body"] == "bad-json"
    assert monitor.forecasts == []
    store.close()


def test_restart_restores_cash_and_cursor_without_new_deposit(tmp_path: Path) -> None:
    store = BattleStore(tmp_path / "battle", min_free_bytes=0)
    first = module.Monitor(store, config())
    key = next(iter(first.engine.state["portfolios"]))
    p = first.engine.state["portfolios"][key]
    p["cash"] = "91.25"
    first.cursors["source"] = 42
    first.commit()
    second = module.Monitor(store, config())
    assert second.engine.state["portfolios"][key]["cash"] == "91.25"
    assert second.cursors["source"] == 42
    store.close()


class EmptyReader:
    def load_day(self, day):
        return {"metars": [], "forecasts": [], "pws": []}


@pytest.mark.asyncio
async def test_battle_api_empty_and_no_future_portfolio(tmp_path: Path, monkeypatch) -> None:
    from premetar.dashboard import battle

    directory = tmp_path / "journal"
    store = BattleStore(directory, min_free_bytes=0)
    store.commit(
        [
            dict(
                kind="METRIC",
                at=(AT + timedelta(seconds=1)).isoformat(),
                payload=dict(strategies=[dict(family="SIMPLE", net_pnl=999)]),
            )
        ],
        {},
        {},
        AT + timedelta(seconds=1),
    )
    monkeypatch.setattr(battle, "DIRECTORY", directory)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(EmptyReader())), base_url="http://testserver"
    ) as client:
        response = await client.get(
            "/api/battle", params=dict(date="2026-10-28", at=AT.isoformat())
        )
        assert response.status_code == 200
        assert response.json()["strategies"] == []
        assert response.json()["realization"]["state"] == "INSUFFICIENT DATA"
        assert (await client.post("/api/battle")).status_code == 405
        assert (
            await client.get("/api/battle?date=2026-10-25&at=2026-10-28T12:00:00Z")
        ).status_code == 422
    store.close()


def test_report_regeneration_deterministic(tmp_path: Path) -> None:
    from premetar.research.battle_reports import generate

    directory = tmp_path / "journal"
    store = BattleStore(directory, min_free_bytes=0)
    store.commit(
        [dict(kind="METRIC", payload=dict(strategies=[], realization={}, sample_days=[]))],
        {},
        {},
        AT,
    )
    generate(directory, tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.glob("reports/**/*") if p.is_file()}
    generate(directory, tmp_path)
    assert before == {p: p.read_bytes() for p in before}
    store.close()


@pytest.mark.asyncio
async def test_restart_gap_is_censored_and_subscription_bootstrapped(
    tmp_path: Path, monkeypatch
) -> None:
    source = TraderStore(tmp_path / "source.sqlite3")
    source.append(
        "STREAMHEALTH", dict(state="SUBSCRIBED", connection_id="new-epoch", tokens=["1", "2"]), AT
    )
    source.append("WS_RAW", dict(text='{"event_type":"last_trade_price"}'), AT)

    class Sources:
        def __init__(self, *args):
            pass

        def paths(self):
            return [source.path]

    monkeypatch.setattr(module, "SegmentReader", Sources)
    store = BattleStore(tmp_path / "journal", min_free_bytes=0)
    monitor = module.Monitor(store, config())
    monitor.cursors[str(source.path)] = 1
    monitor.started = AT
    await monitor.run(0.01)
    assert monitor.tracker.connection_id == "new-epoch"
    assert monitor.tracker.books == {}
    assert monitor.cursors[str(source.path)] == 2
    rows = read_battle(store.directory)
    assert any(e["kind"] == "RESTART_GAP" for e in rows)
    assert not any(e["kind"] == "BUY_FILL" for e in rows)
    source.close()
    store.close()
