# EXP-0016 forecast sources and empirical probability contract

Verified 29 October 2026 against current official documentation and one bounded
pair of public live API schema checks. These are research data, not trading advice
or evidence of profitable execution. No production collector was changed.

## Current forecast API

Source: [Open-Meteo Forecast API](https://open-meteo.com/en/docs), with provider
descriptions for [DWD](https://open-meteo.com/en/docs/dwd-api),
[ECMWF](https://open-meteo.com/en/docs/ecmwf-api) and
[NOAA](https://open-meteo.com/en/docs/gfs-api).

The selected endpoint is `https://api.open-meteo.com/v1/forecast`, explicitly
selecting `models`, `hourly=temperature_2m`, `daily=temperature_2m_max`,
`timezone=Europe/Warsaw`, `timeformat=unixtime`, and Celsius. Exact EPWA reference
coordinates must come from the existing airport configuration. No best-match,
seamless model or historical stitched reconstruction is silently substituted.

| API model ID | Label | Dependence grouping | Bounded API probe |
|---|---|---|---|
| icon_global | ICON Global | DWD_ICON | HTTP 200, hourly/daily fields present |
| icon_eu | ICON Europe | DWD_ICON | HTTP 200, hourly/daily fields present |
| ecmwf_ifs | ECMWF IFS | ECMWF | HTTP 200, hourly/daily fields present |
| ecmwf_aifs025_single | ECMWF AIFS | ECMWF | HTTP 200, hourly/daily fields present |
| gfs_global | GFS Global | NOAA_GFS | HTTP 200, hourly/daily fields present |

Two bounded batch requests with all five models, two forecast days and EPWA-area
coordinates succeeded during implementation. They established schema and normalizer compatibility;
they were not durably recorded prospective forecasts and must not enter performance
or latency results. Actual prospective snapshots belong to the research monitor's
raw-first journal.

The API returns suffixed keys for a multi-model response, e.g.
`hourly.temperature_2m_icon_global` and
`daily.temperature_2m_max_icon_global`, with corresponding suffixed unit keys.
The normalizer also accepts the documented bare keys for a single-model response.
Missing temperatures remain missing; nonfinite/physically impossible values,
ambiguous timestamps, units other than Celsius, duplicate or unordered timestamps
are rejected. The normalization function does not send HTTP requests.

## Time and target semantics

* Hourly `temperature_2m` is a temperature at the valid instant. The maximum of
  these hourly samples has its own field and all tied peak timestamps.
* Daily `temperature_2m_max` is the API's daily aggregation and remains separate.
  Documentation describes daily aggregates from hourly values; it does not
  certify the airport's official final maximum or the market settlement target.
  Even when the two numerical maxima match, their provenance remains separate.
* No true hourly maximum is requested or invented. `hourly_maximum_c` is NULL.
* Epoch times are converted directly to timezone-aware UTC. Warsaw local-day
  boundaries are independently constructed from calendar dates; no fixed
  24-hour addition in UTC. The fall-back day has 25 hourly slots; the spring
  transition has 23. Repeated local clock labels retain distinct UTC identities.
* `generationtime_ms` is response computation duration. It is not initialization,
  publication, original availability or data age. Current API responses do not
  establish those original clocks; `initialization_time` and `publication_time`
  stay NULL. First collector receipt is recorded by the caller.
* Missing model-run identity is disclosed as `LIVE_API_RUN_UNIDENTIFIED`.
  Consecutive live snapshots are revisions, not independently identified runs.
* Model disagreement is a descriptive range, not a probability or independent
  vote count. ICON Global/Europe are grouped together; IFS/AIFS share an ECMWF
  dependence group. This does not claim models within or between groups are
  statistically independent.

## Historical runs and availability

[Single Runs API](https://open-meteo.com/en/docs/single-runs-api) documents the
`run=YYYY-MM-DDTHH:MM` parameter. The current page states IFS HRES archive from
March 2024 and most other models from 2 April 2026. This is an archive access
capability, not proof of original public availability at initialization. A run
downloaded today cannot be treated as a prospective receipt on its historical
initialization day. No paid access, subscriptions or large archive crawl was
enabled for this task. Missing original availability blocks calibrated prospective
claims; approximate archive replay must be labeled separately.

## Terms, attribution and request budget

[Open-Meteo terms](https://open-meteo.com/en/terms) restrict the free hosted API to
non-commercial use, subject to current request limits (10,000/day, 5,000/hour,
600/minute and 300,000/month). Data use requires CC BY 4.0 attribution to
Open-Meteo and the original providers. CC BY data licensing does not remove the
hosted service's access restrictions. This open research-only experiment does
not authorize commercial deployment; do not enable paid APIs automatically.
Provider availability is not guaranteed. Prefer one batched conservative request
over five independent polling loops and reuse captured snapshots where suitable.

## Pure utility interfaces

`normalize_model(payload, model, received)` returns model/family/first receipt,
unknown original clocks, UTC points and per-local-day summaries. `consensus`
selects only the latest snapshot/model with first receipt at or before its as-of
cutoff. It returns descriptive model range and family medians, with no estimated
probability. `horizon_bucket` separates local D−1 morning (<12:00), afternoon
(12:00–17:59), evening (>=18:00), D0 morning and D0 intraday. These are frozen
research strata, not optimized timing windows.

`empirical_probability(history, forecast, outcome, at, validation=None)` uses a
small empirical residual distribution. It is deliberately unavailable without
verified data and a separate accepted chronological validation artifact.

Required candidate forecast fields: `model`, `settlement_date`,
`first_received`, `daily_tmax_c`, `reference_id`. Outcome fields: `kind` EXACT,
AT_MOST or AT_LEAST; `value_c` integer; explicitly verified
`rounding=NEAREST_TIES_WARMER`. Unknown market rounding blocks this estimator;
an ICAO METAR rounding convention is never silently transferred to market rules.

Each history row requires:

* model, settlement_date, forecast_first_received, forecast_tmax_c;
* settlement_tmax_c, settlement_received, official_settlement_verified=True;
* the exact matching official reference_id and target_semantics=DAILY_API_MAX;
* availability_provenance=FIRST_COLLECTOR_RECEIPT;
* run_provenance=PROSPECTIVE_CAPTURE or ORIGINAL_ARCHIVED_RUN; the latter also
  requires an initialization_time no later than its actual historical receipt.

Only prior settlement days whose actual outcomes were already received before
the decision can train. The forecast receipt must match the candidate's frozen
local horizon stratum. Multiple revisions count once per independent day, taking
the latest eligible captured snapshot in that stratum. Future target outcomes,
later receipts, routine METAR maxima, other reference identities, stitched
forecasts and unverified outcomes are excluded. At least 30 independent days
are required; lower caller thresholds cannot weaken this floor.

A separate validation artifact must identify the same model/horizon/reference,
method CHRONOLOGICAL_WALK_FORWARD and passed=True. A count alone cannot authorize
calibration. Required fields are:

* nonempty audit_id and artifact_hash, the SHA256 of its canonical JSON excluding
  artifact_hash (sorted keys, compact separators, no NaN);
* training_dates exactly matching the selected independent training dates,
  training_end_date equal to their maximum;
* validation_dates with at least20 unique explicit dates, disjoint from training
  and all strictly after training_end_date and before the current target day;
* independent_evaluation_days equal to that explicit list length and
  evaluation_end_date equal to its maximum;
* evaluation_evidence keyed by every validation date, containing original
  forecast_hash and settlement_hash (64 lowercase hex characters), actual
  forecast_first_received and settlement_first_received, the same reference_id,
  official_settlement_verified=True and fold_training_end_date;
* all training outcomes already received before each validation forecast receipt,
  validation forecasts matching the same horizon, and final daily outcomes
  received after their local day ended;
* last_outcome_received exactly matching the latest validation receipt, with all
  evidence available no later than available_at, itself before the current
  decision.

The passed decision must be supported by separately audited matched chronological
evaluation, not set by this function or a training score. Hashes bind the retained
artifact and source input identities; they do not independently prove the
caller's official-data verification or make invented records truthful. The audit
must retain/review those source records. No such artifact is invented or
automatically promoted. Missing, overlapping, tampered, future or invalid
artifacts return VALIDATION_PENDING with NULL probabilities even if training
history is large. A future refit changing training dates requires a new audited
artifact; previously held-out days cannot silently become training inputs under
the old validation artifact.

For accepted inputs, residual = official settlement maximum − archived daily
forecast maximum. Apply each prior residual to the current forecast and round
according to the explicitly verified target rule; the empirical fraction matching
the actual outcome bucket is estimated YES probability, with NO=1−YES.
Confidence bounds remain NULL: dependence between settlement days requires
separate block/cluster evaluation. A tiny or zero empirical failure count does
not establish certainty or an actionable edge. Tests use explicit synthetic
fixtures; they do not establish EPWA model accuracy or financial profitability.
