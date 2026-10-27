import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.research.exp0012_bucket_helpers import price_bucket  # noqa: E402
from scripts.research.hightemptation_inventory import reconstruct  # noqa: E402


def trade(name: str, side: str, seconds: int, size: str, price: str, tx: str | None = None) -> dict:
    return {
        "trade_id": name,
        "transaction_hash": tx or name,
        "token_id": "1",
        "condition_id": "condition",
        "side": side,
        "size": size,
        "price": price,
        "source_trade_timestamp": (
            datetime(2026, 10, 27, tzinfo=UTC) + timedelta(seconds=seconds)
        ).isoformat(),
    }


def test_partial_sell_does_not_close_buy_and_fifo_preserves_cost() -> None:
    lots, matches, sales = reconstruct(
        [
            trade("b", "BUY", 0, "100", ".9"),
            trade("s1", "SELL", 5, "20", ".92"),
            trade("s2", "SELL", 40, "80", ".93"),
        ]
    )
    lot = lots[0]
    assert lot["fully_closed"] and lot["holding_seconds"] == 40
    assert lot["close_quantity_by_5s"] == 20
    assert lot["gross_pnl"] == Decimal("2.80")
    assert lot["net_pnl"] is None and lot["after_exchange_fee_pnl"] is None
    assert sum(x["quantity"] for x in matches) == 100
    assert all(x["unmatched_quantity"] == 0 for x in sales)


def test_multiple_buys_and_sell_not_first_later_pair() -> None:
    lots, _, _ = reconstruct(
        [
            trade("b1", "BUY", 0, "20", ".9"),
            trade("b2", "BUY", 2, "30", ".91"),
            trade("s", "SELL", 6, "25", ".92"),
        ]
    )
    assert lots[0]["fully_closed"] and lots[0]["holding_seconds"] == 6
    assert not lots[1]["fully_closed"] and lots[1]["remaining_quantity"] == 25


def test_unknown_opening_and_nontade_inventory_flag_all_token_lots() -> None:
    lots, _, _ = reconstruct(
        [
            trade("s0", "SELL", 0, "10", ".9"),
            trade("b", "BUY", 5, "10", ".91"),
            trade("s1", "SELL", 6, "10", ".92"),
        ]
    )
    assert not lots[0]["primary_eligible"]
    assert "UNKNOWN_OPENING_OR_NONTRADE_INVENTORY" in lots[0]["integrity_flags"]


def test_same_second_sides_and_multiform_projection_quarantined() -> None:
    lots, matches, _ = reconstruct(
        [trade("b", "BUY", 0, "10", ".9"), trade("s", "SELL", 0, "10", ".91")]
    )
    assert lots[0]["status"] == "AMBIGUOUS_EXCLUDED" and not matches
    lots, matches, _ = reconstruct(
        [trade("b", "BUY", 0, "10", ".9", "tx"), trade("b2", "BUY", 0, "11", ".901", "tx")]
    )
    assert all(x["status"] == "AMBIGUOUS_EXCLUDED" for x in lots) and not matches


def test_known_zero_exchange_fees_are_not_full_cost_net() -> None:
    lots, matches, _ = reconstruct(
        [trade("b", "BUY", 0, "10", ".98"), trade("s", "SELL", 5, "10", ".99")],
        verified_fees={"b": Decimal(0), "s": Decimal(0)},
    )
    assert lots[0]["after_exchange_fee_pnl"] == Decimal(".10")
    assert matches[0]["net_pnl"] is None


@pytest.mark.parametrize(
    "value,label",
    [
        (".499", "BELOW_0.50"),
        (".5", "0.50–0.70"),
        (".7", "0.70–0.80"),
        (".8", "0.80–0.90"),
        (".9", "0.90–0.95"),
        (".95", "0.95–0.98"),
        (".98", "0.98–1.00"),
        ("1", "0.98–1.00"),
    ],
)
def test_predefined_price_boundaries(value: str, label: str) -> None:
    assert price_bucket(Decimal(value)) == label


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-.1", "1.1"])
def test_invalid_price_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        price_bucket(Decimal(value))
