"""Auxiliary EXP0018 tests proposed by the local worker."""

from datetime import UTC, datetime

import pytest

from premetar.research.entry_reconstruction_books import BookRing
from premetar.research.entry_reconstruction_clocks import elapsed_seconds
from premetar.research.entry_reconstruction_features import snapshot_features


def _make_row(**kw):
    defaults = {
        "id": 1,
        "received_at": "2026-01-01T00:00:00+01:00",
        "payload": {
            "token_id": "ABC",
            "complete": True,
            "bids": [{"price": "0.92", "size": "10"}],
            "asks": [{"price": "0.94", "size": "5"}],
            "connection_id": "epoch",
            "source": "WS_FULL_SNAPSHOT",
        },
    }
    defaults.update(kw)
    return defaults


class TestElapsedSeconds:
    def test_utc_normal(self):
        later = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        earlier = datetime(2026, 1, 1, 11, 0, 0, tzinfo=UTC)
        assert elapsed_seconds(later, earlier) == pytest.approx(3600.0)

    def test_rejects_naive(self):
        later = datetime(2026, 1, 1, 12, 0, 0)
        earlier = datetime(2026, 1, 1, 11, 0, 0)
        with pytest.raises(ValueError):
            elapsed_seconds(later, earlier)

    def test_rejects_mixed(self):
        later = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        earlier = datetime(2026, 1, 1, 11, 0, 0)
        with pytest.raises(ValueError):
            elapsed_seconds(later, earlier)

    def test_negative(self):
        later = datetime(2026, 1, 1, 11, 0, 0, tzinfo=UTC)
        earlier = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        assert elapsed_seconds(later, earlier) == pytest.approx(-3600.0)


class TestBookRing:
    def test_add_and_latest(self):
        ring = BookRing(max_tokens=4, max_states=180)
        row = _make_row(id=1, received_at="2026-01-01T00:00:00+01:00")
        assert ring.add(row) is True
        res = ring.latest("ABC", datetime.fromisoformat("2026-01-01T00:00:01+01:00"))
        assert res is not None
        assert res["source_event_id"] == 1

    def test_reject_future(self):
        ring = BookRing()
        row = _make_row(id=1, received_at="2030-01-01T00:00:00+01:00")
        assert ring.add(row) is True
        res = ring.latest("ABC", datetime.fromisoformat("2026-01-01T00:00:00+01:00"))
        assert res is None

    def test_duplicate_id_rejected(self):
        ring = BookRing()
        row = _make_row(id=1)
        assert ring.add(row) is True
        assert ring.add(row) is False

    def test_max_states_eviction(self):
        ring = BookRing(max_tokens=1, max_states=2)
        for i in range(5):
            row = _make_row(id=i + 1, received_at=f"2026-01-01T00:00:{i:02d}+01:00")
            ring.add(row)
        res = ring.latest("ABC", datetime.fromisoformat("2026-01-01T00:00:05+01:00"))
        assert res is not None
        assert res["source_event_id"] == 5

    def test_empty_book_is_not_a_fill(self):
        row = _make_row(
            id=1,
            payload={
                "token_id": "ABC",
                "complete": True,
                "bids": [],
                "asks": [],
                "connection_id": "epoch",
                "source": "WS_FULL_SNAPSHOT",
            },
        )
        ring = BookRing()
        assert ring.add(row) is True

    def test_epoch_clear(self):
        ring = BookRing()
        row = _make_row(id=1)
        ring.add(row)
        ring.invalidate(token="ABC")
        res = ring.latest("ABC", datetime.fromisoformat("2026-01-01T00:00:01+01:00"))
        assert res is None

    def test_explicit_invalidate(self):
        ring = BookRing()
        row = _make_row(id=1)
        ring.add(row)
        ring.invalidate(token="ABC")
        assert ring.latest("ABC", datetime.fromisoformat("2026-01-01T00:00:01+01:00")) is None

    def test_window(self):
        ring = BookRing()
        for i in range(3):
            row = _make_row(id=i + 1, received_at=f"2026-01-01T00:00:{i:02d}+01:00")
            ring.add(row)
        wins = ring.window("ABC", datetime.fromisoformat("2026-01-01T00:00:05+01:00"))
        assert len(wins) == 3

    def test_caps(self):
        ring = BookRing(max_tokens=1, max_states=1)
        row = _make_row(id=1)
        ring.add(row)
        # Second token should be allowed if token count allows
        row2 = _make_row(
            id=2,
            payload={
                "token_id": "DEF",
                "complete": True,
                "bids": [{"price": "0.92", "size": "10"}],
                "asks": [{"price": "0.94", "size": "5"}],
                "connection_id": "epoch",
                "source": "WS_FULL_SNAPSHOT",
            },
        )
        assert ring.add(row2) is True

    def test_max_age_cutoff(self):
        ring = BookRing()
        row = _make_row(id=1, received_at="2026-01-01T00:00:00+01:00")
        ring.add(row)
        res = ring.latest("ABC", datetime.fromisoformat("2026-01-01T00:00:00+01:00"), max_age=10)
        assert res is not None
        # Older than 10 seconds
        res = ring.latest("ABC", datetime.fromisoformat("2026-01-01T00:01:00+01:00"), max_age=10)
        assert res is None


class TestSnapshotFeatures:
    def test_normal_snapshot(self):
        snap = _make_row()
        feats = snapshot_features(snap["payload"])
        assert feats["bid"] == 0.92
        assert feats["ask"] == 0.94
        assert feats["mid"] == pytest.approx(0.93)
        assert feats["spread"] == pytest.approx(0.02)
        assert feats["imbalance"] is not None
        assert feats["bid_depth"] == 10
        assert feats["ask_depth"] == 5

    def test_none_input(self):
        feats = snapshot_features(None)
        for k in ["bid", "ask", "mid", "spread", "imbalance", "bid_depth", "ask_depth"]:
            assert feats[k] is None

    def test_empty_bids_asks(self):
        snap = _make_row(
            payload={
                "token_id": "ABC",
                "complete": True,
                "bids": [],
                "asks": [],
                "connection_id": "epoch",
                "source": "WS_FULL_SNAPSHOT",
            }
        )
        feats = snapshot_features(snap["payload"])
        assert feats["bid"] is None
        assert feats["ask"] is None
