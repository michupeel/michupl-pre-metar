# EXP-0016 — Tomorrow forecast versus market

Snapshot cutoff UTC: 2026-10-29T13:14:39.785243+00:00. Settlement date Warsaw: 2026-10-30.

Prospective raw-first capture only. No real orders. CALIBRATION PENDING; no probability, EV or positive edge is established.

## Model availability

Model | Family | Daily API Tmax | Hourly point max | First collector receipt | Original run
---|---|---:|---:|---|---
ecmwf_aifs025_single | ECMWF | 8.9 | 8.9 | 2026-10-29T13:13:57.643644+00:00 | UNKNOWN
ecmwf_ifs | ECMWF | 9.5 | 9.4 | 2026-10-29T13:13:57.643644+00:00 | UNKNOWN
gfs_global | NOAA_GFS | 12.5 | 12.5 | 2026-10-29T13:13:57.643644+00:00 | UNKNOWN
icon_eu | DWD_ICON | 10.8 | 10.7 | 2026-10-29T13:13:57.643644+00:00 | UNKNOWN
icon_global | DWD_ICON | 11.0 | 11.0 | 2026-10-29T13:13:57.643644+00:00 | UNKNOWN

## Actual tomorrow contracts

Outcome | YES bid/ask | NO bid/ask | Rules | Candidate
---|---|---|---|---
{'kind': 'EXACT', 'label': '5°C', 'temperature_c': 5} | 0.001/0.002 | 0.998/0.999 | VERIFIED_CAPTURED_NOAA_RULE_CLAUSES | PROBABILITY_UNVALIDATED
{'kind': 'EXACT', 'label': '10°C', 'temperature_c': 10} | None/None | None/None | VERIFIED_CAPTURED_NOAA_RULE_CLAUSES | PROBABILITY_UNVALIDATED
{'kind': 'EXACT', 'label': '7°C', 'temperature_c': 7} | None/None | None/None | VERIFIED_CAPTURED_NOAA_RULE_CLAUSES | PROBABILITY_UNVALIDATED
{'kind': 'EXACT', 'label': '6°C', 'temperature_c': 6} | 0.001/0.002 | 0.998/0.999 | VERIFIED_CAPTURED_NOAA_RULE_CLAUSES | PROBABILITY_UNVALIDATED
{'kind': 'EXACT', 'label': '9°C', 'temperature_c': 9} | None/None | None/None | VERIFIED_CAPTURED_NOAA_RULE_CLAUSES | PROBABILITY_UNVALIDATED
{'kind': 'EXACT', 'label': '12°C', 'temperature_c': 12} | None/None | None/None | VERIFIED_CAPTURED_NOAA_RULE_CLAUSES | PROBABILITY_UNVALIDATED
{'kind': 'AT_LEAST', 'label': '14°C or higher', 'temperature_c': 14} | None/None | None/None | VERIFIED_CAPTURED_NOAA_RULE_CLAUSES | PROBABILITY_UNVALIDATED
{'kind': 'EXACT', 'label': '11°C', 'temperature_c': 11} | None/None | None/None | VERIFIED_CAPTURED_NOAA_RULE_CLAUSES | PROBABILITY_UNVALIDATED
{'kind': 'EXACT', 'label': '8°C', 'temperature_c': 8} | None/None | None/None | VERIFIED_CAPTURED_NOAA_RULE_CLAUSES | PROBABILITY_UNVALIDATED
{'kind': 'EXACT', 'label': '13°C', 'temperature_c': 13} | None/None | None/None | VERIFIED_CAPTURED_NOAA_RULE_CLAUSES | PROBABILITY_UNVALIDATED
{'kind': 'AT_MOST', 'label': '4°C or below', 'temperature_c': 4} | None/None | None/None | VERIFIED_CAPTURED_NOAA_RULE_CLAUSES | PROBABILITY_UNVALIDATED

## Required research answers

1. Available models/receipt timestamps are listed above. Original initialization and publication timestamps are not supplied by this live endpoint.
2. Forecast/price disagreement is descriptive only: no calibrated probability exists, so a mispricing frequency cannot yet be measured.
3. Decision-book depth is conditional. See candidate CSV for ask-side quantities, freshness and rejected cases. No arrival fill is inferred.
4. D-1 settlement Tmax error/accuracy: INSUFFICIENT VERIFIED ARCHIVED_RUN_AND_OFFICIAL_TARGET PAIRS.
5. P(NO9C | forecast10-13C): NOT IDENTIFIABLE. Consensus is not probability.
6. Overnight/D0 repricing: prospective multi-day follow-up required; no reconstructed profitable history.
7. Best OOS exit: NOT IDENTIFIABLE; three frozen triggers are recorded, execution remains blocked until calibration promotion.
8. D1 committed capital/known inventory:0/0, because entries are blocked. Tail losses and capital-time performance are unmeasured, not proven absent.
9. No matched completed independent settlement days to establish D1 superiority over SIMPLE/WEATHER/HYBRID. Equal100USD/5USDorder/25USDday budgets are frozen.
10. No positive prospective economic edge established.

## Accounting and limits

Captured candidate evaluations:506 (not independent trades). Completed identified days:0. Negative reasons:{'OUTSIDE_D_MINUS_1_ENTRY_DAY': 253, 'PROBABILITY_UNVALIDATED': 506}.
Rule parser policy (only certified per contract when captured clauses match): qualifying routine observation T-remark maximum with body fallback, SPECI exclusion, warmer ties and correction cutoff. Empty/unverified markets do not establish those rules. This is not silently equated with true continuous daily Tmax or only nominal routine integers.
Existing audit:14 archived runs (7 ICON Global/7 ICON EU,21-27Oct00UTC) downloaded28Oct. Their availability is APPROXIMATE_REPLAY with unknown publication and assumed init+6h. Earlier hourly study has94 independent targets/5days, but0 verified final settlement Tmax days. Thus0 audited D-1 forecast/final-settlement calibration pairs; do not confuse missing eligible pairs with no archived forecasts. Related ICON/ECMWF models are grouped, not five independent votes.
D0/D1 are local calendar dates, including DST. Current snapshots and book statuses may be stale. Existing collectors untouched. The independent bounded journal stops at storage cap rather than deleting evidence.
Read limits: {'truncated': False, 'segment_limit_reached': False, 'segments_available': 1, 'segments_considered': 1, 'errors': {}, 'limit': 20000, 'cutoff': '2026-10-29T13:14:39.785243+00:00', 'semantics': 'IMMUTABLE_EVENTS_ONLY_CHECKPOINT_NOT_HISTORICAL_EVIDENCE'}
