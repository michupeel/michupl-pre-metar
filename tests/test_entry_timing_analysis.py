"""Regression tests for observed versus projected clocks and exact identity."""

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.research.hightemptation_entry_timing import align_reports, metadata_for  # noqa: E402


def test_actual_report_offsets_replace_every_projected_clock() -> None:
    row: dict[str, Any] = dict(
        source_trade_timestamp="2026-10-22T20:32:05Z",
        previous_nominal="2026-10-22T20:00:00Z",
        next_nominal="2026-10-22T21:00:00Z",
        previous_offset_seconds=1925,
        next_offset_seconds=-1675,
    )
    clocks = [datetime(2026, 10, 22, 20, 30, tzinfo=UTC), datetime(2026, 10, 22, 21, tzinfo=UTC)]
    align_reports(row, [], clocks)
    assert row["nearest_offset_seconds"] == row["previous_offset_seconds"] == 125
    assert row["next_offset_seconds"] == -1675
    assert row["publication_status"] == "PUBLIC_RELEASE_TIME_UNKNOWN"
    align_reports(row, [], [])
    assert row["nearest_offset_seconds"] is None
    assert row["previous_offset_seconds"] is None
    assert row["next_offset_seconds"] is None


def test_exact_nominal_time_has_zero_previous_and_next_offset() -> None:
    row: dict[str, Any] = dict(source_trade_timestamp="2026-10-22T20:30:00Z")
    align_reports(
        row,
        [],
        [datetime(2026, 10, 22, 20, tzinfo=UTC), datetime(2026, 10, 22, 20, 30, tzinfo=UTC)],
    )
    assert row["previous_offset_seconds"] == row["next_offset_seconds"] == 0


def test_metadata_requires_exact_token_not_just_condition(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "scripts.research.hightemptation_entry_timing.load_market_metadata", lambda p: {}
    )
    trade = dict(
        token_id="123",
        condition_id="0xabc",
        slug="highest-temperature-in-warsaw-on-october-22-2026-14c",
    )
    market = dict(
        conditionId="0xabc",
        clobTokenIds='["999","998"]',
        resolutionSource="https://aviationweather.gov/api/data/metar?ids=EPWA",
        description="Warsaw local time",
    )
    result = metadata_for(
        [trade], dict(markets=[dict(market=market, received_at="2026-10-29T20:00:00Z")])
    )
    assert result["123"]["reference_station"] is None
    assert result["123"]["timezone"] == "Europe/Warsaw"
