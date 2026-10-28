"""Synthetic matched-control clocks; no control quote is called an own fill."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from premetar.research.battle_controls import MAX_CONTROLS, VERSION, ControlTracker

AT = datetime(2026, 10, 28, 11, 29, tzinfo=UTC)


def event(order_id: str = "o1", **extra: Any) -> dict[str, Any]:
    return dict(
        kind="BUY_SUBMITTED",
        at=AT.isoformat(),
        payload=dict(
            family=extra.pop("family", "SIMPLE"),
            mode="TAKER",
            order=dict(
                id=order_id,
                limit=".95",
                quantity="5",
                token_id="no",
                condition_id="c",
                day="2026-10-28",
                created_at=AT.isoformat(),
            ),
            **extra,
        ),
    )


def book(at: datetime, **extra: Any) -> dict[str, Any]:
    return dict(
        status="VALID",
        token_id="no",
        market="c",
        connection_id="epoch1",
        received_at=at.isoformat(),
        bids=[dict(price=".94", size="10")],
        asks=[dict(price=".95", size="10")],
        **extra,
    )


def random_due(tracker: ControlTracker, order_id: str = "o1") -> datetime:
    return datetime.fromisoformat(tracker.state["controls"][order_id]["random_due"])


def test_annotation_is_frozen_seed_and_windows_not_entry_rules() -> None:
    a, b = ControlTracker(), ControlTracker()
    peak = dict(time=(AT + timedelta(minutes=45)).isoformat())
    first, second = a.register(event(), peak, AT), b.register(event(), peak, AT)
    assert first == second
    annotation = first[0]["payload"]
    assert annotation["seed"] == 20261028
    assert 0 <= annotation["random_delay_seconds"] <= 60
    assert annotation["flags"]["within_nominal_metar_window"]
    assert annotation["flags"]["within_forecast_tmax_window"]
    assert annotation["flags"]["policy"] == "ANNOTATIONS_ONLY_NEVER_SIMPLE_ENTRY_GATES"


@pytest.mark.parametrize("family", ["HYBRID", "SIMPLE_98_CONTROL", "WEATHER"])
def test_nonprimary_families_not_registered(family: str) -> None:
    assert ControlTracker().register(event(family=family), None, AT) == []


@pytest.mark.parametrize("price", [".91", ".98", ".99"])
def test_strict_primary_boundaries_not_expanded(price: str) -> None:
    e = event()
    e["payload"]["order"]["limit"] = price
    assert ControlTracker().register(e, None, AT) == []


def test_first_random_book_matches_without_creating_orders_or_fills() -> None:
    tracker = ControlTracker()
    tracker.register(event(), None, AT)
    due = random_due(tracker)
    result = tracker.observe("c", book(due), due)
    matches = [row for row in result if row["kind"] == "CONTROL_MATCH"]
    assert len(matches) == 1
    assert matches[0]["payload"]["execution_claim"] == "DISPLAYED_MATCH_NOT_EXECUTION"
    assert not any("FILL" in row["kind"] or "SUBMITTED" in row["kind"] for row in result)
    assert not [
        row for row in tracker.observe("c", book(due), due) if row["kind"] == "CONTROL_MATCH"
    ]


@pytest.mark.parametrize(
    "bad", ["old", "future", "stale", "wrong_token", "wrong_condition", "invalid"]
)
def test_no_future_old_stale_wrong_identity_books(bad: str) -> None:
    tracker = ControlTracker()
    tracker.register(event(), None, AT)
    due = random_due(tracker)
    current = book(due)
    if bad == "old":
        current["received_at"] = (due - timedelta(seconds=1)).isoformat()
    elif bad == "future":
        current["received_at"] = (due + timedelta(seconds=1)).isoformat()
    elif bad == "stale":
        current["received_at"] = (due - timedelta(seconds=6)).isoformat()
    elif bad == "wrong_token":
        current["token_id"] = "yes"
    elif bad == "wrong_condition":
        current["market"] = "another"
    else:
        current["status"] = "STALE_BOOK"
    assert not [row for row in tracker.observe("c", current, due) if row["kind"] == "CONTROL_MATCH"]
    result = tracker.observe("c", current, due + timedelta(seconds=3))
    assert any(row["kind"] == "CONTROL_UNMATCHED" for row in result)


@pytest.mark.parametrize("bad", ["price", "liquidity"])
def test_unmatched_first_quote_is_not_resampled_until_favorable(bad: str) -> None:
    tracker = ControlTracker()
    tracker.register(event(), None, AT)
    due = random_due(tracker)
    current = book(due)
    current["asks"] = [
        dict(price=".97" if bad == "price" else ".95", size="1" if bad == "liquidity" else "10")
    ]
    result = tracker.observe("c", current, due)
    assert any(row["kind"] == "CONTROL_UNMATCHED" for row in result)
    assert not any(
        row["kind"] == "CONTROL_MATCH"
        for row in tracker.observe(
            "c", book(due + timedelta(seconds=1)), due + timedelta(seconds=1)
        )
    )


def test_horizon_captures_original_book_clock_and_liquidity_not_fill() -> None:
    tracker = ControlTracker()
    tracker.register(event(), None, AT)
    at = AT + timedelta(seconds=5)
    current = book(at)
    current["bids"] = [dict(price=".99", size="6")]
    current["asks"] = []
    capture = next(
        row for row in tracker.observe("c", current, at) if row["kind"] == "CONTROL_HORIZON"
    )
    assert capture["payload"]["horizon_seconds"] == 5
    assert capture["payload"]["exit99_visible_enough"]
    assert capture["payload"]["book_received_at"] == at.isoformat()
    assert capture["payload"]["execution_claim"] == "VISIBLE_QUOTES_NOT_SUPPORTED_OWN_FILL"


def test_horizon_deadline_miss_is_retained_not_backdated() -> None:
    tracker = ControlTracker()
    tracker.register(event(), None, AT)
    later = AT + timedelta(seconds=8)
    result = tracker.observe("c", book(later), later)
    row = next(r for r in result if r["kind"] == "CONTROL_HORIZON_UNRESOLVED")
    assert row["payload"]["horizon_seconds"] == 5
    assert tracker.state["controls"]["o1"]["horizons"]["5"]["status"] == "UNRESOLVED"


def test_restart_preserves_pending_and_completed_dedup() -> None:
    tracker = ControlTracker()
    tracker.register(event(), None, AT)
    due = random_due(tracker)
    tracker.observe("c", book(due), due)
    checkpoint = deepcopy(tracker.state)
    restored = ControlTracker(checkpoint)
    assert restored.register(event(), None, due + timedelta(seconds=1)) == []
    assert not any(r["kind"] == "CONTROL_MATCH" for r in restored.observe("c", book(due), due))
    assert checkpoint == tracker.state


def test_capacity_fails_explicitly_instead_of_unbounded_or_forgetting_identity() -> None:
    tracker = ControlTracker()
    for i in range(MAX_CONTROLS):
        tracker.register(event(f"o{i}"), None, AT)
    result = tracker.register(event("excess"), None, AT)
    assert result[0]["kind"] == "CONTROL_BACKPRESSURE"
    assert len(tracker.state["controls"]) == MAX_CONTROLS
    assert tracker.register(event("o0"), None, AT) == []


def test_unknown_future_peak_and_outside_windows_remain_unknown() -> None:
    at = AT.replace(minute=15)
    e = event()
    e["at"] = e["payload"]["order"]["created_at"] = at.isoformat()
    result = ControlTracker().register(
        e, dict(time=at.isoformat(), first_received=(at + timedelta(seconds=1)).isoformat()), at
    )
    flags = result[0]["payload"]["flags"]
    assert flags["within_forecast_tmax_window"] is None
    assert not flags["within_nominal_metar_window"]


def test_bad_checkpoint_and_naive_clock_rejected() -> None:
    with pytest.raises(ValueError):
        ControlTracker(dict(version="other", seed=20261028, controls={}))
    with pytest.raises(ValueError):
        ControlTracker(dict(version=VERSION, seed=1, controls={}))
    with pytest.raises(ValueError):
        ControlTracker().observe("c", {}, AT.replace(tzinfo=None))
