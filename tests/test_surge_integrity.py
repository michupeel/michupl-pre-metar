"""Synthetic edge cases and separately labeled observed public forensic fixture."""

import asyncio
import json
import runpy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from premetar.research.battle_store import BattleStore
from premetar.research.surge_associations import associate
from premetar.research.surge_buffer import RollingBuffer
from premetar.research.surge_detector import detect_changes
from premetar.research.surge_hunter import SurgeMonitor
from premetar.research.surge_identity import match_public_trade
from premetar.research.surge_liquidity import liquidity_paths
from premetar.research.surge_states import book_state
from premetar.research.trader_stream import _normalize_message, _stream_market

decode_v2_receipt = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/research/hightemptation_books.py")
)["decode_v2_receipt"]

AT = datetime(2026, 10, 31, 8, 58, 33, tzinfo=UTC)


def quote(side="no", seconds=0, **updates):
    d = dict(
        token_id=side,
        condition_id="C",
        outcome=side,
        connection_id="A",
        received_at=(AT + timedelta(seconds=seconds)).isoformat(),
        bid=0.93,
        ask=0.95,
        spread=0.02,
        bid_depth=100.0,
        ask_depth=200.0,
        bid_quantity=100.0,
        ask_quantity=200.0,
        state="VALID_TWO_SIDED_BOOK",
    )
    d.update(updates)
    return d


@pytest.mark.parametrize(
    "update,state",
    [
        (dict(gap=True), "RECONNECT_GAP"),
        (dict(mapping_verified=False), "INVALID_TOKEN_MAPPING"),
        (dict(complete=False), "UNKNOWN_STATE"),
        (dict(received_at="not-a-time"), "INCONSISTENT_BOOK"),
        (dict(received_at="2026-10-31T08:58:33"), "INCONSISTENT_BOOK"),
        (dict(received_at=(AT + timedelta(seconds=1)).isoformat()), "INCONSISTENT_BOOK"),
        (dict(received_at=(AT - timedelta(seconds=11)).isoformat()), "STALE_BOOK"),
    ],
)
def test_book_status(update, state):
    b = dict(
        complete=True,
        received_at=AT.isoformat(),
        bids=[dict(price=".93", size="10")],
        asks=[dict(price=".95", size="10")],
    )
    b.update(update)
    assert book_state(b, AT) == state


def test_missing_side_and_empty_side_are_different():
    b = dict(complete=True, received_at=AT.isoformat(), bids=[])
    assert book_state(b, AT) == "INCONSISTENT_BOOK"
    assert book_state(dict(b, asks=[]), AT) == "VALID_EMPTY_BOOK"
    with pytest.raises(ValueError):
        book_state(b, AT.replace(tzinfo=None))


def test_buffer_causal_order_capacity_and_copy():
    b = RollingBuffer(max_events=2)
    e = dict(token_id="N", source_event_id=1, received_at=AT.isoformat(), bid=0.1)
    assert b.append(e)
    e["bid"] = 0.99
    assert b.window("N", AT)["events"][0]["bid"] == 0.1
    assert not b.append(e)
    assert not b.append(
        dict(e, source_event_id=2, received_at=(AT - timedelta(seconds=1)).isoformat())
    )
    assert b.append(dict(e, source_event_id=2, received_at=(AT + timedelta(seconds=1)).isoformat()))
    assert b.append(dict(e, source_event_id=3, received_at=(AT + timedelta(seconds=2)).isoformat()))
    assert b.window("N", AT + timedelta(seconds=2))["coverage"] == "PARTIAL_CAPACITY"
    assert not b.window("N", AT - timedelta(seconds=1))["events"]
    b.append(dict(e, source_event_id=4, received_at=(AT + timedelta(seconds=400)).isoformat()))
    assert len(b.window("N", AT + timedelta(seconds=400))["events"]) == 1


@pytest.mark.parametrize(
    "field,before,after,kind",
    [
        ("bid", 0.2, 0.8, "BID_SURGE"),
        ("ask", 0.3, 0.7, "ASK_SURGE"),
        ("bid", 0.8, 0.2, "BID_COLLAPSE"),
        ("ask", 0.7, 0.3, "ASK_COLLAPSE"),
        ("bid_depth", 500.0, 100.0, "LIQUIDITY_WITHDRAWAL"),
        ("ask_depth", 0.0, 200.0, "LIQUIDITY_APPEARANCE"),
        ("spread", 0.2, 0.01, "SPREAD_COMPRESSION"),
        ("spread", 0.01, 0.2, "SPREAD_EXPANSION"),
    ],
)
def test_detector_kinds(field, before, after, kind):
    a = quote(**{field: before})
    b = quote(seconds=1, **{field: after})
    assert any(e["kind"] == kind for e in detect_changes(a, b))


def test_detector_rejects_future_order_and_unknown_prices():
    assert not detect_changes(quote(), quote(seconds=-1, bid=0.1))
    assert not detect_changes(quote(), quote(seconds=6, bid=0.1))
    assert not detect_changes(quote(), quote(seconds=1, connection_id="other", bid=0.1))
    assert not detect_changes(quote(bid=None), quote(seconds=1, bid=0.99))
    assert not detect_changes(quote(bid=float("nan")), quote(seconds=1, bid=0.99))


def test_liquidity_is_never_a_fill_or_arbitrage_proof():
    d = liquidity_paths(quote(bid=0.97, ask=0.98), quote("yes", bid=0.05, ask=0.07), AT.isoformat())
    assert d["classification"] == "THEORETICAL_COMPLEMENT_ONLY"
    assert d["net_profit"] is None and d["supported_fill_quantity"] is None
    assert d["apparent_crossed_complement"] is True
    assert (
        liquidity_paths(quote(bid=0.99, ask=0.95), quote("yes"), AT.isoformat())["classification"]
        == "INSUFFICIENT_DATA"
    )
    assert (
        liquidity_paths(quote(ask=None), quote("yes", bid=None), AT.isoformat())["classification"]
        == "NO_EXECUTABLE_PATH"
    )
    for bad in (
        quote("yes", seconds=1),
        quote("yes", condition_id="D"),
        quote("yes", connection_id="B"),
        quote("no"),
    ):
        assert (
            liquidity_paths(quote(), bad, AT.isoformat())["classification"] == "INSUFFICIENT_DATA"
        )
    assert (
        liquidity_paths(quote(), quote("yes", seconds=-2), AT.isoformat())["classification"]
        == "INSUFFICIENT_DATA"
    )


def test_delayed_receipt_and_same_trade_dont_prove_surge_cause():
    surge = dict(condition_id="C", received_at=AT.isoformat())
    t = dict(
        condition_id="C",
        side="BUY",
        outcome="No",
        evidence_class="PROSPECTIVE_POLL",
        trade_id="T",
        source_trade_timestamp=(AT - timedelta(seconds=1)).isoformat(),
        first_collector_receipt_utc=(AT + timedelta(seconds=2)).isoformat(),
    )
    assert not associate(surge, [t], AT.isoformat())["detection_following_trade_ids"]
    joined = associate(surge, [t, t], (AT + timedelta(seconds=3)).isoformat())
    assert (
        joined["detection_following_trade_ids"] == ["T"]
        and not joined["source_clock_following_trade_ids"]
    )
    assert joined["independent_causality_proven"] is False
    assert not associate(
        surge,
        [dict(t, evidence_class="HISTORICAL_BACKFILL")],
        (AT + timedelta(seconds=300)).isoformat(),
    )["source_clock_following_trade_ids"]


def test_observed_wellington_transaction_order_and_mint():
    f = json.loads(
        (Path(__file__).parent / "fixtures/wellington_surge_observed.json").read_text(
            encoding="utf-8"
        )
    )
    assert f["fixture_kind"] == "OBSERVED_PUBLIC_DATA_NOT_SYNTHETIC"
    proofs = [p for e in f["rpc_envelopes"] for p in decode_v2_receipt(e)]
    assert {p["side"] for p in proofs} == {"BUY", "SELL"}
    assert all(p["quantity"] == "207.78" and p["role"] == "CHAIN_VERIFIED_TAKER" for p in proofs)
    buy = next(p for p in proofs if p["side"] == "BUY")
    message = f["messages"][0]
    original = match_public_trade(
        message["envelope"]["text"], buy["transaction_hash"], buy["token_id"]
    )
    assert original is not None and original["size"] == "207.78"
    assert message["received_at"] < f["messages"][1]["received_at"]
    emitted = []
    _normalize_message(
        message["envelope"]["text"], "test", AT, lambda k, p, t, key: emitted.append((k, p))
    )
    assert emitted[0][1]["transaction_hash"] == buy["transaction_hash"]
    assert emitted[0][1]["wallet_attribution"] == "UNAVAILABLE"
    assert not match_public_trade(
        "[" + message["envelope"]["text"] + "," + message["envelope"]["text"] + "]",
        buy["transaction_hash"],
        buy["token_id"],
    )


@pytest.mark.parametrize("stable,expected", [(0, [3.0, 3.0, 3.0]), (60, [3.0, 6.0, 12.0])])
async def test_reconnect_backoff_does_not_reset_after_short_session(monkeypatch, stable, expected):
    from premetar.research import trader_stream as module

    stop = asyncio.Event()
    delays = []

    class Socket:
        async def send(self, message):
            pass

        async def recv(self):
            raise OSError("SYNTHETIC_TEST_ONLY")

    class Connection:
        async def __aenter__(self):
            return Socket()

        async def __aexit__(self, *args):
            return None

    async def pause(event, seconds):
        delays.append(seconds)
        if len(delays) == 3:
            event.set()

    monkeypatch.setattr(module, "connect", lambda *args, **kwargs: Connection())
    monkeypatch.setattr(module, "_pause", pause)
    await _stream_market(lambda: ["N", "Y"], lambda *args: None, stop, stable)
    assert delays == expected


def test_surge_observer_stale_state_gap_and_restart(tmp_path):
    store = BattleStore(tmp_path, min_free_bytes=0)
    try:
        m = SurgeMonitor(store, tmp_path / "absent")
        m.state["markets"] = {"C": dict(condition_id="C", tokens=dict(no="N", yes="Y"))}
        row = dict(
            id=1,
            kind="BOOK",
            received_at=AT.isoformat(),
            payload=dict(
                token_id="N",
                complete=True,
                source="WS_FULL_SNAPSHOT",
                connection_id="A",
                bids=[dict(price=".1", size="10")],
                asks=[],
            ),
        )
        m.ingest(row, AT)
        assert m.quote("N", AT + timedelta(seconds=11))["state"] == "STALE_BOOK"
        m.ingest(
            dict(
                id=2,
                kind="STREAMHEALTH",
                received_at=AT.isoformat(),
                payload=dict(state="RECONNECTING"),
            ),
            AT,
        )
        assert m.quote("N", AT)["state"] == "RECONNECT_GAP"
        store.commit([], m.state, m.cursors, AT)
        restarted = SurgeMonitor(store, tmp_path / "absent")
        assert restarted.quote("N", AT)["state"] == "NO_INITIAL_SNAPSHOT"
        assert store.connection.execute("pragma integrity_check").fetchone()[0] == "ok"
    finally:
        store.close()


def test_arrival_review_never_uses_decision_time_book_as_later_fill(tmp_path):
    store = BattleStore(tmp_path, min_free_bytes=0)
    try:
        m = SurgeMonitor(store, tmp_path / "absent")
        m.state["markets"] = {"C": dict(condition_id="C", tokens=dict(no="N", yes="Y"))}
        for identity, token in enumerate(("N", "Y"), 1):
            m.ingest(
                dict(
                    id=identity,
                    kind="BOOK",
                    received_at=AT.isoformat(),
                    payload=dict(
                        token_id=token,
                        complete=True,
                        source="WS_FULL_SNAPSHOT",
                        connection_id="A",
                        bids=[dict(price=".93", size="10")],
                        asks=[dict(price=".95", size="10")],
                    ),
                ),
                AT,
            )
        m.state["surge_arrivals"] = [
            dict(surge_id="S", condition_id="C", received_at=AT.isoformat(), remaining=[0.1])
        ]
        assert not any(
            e["kind"] == "SURGE_ARRIVAL_REVIEW" for e in m.followups(AT + timedelta(seconds=0.5))
        )
        review = next(
            e["payload"]
            for e in m.followups(AT + timedelta(seconds=11))
            if e["kind"] == "SURGE_ARRIVAL_REVIEW"
        )
        assert review["feasibility"]["reason"] == "NO_RECORDED_PAIR_AFTER_MODELED_ARRIVAL"
        assert review["supported_fill_quantity"] is None and review["net_profit"] is None
    finally:
        store.close()


async def test_capture_cancellation_preserves_checkpoint_and_releases_lock(tmp_path, monkeypatch):
    from premetar.research import entry_reconstruction_capture as module
    from premetar.research.battle_store import read_battle
    from premetar.research.trader_store import TraderStore

    source = tmp_path / "source.sqlite3"
    s = TraderStore(source)
    s.append(
        "MARKET",
        dict(
            conditionId="C",
            active=True,
            closed=False,
            acceptingOrders=True,
            slug="highest-temperature-in-warsaw-on-november-1-2026-10c",
            clobTokenIds='["Y","N"]',
            outcomes='["Yes","No"]',
            outcomePrices='["0.05","0.95"]',
            description="Warsaw Chopin Airport (EPWA)",
        ),
        datetime.now(UTC) - timedelta(seconds=1),
    )
    s.close()
    ready = asyncio.Event()

    async def stream(tokens, emit, stop):
        ready.set()
        await stop.wait()

    monkeypatch.setattr(module, "stream_market", stream)
    task = asyncio.create_task(
        module.capture(10, tmp_path / "capture", source, tmp_path / "absent")
    )
    await asyncio.wait_for(ready.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not (tmp_path / "capture/monitor.lock").exists()
    assert any(e["kind"] == "CAPTURE_INTERRUPTED" for e in read_battle(tmp_path / "capture"))
