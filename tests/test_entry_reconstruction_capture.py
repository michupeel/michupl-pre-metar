"""Synthetic public-feed fixtures; no live WebSocket in tests."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from premetar.research import entry_reconstruction_capture as capture_module
from premetar.research.entry_reconstruction_capture import capture, select_watchlist
from premetar.research.trader_store import TraderStore, read_events


def market(at, condition="C", **updates):
    payload = dict(
        conditionId=condition,
        active=True,
        closed=False,
        acceptingOrders=True,
        slug="highest-temperature-in-warsaw-on-october-31-2026-12c",
        clobTokenIds='["YES","NO"]',
        outcomes='["Yes","No"]',
        outcomePrices='["0.05","0.95"]',
        description="Warsaw Chopin Airport (EPWA)",
    )
    payload.update(updates)
    return dict(id=1, received_at=at.isoformat(), payload=payload)


def test_frozen_selection_excludes_future_stale_wrong_markets_and_nonfinite():
    at = datetime.now(UTC)
    valid = market(at)
    rows = [
        valid,
        market(at + timedelta(seconds=1), "F"),
        market(at - timedelta(seconds=601), "S"),
        market(at, "X", closed=True),
        market(at, "Y", outcomePrices='["NaN","NaN"]'),
    ]
    selected = select_watchlist(rows, at)
    assert len(selected) == 1 and selected[0]["condition_id"] == "C"
    assert selected[0]["tokens"] == dict(yes="YES", no="NO")
    assert selected[0]["mark_status"] == "DISCOVERY_FILTER_NOT_EXECUTABLE_PRICE"
    assert "rank_hash" not in valid


def test_frozen_selection_is_deterministic_under_input_order():
    at = datetime.now(UTC)
    rows = [market(at, str(n)) for n in range(20)]
    assert select_watchlist(rows, at) == select_watchlist(list(reversed(rows)), at)
    assert len(select_watchlist(rows, at)) == 16


async def test_bounded_capture_is_raw_first_and_leaves_source_untouched(tmp_path, monkeypatch):
    source = tmp_path / "source.sqlite3"
    store = TraderStore(source)
    at = datetime.now(UTC) - timedelta(seconds=1)
    store.append("MARKET", market(at)["payload"], at)
    store.close()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    async def fake_stream(tokens, emit, stop):
        assert len(tokens()) == 2
        received = datetime.now(UTC)
        emit("STREAMHEALTH", dict(state="SUBSCRIBED", connection_id="one"), received, None)
        emit("WS_RAW", dict(text='{"event_type":"book"}', connection_id="one"), received, None)
        emit(
            "BOOK",
            dict(
                token_id=tokens()[0],
                complete=True,
                bids=[dict(price=".92", size="10")],
                asks=[dict(price=".94", size="5")],
                source="WS_FULL_SNAPSHOT",
                connection_id="one",
            ),
            received,
            None,
        )
        await stop.wait()

    monkeypatch.setattr(capture_module, "stream_market", fake_stream)
    result = await capture(1, tmp_path / "capture", source, tmp_path / "absent-weather")
    assert result["counts"]["BOOK"] == 1 and result["error_class"] is None
    assert result["integrity"] == "ok"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    events = read_events(next((tmp_path / "capture/books").glob("*.sqlite3")), limit=100)
    assert [e["kind"] for e in events] == ["RUN", "STREAMHEALTH", "WS_RAW", "BOOK", "STOP"]
    assert json.loads(json.dumps(result))["persistent_activation"] == "NOT_AUTHORIZED_NOT_INSTALLED"


async def test_no_eligible_watchlist_does_not_start_socket(tmp_path, monkeypatch):
    source = tmp_path / "source.sqlite3"
    store = TraderStore(source)
    store.close()
    called = False

    async def forbidden(*args):
        nonlocal called
        called = True

    monkeypatch.setattr(capture_module, "stream_market", forbidden)
    with pytest.raises(ValueError, match="No eligible"):
        await capture(1, tmp_path / "capture", source, tmp_path / "absent")
    assert not called
    assert not (tmp_path / "capture/monitor.lock").exists()


async def test_no_unbounded_capture(tmp_path):
    with pytest.raises(ValueError):
        await capture(3601, tmp_path / "capture")
