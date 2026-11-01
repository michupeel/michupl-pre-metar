"""Synthetic helper tests for EXP0018.1."""

from datetime import UTC, datetime, timedelta

from premetar.research.surge_associations import associate
from premetar.research.surge_detector import detect_changes
from premetar.research.surge_states import book_state

at = datetime(2026, 10, 31, 8, 58, 33, tzinfo=UTC)


def test_book_state_valid_one_sided():
    data = {
        "complete": True,
        "mapping_verified": True,
        "received_at": at.isoformat(),
        "bids": [{"price": ".99", "size": "10"}],
        "asks": [],
    }
    assert book_state(data, at) == "VALID_ONE_SIDED_BOOK"


def test_book_state_empty():
    data = {
        "complete": True,
        "mapping_verified": True,
        "received_at": at.isoformat(),
        "bids": [],
        "asks": [],
    }
    assert book_state(data, at) == "VALID_EMPTY_BOOK"


def test_book_state_no_snapshot():
    assert book_state(None, at) == "NO_INITIAL_SNAPSHOT"


def test_detect_changes_bid_surge():
    before = {
        "token_id": "N",
        "connection_id": "S",
        "received_at": at.isoformat(),
        "bid": 0.1,
        "ask": None,
    }
    after = dict(before)
    after["received_at"] = (at + timedelta(seconds=1)).isoformat()
    after["bid"] = 0.99
    events = detect_changes(before, after)
    assert any(e.get("kind") == "BID_SURGE" for e in events)
    surge_event = [e for e in events if e.get("kind") == "BID_SURGE"][0]
    delta = surge_event.get("delta", 0)
    assert abs(delta - 0.89) < 1e-6


def test_detect_changes_different_connection():
    before = {
        "token_id": "N",
        "connection_id": "S",
        "received_at": at.isoformat(),
        "bid": 0.1,
        "ask": None,
    }
    after = dict(before)
    after["connection_id"] = "X"
    events = detect_changes(before, after)
    assert events == []


def test_associate_no_entry_delay():
    snap = {"condition_id": "C", "received_at": at.isoformat()}
    events = []
    result = associate(snap, events, (at + timedelta(seconds=300)).isoformat())
    assert result["no_entry_proven"] is False
    assert result["status"] == "NO_ENTRY_OBSERVED_DELAY_CENSOR_REMAINS"
