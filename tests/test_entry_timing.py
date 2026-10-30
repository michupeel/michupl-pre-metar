"""Synthetic boundary cases, not empirical trader outcomes."""

from datetime import UTC, datetime

import pytest

from premetar.research.entry_timing import (
    cadence,
    deduplicate,
    execution_key,
    phase_contrast,
    price_bucket,
    receipt_context,
    schedule_offsets,
    summarize,
    timing_bin,
    utc,
)


@pytest.mark.parametrize(
    ("price", "bucket"),
    [
        (".89999", "BELOW_0.90"),
        (".90", "0.90_TO_0.95_INCLUSIVE"),
        (".95", "0.90_TO_0.95_INCLUSIVE"),
        (".95001", "ABOVE_0.95_BELOW_0.98"),
        (".9799999999", "ABOVE_0.95_BELOW_0.98"),
        (".980000", "EXACT_0.98"),
        (".9800000001", "ABOVE_0.98_BELOW_0.99"),
        (".99", "EXACT_0.99"),
        (".999", "ABOVE_0.99"),
    ],
)
def test_exact_price_partitions(price: str, bucket: str) -> None:
    assert price_bucket(price) == bucket


@pytest.mark.parametrize("price", ["NaN", "Infinity", "0", "1", "-1"])
def test_invalid_price(price: str) -> None:
    with pytest.raises(ValueError):
        price_bucket(price)


@pytest.mark.parametrize(
    ("seconds", "bucket"),
    [
        (-301, "<-5m"),
        (-300, "[-5m,-3m)"),
        (-180, "[-3m,-1m)"),
        (-60, "[-60s,-30s)"),
        (-30, "[-30s,0s)"),
        (0, "[0s,30s)"),
        (30, "[30s,60s)"),
        (60, "[1m,3m)"),
        (180, "[3m,5m)"),
        (300, ">=5m"),
    ],
)
def test_exclusive_offset_bins(seconds: int, bucket: str) -> None:
    assert timing_bin(seconds) == bucket


def test_month_rollover_and_tie_earlier() -> None:
    at = utc("2026-11-01T00:05:00Z")
    result = schedule_offsets(at, [20, 50])
    assert result["previous_nominal"] == "2026-10-31T23:50:00+00:00"
    assert result["next_nominal"] == "2026-11-01T00:20:00+00:00"
    assert result["nearest_offset_seconds"] == 900
    assert utc("2026-10-25T02:30:00+02:00") != utc("2026-10-25T02:30:00+01:00")
    with pytest.raises(ValueError):
        utc("2026-10-25T02:30:00")


def test_missing_schedule() -> None:
    assert schedule_offsets(datetime.now(UTC), [])["nearest_offset_seconds"] is None


def test_cadence_does_not_count_corrections_or_speci_as_extra_routine() -> None:
    reports = [
        dict(event_time=f"2026-10-{day:02d}T{hour:02d}:30:00Z", product_type="METAR")
        for day in (24, 25)
        for hour in range(24)
    ]
    reports += reports[:10] + [dict(event_time="2026-10-24T12:07:00Z", product_type="SPECI")]
    result = cadence(reports)
    assert result["routine_cycles"] == 48
    assert result["minutes"] == [30]
    assert cadence(reports[:4])["minutes"] == []


def test_first_receipt_and_no_future_publication_assumption() -> None:
    base = dict(
        event_time="2026-10-29T12:00:00Z", product_type="METAR", evidence_class="REALTIME_CAPTURED"
    )
    reports = [
        dict(base, collector_receive_time="2026-10-29T11:59:00Z"),
        dict(base, collector_receive_time="2026-10-29T12:02:00Z"),
        dict(base, collector_receive_time="2026-10-29T11:58:00Z", startup_censored=True),
        dict(base, collector_receive_time=None, source_receipt_time="2026-10-29T11:50:00Z"),
    ]
    result = receipt_context(reports, utc("2026-10-29T12:01:00Z"), base["event_time"])
    assert result["first_metar_receipt"] == "2026-10-29T11:59:00+00:00"
    assert result["trade_minus_first_receipt_seconds"] == 120
    assert result["publication_status"] == "PUBLIC_RELEASE_TIME_UNKNOWN"
    later = receipt_context([reports[1]], utc("2026-10-29T12:01:00Z"), base["event_time"])
    assert later["previous_available_metar"] is None


def test_dedup_preserves_first_receipt_and_distinct_execution_groups() -> None:
    old = dict(
        trade_id="a",
        transaction_hash="tx",
        token_id="token",
        side="BUY",
        source_trade_timestamp="2026-10-29T12:00:00Z",
        first_collector_receipt_utc="2026-10-29T12:01:00Z",
    )
    newer = dict(old, first_collector_receipt_utc="2026-10-29T12:02:00Z")
    another_fill = dict(old, trade_id="b")
    rows = deduplicate([newer, old, another_fill])
    assert len(rows) == 2
    assert rows[0]["first_collector_receipt_utc"] == old["first_collector_receipt_utc"]
    assert execution_key(rows[0]) == execution_key(rows[1])


def test_uniform_phase_is_not_claimed_matched_and_grouped_fill_denominator() -> None:
    rows = [
        dict(
            execution_group=f"tx{i // 2}",
            market_date=f"2026-10-{i // 2 + 1:02d}",
            nearest_offset_seconds=30 if i % 4 == 0 else 300,
            timing_bin=timing_bin(30 if i % 4 == 0 else 300),
            schedule_minutes=[0, 30],
            station="EPWA",
        )
        for i in range(40)
    ]
    result = phase_contrast(rows)
    assert result["independent_executions"] == 20
    assert result["matched_market_activity_status"] == "NOT_IDENTIFIABLE"
    assert result == phase_contrast(rows)
    summary = summarize(rows)
    assert sum(r["count"] for r in summary["hist"]) == 40
    assert summary["percentages"]["within_60s"] == 25
    assert summarize([])["percentages"]["within_60s"] is None
