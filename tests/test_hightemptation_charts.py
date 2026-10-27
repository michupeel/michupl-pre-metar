"""Synthetic CSV chart fixtures, never evidence about the monitored wallet."""

import csv
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "hightemptation_charts", Path(__file__).parents[1] / "scripts/research/hightemptation_charts.py"
)
assert _spec is not None and _spec.loader is not None
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
render = _module.render
holding_series = _module.holding_series
local_hours = _module.local_hours


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_empty_exports_produce_labeled_png_artifacts(tmp_path: Path) -> None:
    paths = render(tmp_path)
    assert len(paths) == 3
    for path in paths:
        assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_holding_series_counts_buy_closures_not_partial_sell_rows() -> None:
    durations, weights, omitted = holding_series(
        [
            {
                "fully_closed": "true",
                "holding_seconds": "6",
                "matched_quantity": "20",
                "status": "CONDITIONAL_FIFO",
            },
            {"fully_closed": "false", "holding_seconds": "3", "matched_quantity": "2"},
            {
                "fully_closed": "true",
                "holding_seconds": "0",
                "buy_size": "7",
                "status": "AMBIGUOUS_SAME_SECOND",
            },
            {"fully_closed": "true", "holding_seconds": "NaN", "buy_size": "7"},
            {"fully_closed": "true", "holding_seconds": "12", "buy_size": "5"},
        ]
    )
    assert durations == [6, 12]
    assert weights == [20, 5]
    assert omitted == 3


def test_local_hours_keep_both_dst_fallback_instants_and_reject_naive_time() -> None:
    common = {
        "market_kind": "TMAX",
        "timezone": "Europe/Warsaw",
        "temporal_identity_status": "VERIFIED_REFERENCE",
    }
    hours, omitted = local_hours(
        [
            {**common, "local_time": "2026-10-25T02:30:00+02:00"},
            {**common, "local_time": "2026-10-25T02:30:00+01:00"},
            {**common, "local_time": "2026-10-25T02:30:00"},
            {**common, "timezone": "", "local_hour": "14.5"},
            {**common, "temporal_identity_status": "UNKNOWN_TIMEZONE", "local_hour": "14.5"},
        ]
    )
    assert hours["TMAX"] == [2.5, 2.5]
    assert omitted == 3


def test_primary_inventory_exclusions_remain_excluded_from_closure_chart() -> None:
    values, weights, omitted = holding_series(
        [
            {
                "fully_closed": "True",
                "primary_eligible": "False",
                "holding_seconds": "0",
                "matched_quantity": "50",
                "status": "CONDITIONAL_TRADE_ONLY_FIFO",
            },
            {
                "fully_closed": "True",
                "primary_eligible": "True",
                "holding_seconds": "8",
                "matched_quantity": "20",
                "status": "CONDITIONAL_TRADE_ONLY_FIFO",
            },
        ]
    )
    assert values == [8]
    assert weights == [20]
    assert omitted == 1


def test_complete_synthetic_csv_exports_render(tmp_path: Path) -> None:
    write_csv(
        tmp_path / "hightemptation_price_distribution.csv",
        [
            {"price_bucket": "[0.90,0.95)", "buy_count": "2", "shares": "50"},
            {"price_bucket": "[0.98,1.00]", "buy_count": "1", "shares": "10"},
        ],
    )
    write_csv(
        tmp_path / "hightemptation_holding_times.csv",
        [
            {
                "fully_closed": "true",
                "holding_seconds": "6",
                "matched_quantity": "20",
                "status": "CONDITIONAL_FIFO",
            },
            {
                "fully_closed": "true",
                "holding_seconds": "3600",
                "matched_quantity": "10",
                "status": "CONDITIONAL_FIFO",
            },
        ],
    )
    write_csv(
        tmp_path / "hightemptation_tmax_timing.csv",
        [
            {
                "market_kind": "TMAX",
                "timezone": "Europe/London",
                "local_hour": "14.5",
                "temporal_identity_status": "VERIFIED_REFERENCE",
            },
            {
                "market_kind": "TMIN",
                "timezone": "Asia/Tokyo",
                "local_hour": "5.0",
                "temporal_identity_status": "VERIFIED_REFERENCE",
            },
        ],
    )
    paths = render(tmp_path)
    assert all(path.stat().st_size > 10_000 for path in paths)
