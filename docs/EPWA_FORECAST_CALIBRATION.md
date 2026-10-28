# Audited EPWA forecast calibration

Research-only pipeline; no production forecast, station or QC policy is changed.

```powershell
uv run python -m scripts.research.epwa_forecast_calibration --days 7
```

The script preserves raw responses before normalization in its independent ignored
archive database and uses SQLite backup for a consistent weather snapshot. Repeated
requests reuse captured responses. Reports retain snapshot cutoff/hash and input
run IDs. Requested EPWA point:52.163N,20.961E.

## Actual supported archive runs

The official [Single Runs API](https://open-meteo.com/en/docs/single-runs-api)
returned seven initialized00UTC runs each for ICON Global and ICON Europe. Returned
grid points were52.125/21.0 and52.1875/20.9375 respectively. ICON-D2 returned HTTP400,
"No data is available for this location"; no D2 comparison is manufactured.
Model initialization is explicit, but original public availability is unknown.
The fixed replay decision scenario is initialization+6h, marked
APPROXIMATE_REPLAY. It cannot certify actual timely public availability or activate
calibration. Prospective locally received snapshots remain a separate class. See
[model update clocks](https://open-meteo.com/en/docs/model-updates).

## Frozen methods and causal validation

* RAW: unchanged model.
* GLOBAL_MEDIAN: subtract median earlier forecast minus received METAR midpoint;
  minimum24 independent targets across3 local days.
* HOUR_HORIZON_MEDIAN: same local hour and fixed0–6/6–24/24–48/>48h lead bin;
  minimum12 targets across3 days. Otherwise use RAW, explicitly flagged.
* CAUSAL_NOWCAST: subtract half the latest already-received METAR residual times
  exp(-horizon/6h); reference age at most2h, model/reference alignment at most30min.

Each decision uses only earlier run decisions and references received before that
decision. The target cannot train itself. Nominal METAR events are deduplicated;
initial reports are evaluation targets, corrections can only affect training after
their actual receipt. Startup-censored/coverage-gap reports are excluded.
Midpoint residuals retain the integer reference's quantization uncertainty;
interval-aware MAE and exact integer accuracy are reported separately. Model/method
comparisons use matched targets/decisions. Repeated runs/checkpoints are not
independent meteorological events. Day-block uncertainty needs20days; unavailable
intervals remain null.

## Observed result and decision

The final17:33UTC snapshot audit contained14 actual runs,94 independent METAR targets across5
local days, with428 matched forecast-target pairs for cross-model comparisons.
On this same matched sample RAW interval-aware MAE was1.0829C for Global and1.1542C
for Europe. These are approximate hourly archive replay results, not daily Tmax
errors or a statistically validated model ranking. Global and causal-nowcast
corrections failed to improve their own matched RAW results. Hour/horizon correction
had insufficient history and fell back to RAW for every target. Full updated counts
and all failures are in reports/research/epwa_forecast_calibration.{md,json,csv}.

Daily Tmax is a different target. Current captured Warsaw rules use EPWA Aviation
Weather Center routine reports, precise T-group when present, otherwise integer
body temperature; SPECI excluded, local date, corrections subject to the frozen
resolution-source cutoff, Wunderground fallback if applicable. The local database
does not contain an audited final resolution-source view after that cutoff.
Therefore verified final daily targets=0. Never substitute the maximum of captured
routine integers. Daily calibration requires14 earlier verified days and7 future
prospective validation days; approximate replays can never promote it. Validation
outcomes must themselves have been available before any activation decision.

Dashboard state: **CALIBRATION PENDING**, calibrated Tmax/time/error unknown,
sample size0 verified final days. RAW Tmax remains visible alongside it. There is
no invented corrected Tmax, confidence interval, timing error or performance gain.
