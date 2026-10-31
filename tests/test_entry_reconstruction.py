"""Causal/concurrency acceptance tests owned by Codex; no public requests."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from premetar.research.battle_store import BattleStore, read_battle
from premetar.research.entry_reconstruction import (
    Reconstruction,
    settlement_day,
    source_rows,
    watch,
    window_quality,
)
from premetar.research.entry_reconstruction_books import BookRing
from premetar.research.entry_reconstruction_clocks import elapsed_seconds
from premetar.research.entry_reconstruction_controls import match_controls
from premetar.research.entry_reconstruction_features import price_changes
from premetar.research.entry_reconstruction_levels import update_levels
from premetar.research.trader_normalizer import WALLET

AT = datetime(2026, 10, 31, 12, tzinfo=UTC)


def row(identity=1, seconds=0, token="NO", kind="BOOK", **updates):
    payload = dict(
        token_id=token,
        complete=True,
        bids=[dict(price="0.92", size="10")],
        asks=[dict(price="0.94", size="5")],
        connection_id="a",
        source="WS_FULL_SNAPSHOT",
    )
    payload.update(updates)
    return dict(
        id=identity,
        kind=kind,
        received_at=(AT + timedelta(seconds=seconds)).isoformat(),
        payload=payload,
    )


def trade(identity=100, source_offset=10, receipt_offset=12):
    return row(
        identity,
        receipt_offset,
        kind="TRADE",
        trader_wallet=WALLET,
        condition_id="C",
        trade_id=str(identity),
        side="BUY",
        outcome="No",
        price="0.94",
        size="10",
        source_trade_timestamp=(AT + timedelta(seconds=source_offset)).isoformat(),
        first_collector_receipt_utc=(AT + timedelta(seconds=receipt_offset)).isoformat(),
        evidence_class="PROSPECTIVE_POLL",
        slug="highest-temperature-in-warsaw-on-october-31-2026",
    )


def test_dst_fold_preserves_elapsed_time():
    tz = ZoneInfo("Europe/Warsaw")
    early = datetime(2026, 10, 25, 2, 30, tzinfo=tz, fold=0)
    late = datetime(2026, 10, 25, 2, 30, tzinfo=tz, fold=1)
    assert elapsed_seconds(late, early) == 3600


@pytest.mark.parametrize(
    "updates",
    [
        dict(complete=False),
        dict(bids=None),
        dict(asks=[dict(price="NaN", size="1")]),
        dict(bids=[dict(price="0.95", size="1")]),
    ],
)
def test_ring_rejects_invalid_snapshot_without_poisoning_history(updates):
    ring = BookRing()
    assert ring.add(row())
    assert not ring.add(row(2, 1, **updates))
    assert ring.latest("NO", AT)["source_event_id"] == 1


def test_ring_epoch_caps_and_utc_cutoff():
    ring = BookRing(max_tokens=1, max_states=2)
    for n in range(3):
        assert ring.add(row(n + 1, n))
    assert len(ring.window("NO", AT + timedelta(seconds=3))) == 2
    assert ring.add(row(4, 4, connection_id="b"))
    assert len(ring.window("NO", AT + timedelta(seconds=4))) == 1
    assert ring.add(row(5, 5, token="YES"))
    assert ring.latest("NO", AT + timedelta(seconds=5)) is None
    with pytest.raises(ValueError):
        ring.window("YES", AT.replace(tzinfo=None))


def test_price_changes_do_not_use_future_or_forward_nearest():
    ring = BookRing()
    ring.add(row(1, -30))
    ring.add(row(2, -15, bids=[dict(price="0.94", size="1")], asks=[dict(price="0.96", size="1")]))
    ring.add(row(3, 0))
    ring.add(row(4, 1, bids=[dict(price="0.98", size="1")], asks=[dict(price="0.99", size="1")]))
    features = price_changes(ring.window("NO", AT + timedelta(seconds=1)), AT.isoformat())
    assert features["change_15s"] == pytest.approx(-0.02)
    assert features["change_30s"] == pytest.approx(0)
    assert features["reversal_30s"] is True
    assert features["change_60s"] is None
    assert (
        price_changes(
            ring.window("NO", AT + timedelta(seconds=12)), (AT + timedelta(seconds=12)).isoformat()
        )["change_5s"]
        is None
    )


def test_controls_are_causal_finite_same_station_day_and_deduplicated():
    entry = dict(
        condition_id="A",
        station="EPWA",
        settlement_day="2026-10-31",
        received_at=AT.isoformat(),
        price=0.94,
        spread=0.02,
        depth=10.0,
    )
    candidate = dict(entry, condition_id="B")
    candidates = [
        candidate,
        candidate,
        dict(candidate, condition_id="future", received_at=(AT + timedelta(seconds=1)).isoformat()),
        dict(candidate, condition_id="other", station="EGLL"),
        dict(candidate, condition_id="nan", price=float("nan")),
    ]
    selected = match_controls(entry, candidates)
    assert len(selected) == 1 and selected[0]["condition_id"] == "B"
    assert selected[0]["label"] == "PENDING_DELAYED_ATTRIBUTION"
    assert "label" not in candidate
    assert not match_controls(dict(entry, station=None), candidates)


def test_sparse_window_is_never_certified_continuous():
    points = [dict(received_at=(AT - timedelta(seconds=s)).isoformat()) for s in (300, 60, 10, 0)]
    quality = window_quality(points, AT)
    assert quality["window_300s"] == "PARTIAL_OR_MISSING"
    assert quality["continuous_depth_verified"] is False


def test_delta_invalidation_restart_and_no_source_writes(tmp_path):
    store = BattleStore(tmp_path / "journal", min_free_bytes=0)
    try:
        monitor = Reconstruction(store, tmp_path / "absent-weather")
        monitor.ingest(row(), AT)
        assert monitor.book("NO", AT)
        monitor.ingest(
            row(2, 1, kind="WS_DELTA", price_changes=[dict(asset_id="NO")]),
            AT + timedelta(seconds=1),
        )
        assert monitor.book("NO", AT + timedelta(seconds=1)) is None
        monitor.ingest(row(3, 2), AT + timedelta(seconds=2))
        store.commit([], monitor.state, {"source": 3}, AT + timedelta(seconds=2))
        restarted = Reconstruction(store, tmp_path / "absent-weather")
        assert restarted.book("NO", AT + timedelta(seconds=2)) is None
        assert restarted.cursors["source"] == 3
    finally:
        store.close()


def test_entry_dedup_preserves_first_receipts_and_immutability(tmp_path):
    store = BattleStore(tmp_path / "journal", min_free_bytes=0)
    try:
        monitor = Reconstruction(store, tmp_path / "absent")
        monitor.ingest(row(1, 8), AT + timedelta(seconds=8))
        events = monitor.ingest(trade(), AT + timedelta(seconds=12))
        recon = next(e["payload"] for e in events if e["kind"] == "ENTRY_RECONSTRUCTION")
        assert recon["original_first_detection"] == (AT + timedelta(seconds=12)).isoformat()
        assert recon["books"]["no"]["pre_execution"]["ask"] == 0.94
        assert recon["books"]["yes"]["pre_execution"]["ask"] is None
        store.commit(events, monitor.state, {"source": 100}, AT + timedelta(seconds=12))
        assert not monitor.ingest(trade(), AT + timedelta(seconds=15))
        with pytest.raises(sqlite3.DatabaseError):
            store.connection.execute("UPDATE events SET kind='ALTERED'")
        assert store.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert (
            len(
                [
                    e
                    for e in read_battle(tmp_path / "journal")
                    if e["kind"] == "ENTRY_RECONSTRUCTION"
                ]
            )
            == 1
        )
    finally:
        store.close()


def test_readonly_source_tail_skips_raw_and_cold_start(tmp_path):
    path = tmp_path / "source.sqlite3"
    with sqlite3.connect(path) as writer:
        writer.execute(
            "CREATE TABLE events(id INTEGER PRIMARY KEY,kind TEXT,received_at TEXT,payload TEXT)"
        )
        writer.execute(
            "INSERT INTO events VALUES(1,'RAW',?,?)", (AT.isoformat(), "INVALID_JSON_NOT_DECODED")
        )
        writer.execute(
            "INSERT INTO events VALUES(2,'BOOK',?,?)",
            (AT.isoformat(), json.dumps(row()["payload"])),
        )
        writer.commit()
        assert source_rows(path, None) == (2, [])
        cursor, rows = source_rows(path, 0)
        assert cursor == 2 and len(rows) == 1
        writer.execute("INSERT INTO events VALUES(3,'BOOK',?,?)", (AT.isoformat(), "malformed"))
    assert source_rows(path, 2)[1][0]["kind"] == "COVERAGE_GAP"
    assert sqlite3.connect(path).execute("SELECT count(*) FROM events").fetchone()[0] == 3


def test_control_delayed_trade_never_certified_no_entry(tmp_path):
    store = BattleStore(tmp_path / "journal", min_free_bytes=0)
    try:
        monitor = Reconstruction(store, tmp_path / "absent")
        monitor.state["control_pending"] = [
            dict(
                condition_id="B",
                attribution_deadline=(AT + timedelta(seconds=300)).isoformat(),
                matched_at=AT.isoformat(),
            )
        ]
        assert not monitor.control_outcomes(AT + timedelta(seconds=299))
        events = monitor.control_outcomes(AT + timedelta(seconds=300))
        assert events[0]["payload"]["no_entry_proven"] is False
    finally:
        store.close()


@pytest.mark.parametrize(
    "slug,expected",
    [
        ("highest-temperature-in-warsaw-on-october-31-2026-12c", "2026-10-31"),
        ("bad", None),
        ("x-february-31-2026", None),
    ],
)
def test_explicit_settlement_date(slug, expected):
    assert settlement_day(slug) == expected


def test_unbounded_activation_is_not_available():
    with pytest.raises(ValueError):
        watch(3601, Path("never-created"))


def test_absolute_levels_replace_not_add_and_zero_removes():
    levels = [dict(price="0.50", size="10")]
    changed = update_levels(levels, [dict(price=".5", size="3")])
    assert changed == [dict(price="0.50", size="3")]
    assert levels[0]["size"] == "10"
    assert not update_levels(changed, [dict(price="0.5", size="0")])


@pytest.mark.parametrize(
    "price,size", [("NaN", "1"), ("0.5", "NaN"), ("oops", "1"), (".5", "-1"), ("1.1", "1")]
)
def test_invalid_delta_levels_raise_value_error(price, size):
    with pytest.raises(ValueError):
        update_levels([], [dict(price=price, size=size)])


def delta(identity=2, seconds=1, **updates):
    change = dict(
        asset_id="NO", price="0.92", size="3", side="BUY", best_bid="0.92", best_ask="0.94"
    )
    change.update(updates)
    return row(identity, seconds, kind="WS_DELTA", price_changes=[change], connection_id="a")


def test_delta_reconstruction_requires_snapshot_epoch_and_bbo():
    ring = BookRing()
    assert ring.delta(delta()) == 0
    assert ring.add(row())
    assert ring.delta(delta()) == 1
    snapshot = ring.latest("NO", AT + timedelta(seconds=1))
    assert snapshot["bids"][0]["size"] == "3"
    assert snapshot["seed_event_id"] == 1
    assert snapshot["sequence_guarantee"] == "UNAVAILABLE"
    assert ring.delta(delta(3, 2, best_bid="0.91")) == 0
    assert ring.latest("NO", AT + timedelta(seconds=2)) is None


def test_delta_different_epoch_cannot_reuse_old_seed():
    ring = BookRing()
    ring.add(row())
    packet = delta()
    packet["payload"]["connection_id"] = "new"
    assert ring.delta(packet) == 0
    assert ring.latest("NO", AT + timedelta(seconds=1)) is None


def test_post_windows_need_actual_after_target_books(tmp_path):
    store = BattleStore(tmp_path / "journal", min_free_bytes=0)
    try:
        monitor = Reconstruction(store, tmp_path / "absent")
        monitor.ingest(trade(), AT + timedelta(seconds=12))
        assert not monitor.post_windows(AT + timedelta(seconds=19), AT + timedelta(seconds=19))
        events = monitor.ingest(row(101, 21), AT + timedelta(seconds=21))
        post = next(e["payload"] for e in events if e["kind"] == "ENTRY_POST_WINDOW")
        assert post["requested_offset_seconds"] == 10 and post["actual_offset_seconds"] == 11
        assert post["books"]["no"]["received_at"] == (AT + timedelta(seconds=21)).isoformat()
    finally:
        store.close()


def test_cycle_defers_packets_appended_after_cycle_start_without_loss(tmp_path, monkeypatch):
    from premetar.research import entry_reconstruction as module

    store = BattleStore(tmp_path / "journal", min_free_bytes=0)
    try:
        monitor = Reconstruction(store, tmp_path / "absent")
        monitor.cursors["source"] = 0
        monkeypatch.setattr(module, "source_rows", lambda path, after: (1, [row(1, 1)]))
        monitor.cycle(tmp_path / "source", AT)
        assert monitor.cursors["source"] == 0
        assert monitor.book("NO", AT + timedelta(seconds=2)) is None
        monitor.cycle(tmp_path / "source", AT + timedelta(seconds=2))
        assert monitor.cursors["source"] == 1
        assert monitor.book("NO", AT + timedelta(seconds=2)) is not None
    finally:
        store.close()


def test_one_sided_repricing_is_observed_evidence_without_midpoint():
    points = [
        dict(received_at=AT.isoformat(), bids=[dict(price=".1", size="1")], asks=[]),
        dict(
            received_at=(AT + timedelta(seconds=1)).isoformat(),
            bids=[dict(price=".99", size="5")],
            asks=[],
        ),
    ]
    values = price_changes(points, (AT + timedelta(seconds=2)).isoformat())
    assert values["change_5s"] is None
    assert values["largest_adjacent_bid_increase"] == pytest.approx(0.89)
