"""Synthetic causal replay and isolated storage tests; no public API calls."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from premetar.dashboard.app import create_app
from premetar.research import d1_monitor as module
from premetar.research.battle_store import BattleStore, read_battle
from premetar.research.d1_reports import generate

AT = datetime(2026, 10, 29, 12, tzinfo=UTC)


def market():
    return dict(
        slug="highest-temperature-in-warsaw-on-october-30-2026-9c",
        conditionId="c",
        active=True,
        closed=False,
        acceptingOrders=True,
        outcomes='["Yes","No"]',
        clobTokenIds='["1","2"]',
        groupItemTitle="9°C",
        description="Warsaw Chopin Airport (EPWA). local time hourly temperature remark routine SPECI does not count half rounded up to the next higher https://aviationweather.gov/api/data/metar?ids=EPWA",
        resolutionSource="https://aviationweather.gov/api/data/metar?ids=EPWA",
    )


def test_normalize_explicit_market_and_threshold():
    m = module.normalize_market(market(), AT)
    assert m["identity"]["settlement_date"] == "2026-10-30"
    assert m["identity"]["tokens"] == {"YES": "1", "NO": "2"}
    assert m["outcome"]["kind"] == "EXACT"
    raw = market()
    raw["groupItemTitle"] = "9°C or below"
    assert module.normalize_market(raw, AT)["outcome"]["kind"] == "AT_MOST"
    raw["description"] = "Warsaw weather only"
    assert module.normalize_market(raw, AT)["rules_status"] == "UNVERIFIED"


def test_tail_startup_censors_historical_books(tmp_path):
    path = tmp_path / "source.sqlite3"
    with sqlite3.connect(path) as c:
        c.execute(
            "create table events(id integer primary key,kind text,received_at text,payload text)"
        )
        c.executemany(
            "insert into events values(?,?,?,?)",
            [(1, "STREAMHEALTH", AT.isoformat(), "{}"), (2, "WS_RAW", AT.isoformat(), "{}")],
        )
    cursor, events = module.tail(path, None)
    assert cursor == 2 and [e["kind"] for e in events] == ["STREAMHEALTH"]
    assert module.tail(path, cursor) == (2, [])


def test_asof_never_uses_future_snapshot_or_forecast(tmp_path):
    store = BattleStore(tmp_path, min_free_bytes=0)
    store.commit(
        [
            dict(
                kind="D1_SNAPSHOT",
                at=AT.isoformat(),
                payload=dict(
                    decision_day="2026-10-29",
                    markets=[dict(settlement_date="2026-10-30", title="earlier")],
                    health=dict(state="RUNNING"),
                ),
            ),
            dict(
                kind="D1_SNAPSHOT",
                at=(AT + timedelta(seconds=10)).isoformat(),
                payload=dict(
                    decision_day="2026-10-29",
                    markets=[dict(settlement_date="2026-10-30", title="future")],
                ),
            ),
        ],
        {},
        {},
        AT + timedelta(seconds=10),
    )
    assert module.view(AT, tmp_path)["markets"][0]["title"] == "earlier"
    assert not module.view(AT - timedelta(seconds=1), tmp_path)["markets"]
    assert module.view(AT + timedelta(seconds=200), tmp_path)["health"]["state"] == "STALE"
    store.close()


def test_midnight_does_not_reuse_previous_tomorrow(tmp_path):
    store = BattleStore(tmp_path, min_free_bytes=0)
    store.commit(
        [
            dict(
                kind="D1_SNAPSHOT",
                at=AT.isoformat(),
                payload=dict(
                    decision_day="2026-10-29", markets=[dict(settlement_date="2026-10-30")]
                ),
            )
        ],
        {},
        {},
        AT,
    )
    assert not module.view(AT + timedelta(days=1), tmp_path)["markets"]
    store.close()


def test_shared_source_no_duplicate_subscription(tmp_path, monkeypatch):
    store = BattleStore(tmp_path, min_free_bytes=0)
    monitor = module.D1Monitor(store)
    monitor.markets = {"c": {"tokens": {"YES": "y", "NO": "n"}}}
    tracker = module.BookTracker(5)
    monitor.sources["existing"] = tracker
    monitor.normalize(
        tracker,
        "BOOK",
        dict(
            token_id="n",
            connection_id="a",
            market="c",
            complete=True,
            bids=[dict(price=".4", size="10")],
            asks=[dict(price=".5", size="10")],
        ),
        AT,
    )
    monitor.last_raw["existing"] = AT
    monkeypatch.setattr(module, "now", lambda: AT)
    assert monitor.missing_tokens() == ["y"]
    assert monitor.book("n", AT)["best_ask"] == "0.5"
    assert monitor.book("n", AT + timedelta(seconds=6))["status"] != "VALID"
    store.close()


async def test_public_error_is_raw_first(tmp_path, monkeypatch):
    store = BattleStore(tmp_path, min_free_bytes=0)
    monitor = module.D1Monitor(store)
    transport = httpx.MockTransport(lambda _: httpx.Response(429, json={"error": "slow"}))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await monitor.get(client, "https://example.test", {})
    events = read_battle(tmp_path)
    assert events[-1]["kind"] == "D1_HTTP_RAW" and events[-1]["payload"]["status"] == 429
    store.close()


async def test_malformed_forecast_and_empty_discovery_are_raw_preserved(tmp_path, monkeypatch):
    store = BattleStore(tmp_path, min_free_bytes=0)
    monitor = module.D1Monitor(store)
    monkeypatch.setattr(module, "airport_coordinates", lambda: (52.0, 21.0))
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=[]))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ValueError, match="forecast object"):
            await monitor.forecast(client)
        await monitor.discover(client)
    events = read_battle(tmp_path)
    assert sum(e["kind"] == "D1_HTTP_RAW" for e in events) == 3
    assert all(e["payload"]["markets"] == 0 for e in events if e["kind"] == "D1_DISCOVERY")
    assert not monitor.forecasts and not monitor.markets
    store.close()


def test_restart_preserves_captured_forecasts_without_replaying_books(tmp_path):
    store = BattleStore(tmp_path, min_free_bytes=0)
    store.commit(
        [],
        dict(markets={"c": {"tokens": {"YES": "y", "NO": "n"}}}, forecasts=[dict(model="test")]),
        {},
        AT,
    )
    monitor = module.D1Monitor(store)
    assert monitor.forecasts == [dict(model="test")]
    assert monitor.missing_tokens() == ["n", "y"]
    assert monitor.own.books == {}
    assert store.connection.execute("pragma integrity_check").fetchone()[0] == "ok"
    store.close()


async def test_malformed_shared_frame_does_not_drop_next_good_event(tmp_path, monkeypatch):
    source = tmp_path / "source.sqlite3"
    with sqlite3.connect(source) as c:
        c.execute(
            "create table events(id integer primary key,kind text,received_at text,payload text)"
        )
        bad = dict(connection_id="a", text="{")
        good = dict(
            connection_id="a",
            text=json.dumps(
                dict(
                    event_type="book",
                    asset_id="n",
                    market="c",
                    bids=[dict(price=".4", size="10")],
                    asks=[dict(price=".5", size="10")],
                )
            ),
        )
        c.executemany(
            "insert into events values(?,?,?,?)",
            [
                (1, "WS_RAW", AT.isoformat(), json.dumps(bad)),
                (2, "WS_RAW", AT.isoformat(), json.dumps(good)),
            ],
        )
    store = BattleStore(tmp_path / "journal", min_free_bytes=0)
    monitor = module.D1Monitor(store)
    monitor.cursors[str(source)] = 0
    monkeypatch.setattr(monitor, "paths", lambda: [source])
    await monitor.reuse()
    assert monitor.sources[str(source)].view("n", AT)["status"] == "VALID"
    assert monitor.cursors[str(source)] == 2
    assert any(e["kind"] == "D1_SOURCE_GAP" for e in read_battle(store.directory))
    store.close()


def test_queued_unsubscribed_frame_cannot_invalidate_other_book(tmp_path):
    store = BattleStore(tmp_path, min_free_bytes=0)
    monitor = module.D1Monitor(store)
    monitor.own_emit(
        "STREAMHEALTH", dict(state="SUBSCRIBED", connection_id="a", tokens=["n"]), AT, None
    )
    book = dict(
        connection_id="a",
        token_id="n",
        market="c",
        complete=True,
        bids=[dict(price=".4", size="10")],
        asks=[dict(price=".5", size="10")],
    )
    monitor.own_emit("BOOK", book, AT, None)
    monitor.own_emit("BOOK", dict(book, token_id="removed"), AT, None)
    assert monitor.own.view("n", AT)["status"] == "VALID"
    store.close()


def test_report_regeneration_deterministic_empty(tmp_path):
    out = tmp_path / "reports"
    generate(AT, tmp_path / "missing", out)
    first = {p.name: p.read_bytes() for p in out.iterdir()}
    generate(AT, tmp_path / "missing", out)
    assert first == {p.name: p.read_bytes() for p in out.iterdir()}
    assert json.loads((out / "summary.json").read_text())["strategies"][0]["net_pnl"] is None


def test_dashboard_projection_never_decodes_raw_archive(tmp_path):
    store = BattleStore(tmp_path, min_free_bytes=0)
    store.commit(
        [dict(kind="D1_HTTP_RAW", at=AT.isoformat(), payload=dict(text="not JSON"))], {}, {}, AT
    )
    assert module.read_state(tmp_path, AT) == []
    store.close()


async def test_dashboard_endpoint_readonly_causal(monkeypatch):
    monkeypatch.setattr(module, "view", lambda at: dict(asof=at.isoformat(), markets=[]))
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as c:
        assert (await c.get("/api/tomorrow", params={"at": AT.isoformat()})).status_code == 200
        assert (
            await c.get("/api/tomorrow", params={"at": "2026-10-29T12:00:00"})
        ).status_code == 422
        assert (await c.post("/api/tomorrow")).status_code == 405
        assert (
            await c.get("/api/tomorrow", headers={"Origin": "https://evil.test"})
        ).status_code == 403
