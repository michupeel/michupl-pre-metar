"""Historical descriptive statistics must not invent position attribution."""

from premetar.research.trader_reports import characterize, market_identity


def test_minimum_and_maximum_markets_remain_separate() -> None:
    assert market_identity("lowest-temperature-in-ankara-on-october-25-2026-5c") == (
        "TMIN",
        "ankara",
    )
    assert market_identity("highest-temperature-in-taipei-on-october-25-2026-31c") == (
        "TMAX",
        "taipei",
    )
    assert market_identity("btc-up-or-down") == ("OTHER", "UNKNOWN")


def test_first_later_sell_does_not_use_equal_or_prior_clocks() -> None:
    def row(side: str, second: int) -> dict[str, str]:
        return {
            "side": side,
            "token_id": "1",
            "source_trade_timestamp": f"2026-10-27T09:00:{second:02d}+00:00",
        }

    result = characterize(
        [row("SELL", 1), row("BUY", 5), row("SELL", 5), row("SELL", 11), row("BUY", 12)]
    )
    assert result["median_first_later_sell_seconds"] == 6
    assert result["with_strictly_later_sell"] == 1
    assert result["without_later_sell"] == 1
    assert result["same_second_ambiguous"] == 1
    assert "not proof" in result["interpretation"]
