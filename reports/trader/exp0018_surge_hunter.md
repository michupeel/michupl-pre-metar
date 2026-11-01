# EXP0018.1 — Surge Hunter

Generated 2026-11-01T01:09:52.726055+00:00. Bounded prospective capture, separate retrospective Wellington replay.

## Actual session evidence

| Contracts/tokens | Duration s | BOOK / DELTA | Reconnects | Storage bytes | Integrity |
|---|---:|---|---:|---:|---|
|4/8|361.01600000000326|8/12|0|139264|ok|
|8/16|361.0309999999881|20/88|0|372736|ok|
|4/8|31.030999999988126|8/0|0|106496|ok|
|4/8|16.030999999988126|8/1|0|106496|ok|

## Prospective independent detector

```json
{
  "surges": 4,
  "entries": 0,
  "associations": 0,
  "association_reviews": 4,
  "supported_fills": 0,
  "matched_controls": 0,
  "market_day_clusters": 2,
  "source_packets": 2,
  "complete_pre_entry_windows": 0,
  "window_scope": "RECORDED_SESSION_BEFORE_SOURCE_REPORTED_TIME_NOT_VERIFIED_MATCHING_TIME",
  "events_by_kind": {
    "LIQUIDITY_APPEARANCE": 4
  },
  "independent_entry_probability": null,
  "shadow_profit": null,
  "matched_comparison_status": "INSUFFICIENT_DATA"
}
```

Mirrored YES/NO and different threshold fields are not independent decisions. Source packets and market/day clusters are reported separately. No-entry labels remain delayed/censored. Missing market-age, exact settlement-window and verified METAR context prevent a valid matched-control effect estimate; no entry-probability percentage is reported.

## Wellington: new discriminating evidence

Exact RAW WS BUY transaction hash joins the canonical receipt. Public BUY receipt08:58:29.775972 precedes the genuine bid insertion08:58:29.863130 by87.158ms; exchange timestamps also order BUY before bid (54ms). Data API time08:58:33 equals block timestamp, not an independently verified matching-engine clock. This specific bid jump is not evidence of a signal preceding the observed execution print.
The executed BUY is BUY/BUY mint:207.78NO funded by196.0404pUSD from HighTempTation plus11.7396pUSD from five YES makers. Effective NO fills0.92/0.93/0.94/0.95/0.98. SELL207.78at0.99 is also chain-verified TAKER. Gross cash difference9.6618before unknown external costs, conditional inventory association; no copy fill or net-profit claim.

## Reconnect diagnosis

Confirmed amplifier: baseline backoff reset after each handshake, so short-lived sessions repeatedly waited only3s. New experiment opts into60s stable-session reset; synthetic regression verifies3/6/12s retry progression. Existing default unchanged. Old disconnect root cause remains UNKNOWN: original logs have ConnectionClosedError but no close frames/codes. Small clean sessions cannot establish causation by cohort size. No healthy process restarted.

## Frozen research definitions

Same-token/same-session quote changes>=0.10 within<=5s; depth change>=100shares and>=50%; spread change>=0.05. Initial/gap states cannot trigger. Snapshot transitions explicitly labeled. Empty sides remain distinct from missing data. Complementary1-bidYES is theoretical without exchange/fee/arrival proof; no optimistic maker queue fills. Real source event histories are persisted before wallet attribution, not selected after future trades.

## Operational limitations

Recorded session duration can exceed300s while event activity is sparse; PONG is not a depth freshness certificate. Current old quotes are stale, not current executable books. No complete actual pre-entry event window is claimed without an entry and continuity evidence. Continuous command cycles finite sessions with explicit gaps; autostart was not installed. Storage caps stop rather than deleting research evidence. See EXP0018_SURGE_OPERATIONS.md for budgets/commands.
