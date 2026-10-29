# EXP0016.1 — forecast/settlement joins and error accounting

`premetar.research.settlement_calibration` is research only. It never updates
production forecasts, probabilities, strategy configuration or paper positions.
Its output is a reproducible retrospective dataset, not newly created live signals.

Interfaces:

* `load_archived_runs(Path)` opens the existing archive read-only, at most5000
  ARCHIVED_RUN rows, with archive event/hash and original download receipt.
* `evaluate(runs, targets, at=aware_datetime)` returns records, model summaries,
  excluded reasons, independent-day counts and a pending-calibration indicator.
* `export(result, directory)` deterministically serializes JSON and CSV plus
  a JSON SHA256. No wall clock/network/database write is hidden in evaluation.

Canonical target input fields: `settlement_date`, `classification`,
`raw_maximum_c`, `settlement_integer`, `target_available_at`, `source_provenance`,
`market_event_id`. Target classes remain separate. Fully verified source+market
claims require a finite raw maximum and integer agreeing under nearest/ties-warmer
rounding, evidence after the local day ended and no conflicting duplicate label.
Rows whose evidence was not yet received by analysis cutoff are excluded.
Source-only/market-only rows never count as fully verified calibration days.

## Frozen D-1 selection

Checkpoints06:00,12:00,18:00 Europe/Warsaw on the previous local calendar day.
Within model AND availability class choose the latest initialized run actually
eligible by that checkpoint and containing the complete target local-day hourly
grid. Warsaw23/25hour days use neighboring local midnights; repeated02:00 stamps
remain distinct UTC points. Duplicate valid UTC timestamps are invalid.

PROSPECTIVE_CAPTURED uses actual first collector receipt. Verified historical
availability requires an explicit verification flag and original availability.
The existing archived-run alternative is only the documented
INIT_PLUS_6H_SCENARIO_NOT_VERIFIED_ORIGINAL_AVAILABILITY assumption. Its init+6h
eligibility is labeled APPROXIMATE_REPLAY and never counted as strict chronology.
A later run or assumption unavailable at a checkpoint cannot be used there.
Actual download receipt stays visible even when later than historical decision.

Every output retains model/family/run ID, init, verified publication if present,
original or assumed availability separately, first download receipt, decision,
valid-day bounds, init/decision lead to day start, all tied peak hours, target
receipt/class/provenance, raw maximum, integer outcome and payload hash.
`target_known_at_historical_decision` explicitly records that backfilled labels
were not information inputs. Ground-truth labels are outcomes, not forecasts.

## Tmax semantics and metrics

The existing14run archive has hourly temperature points only. `daily_api_tmax_c`
and its errors remain NULL; the maximum of hourly points is exported separately
as `hourly_point_max_c`. No routine METAR maximum or hourly-point maximum is
silently described as a dailyAPI/continuous airport maximum.

Continuous forecast errors use the actual raw qualifying source maximum, with
source-reconstructed versus verified-final scopes separate. Market-only integer
labels permit integer agreement and interval-distance diagnostics, not precise
continuous errors. An exact upper half-degree has zero distance infimum to the
METAR interval yet rounds toward the warmer integer; exact match is separate.

Model/availability/verification/checkpoint summaries show RAW MAE, signed bias,
median error, dailyAPI errors where available and integer match. Three checkpoints
for one day and correlated forecasts never create three independent target days.
Strict-pair counts require both fully verified source+market target and verified
or prospective forecast availability. Approximate replay pairs are counted apart.

Disagreement diagnostics freeze the12:00 checkpoint, group related models by
family median and evaluate family spread against absolute family-median error.
At least20 matched independently verified days, at least2families per day and
at least5days in each fixed<2C/≥2C spread bin are required before showing a
descriptive association. It is not a causal effect or a probability. With only
ICON Global/Europe archives, one family alone cannot support this comparison.

## Probability readiness

This utility does not fit/promote probabilities. The existing minimum remains
30independent training days plus20separate chronological validation days and
an audited promotion certificate. Verified target count alone is not sufficient:
original horizon availability and held-out validation must also be present.
Until then `CALIBRATION_PENDING`, probabilityNULL, promotionfalse.

The current historical archives21–27October2026 were downloaded28October and
have unknown original publication clocks. More independent raw-error observations
can be useful exploratory evidence but cannot manufacture prospective chronology.
