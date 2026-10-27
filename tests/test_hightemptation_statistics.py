"""Synthetic accounting denominators and uncertainty; no market data generated."""

import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest

from scripts.research.hightemptation_tmax_limit_exit import (  # noqa: E402
    aggregate,
    closure_summary,
    cluster_interval,
    run,
)


def lot(closed: bool, day: int = 0) -> dict:
    return {
        "fully_closed": closed,
        "holding_seconds": 5 if closed else None,
        "buy_size": Decimal(100),
        "matched_quantity": Decimal(100 if closed else 20),
        "close_quantity_by_5s": Decimal(100 if closed else 20),
        "close_quantity_by_10s": Decimal(100 if closed else 20),
        "close_quantity_by_30s": Decimal(100 if closed else 20),
        "close_quantity_by_60s": Decimal(100 if closed else 20),
        "source_trade_timestamp": (
            datetime(2026, 10, 1, tzinfo=UTC) + timedelta(days=day)
        ).isoformat(),
    }


def test_open_lot_remains_in_count_and_volume_denominators() -> None:
    result = closure_summary([lot(True), lot(False)])
    assert result["5"]["fraction_of_all_eligible"] == 0.5
    assert result["5"]["fraction_of_closed"] == 1
    assert result["5"]["share_quantity_closed_fraction"] == 0.6
    assert result["not_fully_closed"] == 1
    assert result["verified_opening_balances"] == 0


def test_empty_and_small_day_counts_do_not_invent_uncertainty() -> None:
    assert closure_summary([])["5"]["fraction_of_all_eligible"] is None
    assert cluster_interval([lot(True)], 5)["low"] is None


def test_day_block_uncertainty_is_deterministic_not_independent_fill_bootstrap() -> None:
    rows = [lot(i % 2 == 0, i) for i in range(20)]
    one = cluster_interval(rows, 5)
    two = cluster_interval(rows, 5)
    assert one == two
    assert one["days"] == 20 and one["low"] <= 0.5 <= one["high"]


def test_partial_realized_gross_is_retained_but_not_full_cost_profit() -> None:
    row = {
        **lot(False),
        "primary_eligible": True,
        "gross_pnl": Decimal("-1"),
        "matched_cost": Decimal(18),
        "inventory_exposure_unclosed_cost": Decimal(72),
        "buy_notional": Decimal(90),
        "buy_price": Decimal(".9"),
        "buy_role": "UNKNOWN",
        "after_exchange_fee_pnl": None,
        "quantity_time_sum": Decimal(100),
        "return_on_matched_capital_gross": None,
    }
    result = aggregate([row])
    assert result["gross_pnl"] is None
    assert result["partial_lots_matched_gross_pnl"] == -1
    assert result["all_matched_gross_pnl"] == -1
    assert result["net_pnl"] is None and result["unclosed_ledger_cost"] == 72


def test_case_specific_report_refuses_unrelated_snapshot(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps({"sources": {"trader": {"sha256": "another"}, "weather": {"sha256": "another"}}})
    )
    with pytest.raises(ValueError, match="frozen study"):
        run(tmp_path, tmp_path / "reports")
