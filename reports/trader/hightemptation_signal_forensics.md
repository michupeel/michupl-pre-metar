# EXP-0011 public trader research

Generated UTC: 2026-10-27T09:34:30.053034+00:00

Historical/bootstrap trades are not prospective detections. Source trade time is not order placement time.

Recorded event counts: `{"ACTIVITY": 45, "BACKFILL_STATE": 12, "BOOK": 2356, "COPY_COMPLETE": 12, "COPY_REQUEST": 12, "DATA_SERVICE_STATUS": 33, "DISCOVERY": 8, "ENDPOINT_RECEIPT": 641, "ERROR": 2, "EXECUTION_GROUP": 597, "HEALTH": 183, "MARKET": 3657, "PROFILE_VERIFIED": 7, "RAW": 1282, "ROLE_EVIDENCE": 104, "RUN": 7, "SHADOW": 72, "STOP": 6, "STREAMHEALTH": 86, "TRADE": 11865, "WEATHER": 2, "WS_DELTA": 56670, "WS_RAW": 57371, "WS_TRADE": 148}`.

## Historical descriptive characterization

```json
{
  "all_records": {
    "buy_records": 4952,
    "excluded_missing_clock_or_token": 0,
    "with_strictly_later_sell": 4901,
    "without_later_sell": 51,
    "same_second_ambiguous": 5,
    "median_first_later_sell_seconds": 6.0,
    "first_later_sell_within_10_seconds": 3677,
    "first_later_sell_within_60_seconds": 4382,
    "market_kinds": {
      "OTHER": 11,
      "TMAX": 8696,
      "TMIN": 3158
    },
    "source_time_precision_seconds": 1,
    "interpretation": "First later same-token SELL, not proof of full liquidation, linked lots, fees or profit; source timestamps are not decision times"
  },
  "by_statistic": {
    "TMAX": {
      "buy_records": 3435,
      "excluded_missing_clock_or_token": 0,
      "with_strictly_later_sell": 3419,
      "without_later_sell": 16,
      "same_second_ambiguous": 5,
      "median_first_later_sell_seconds": 8.0,
      "first_later_sell_within_10_seconds": 2324,
      "first_later_sell_within_60_seconds": 2956,
      "market_kinds": {
        "TMAX": 8696
      },
      "source_time_precision_seconds": 1,
      "interpretation": "First later same-token SELL, not proof of full liquidation, linked lots, fees or profit; source timestamps are not decision times"
    },
    "TMIN": {
      "buy_records": 1507,
      "excluded_missing_clock_or_token": 0,
      "with_strictly_later_sell": 1481,
      "without_later_sell": 26,
      "same_second_ambiguous": 0,
      "median_first_later_sell_seconds": 5.0,
      "first_later_sell_within_10_seconds": 1353,
      "first_later_sell_within_60_seconds": 1426,
      "market_kinds": {
        "TMIN": 3158
      },
      "source_time_precision_seconds": 1,
      "interpretation": "First later same-token SELL, not proof of full liquidation, linked lots, fees or profit; source timestamps are not decision times"
    },
    "OTHER": {
      "buy_records": 10,
      "excluded_missing_clock_or_token": 0,
      "with_strictly_later_sell": 1,
      "without_later_sell": 9,
      "same_second_ambiguous": 0,
      "median_first_later_sell_seconds": 92.0,
      "first_later_sell_within_10_seconds": 0,
      "first_later_sell_within_60_seconds": 0,
      "market_kinds": {
        "OTHER": 11
      },
      "source_time_precision_seconds": 1,
      "interpretation": "First later same-token SELL, not proof of full liquidation, linked lots, fees or profit; source timestamps are not decision times"
    }
  }
}
```

TMAX and TMIN are distinct market cohorts. Historical exit timing does not establish copy profitability.

## Interpretation

Execution time does not establish decision time. Maker/taker remains UNKNOWN unless separately verified by reliable execution-role evidence. Resting orders are a competing explanation. A snapshot fetched after trade detection cannot reconstruct the pre-trade book. Weather context is available-as-of only where recorded receipt times demonstrate that condition. No missing forecast is substituted retrospectively.

## Recorded book windows and role evidence

At 2026-10-27T09:34:30.427266+00:00, 100 recent captured trades, 2200 requested windows; role counts `{"API_ATTRIBUTED_TAKER": 89, "UNKNOWN": 11}`. Exact trade-ID positive taker-only matches are API attribution, not on-chain verification. Absence does not prove maker. Source-second anchors are descriptive; clock uncertainty prevents claiming millisecond ordering. Detection-time context is not information known at source execution. Order creation remains unknown. See hightemptation_book_windows.csv; unavailable prior books are never replaced with later books.
