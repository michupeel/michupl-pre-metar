# Research log

## EXP-0001 — public high-frequency observations before routine METAR

Date:2026-10-21 UTC.

Question: Can airport observations predict the next integer METAR temperature
before our first full-report receipt from monitored dissemination paths?

Data: prospective immutable HTTP captures, initially EDDM/DWD (A), EHAM/KNMI(B),
with AWC/KNMI METAR receive comparison. No historical-only latency evidence.

Method: naive WMO Celsius rounding; target chosen by station/nominal order before
correctness is evaluated. Exclude startup, gaps, historical and cross-run clocks.
Report accuracy/MAE/bias and receive lead by fixed buckets. Frozen protocol is
copied into each run manifest. No ML/probability fitting in M1.

Result: initial smoke confirms working AWC, DWD10min and KNMI full-report capture.
It is too short and startup-censored to establish edge. See docs/verification.md
for actual counts and identities. Version1 produced no latency pairs; version1.1
clarifies request overlap is not a publication lower bound and records the precise
monotonic clock implementation.

Conclusion: INCONCLUSIVE / INSUFFICIENT DATA. A successful HTTP/parser test is not
an information edge result. Any negative conclusion requires adequate coverage.

Next: collect multiple days, review freshness and exclusions; implement authorized
KNMI10min/notifications and expand EDDM full-report race only after verification.

### EXP-0001A — EDDM / DWD

Verified DWD01262 München-Flughafen (WMO10870). Live ZIP contains TT_10,TD_10,QN,
pressure and UTC MESS_DATUM. TT_10 is documented instantaneous2m temperature.
Publication cadence is a bottleneck to measure: `now` is documented as hourly/
less than1h, unlike10-minute observation sampling. Sensor parity unverified.

### EXP-0001B — EHAM / KNMI

Direct no-key KNMI full METAR works and preserves original TAC plus upstream
translation receipt. Second path AWC works. KNMI10min candidate adapter is pending
API-key/format verification, so no EHAM predictive accuracy is claimed.

## EXP-0002 — Open PWS Discovery

Question: Can we discover publicly accessible temperature sensors near selected airports?

Hypothesis: Anonymous documented APIs expose usable inventories within 20km of
EDDM, EHAM, EPWA and EGLL, with sensor identity separable from station grouping.

Data: actual public HTTP discovery on 2026-10-23 at approximately22:30 UTC;
NOAA airport reference metadata; raw responses retained locally. No paid sources.

Method: bbox or area discovery, normalized provider identities, exact horizontal
haversine filtering, temperature-sensor identification, auditable discovery snapshots.

Results: openSenseMap stations EDDM35/EHAM53/EPWA124/EGLL9; temperature-bearing
subset29/38/104/9. Sensor.Community temperature-bearing location groups22/36/63/7.
349 airport/provider station associations;308 with temperature sensors. Netatmo
runtime blocked; no Netatmo or CWOP station count measured.

Limitations: provider records are not independent physical station counts;
Sensor.Community's recent window misses offline stations; unknown metadata and
licensing/quota details remain explicitly documented. Proximity proves no skill.

Conclusion: discovery feasibility demonstrated for two public APIs. Predictive
quality and information edge remain INSUFFICIENT DATA.

Next steps: prospective monitoring, conservative duplicate review and completing
provider terms/metadata verification before wider data redistribution.

## EXP-0003 — Automated Sensor Quality

Question: Can deterministic QC identify unreliable or unsuitable nearby sensors?

Hypothesis: physical, metadata and temporal checks identify obvious problems,
while spatial/solar flags preserve genuine microclimate alternatives.

Data: synthetic behavioral tests plus a bounded actual45-second combined capture
with eight manually selected monitoring associations (two providers/four airports).

Method: raw-first normalization, configurable physical limits, clock/freshness
checks, duplicate/jump/stuck/gap diagnostics, distance-weighted peers and Astral
solar geometry. Save versioned QC outputs; never fabricate scores for small samples.

Results:12 normalized PWS readings/12 arrivals; four openSenseMap readings had
three missing temperatures and one reported -145.38°C (physically implausible).
Eight Sensor.Community readings contained temperatures with server-ingest clocks.
Initial quality report found four fresh station associations; all349 associations
remained UNVERIFIED without predictive history. Original payloads were preserved.

Limitations: this smoke does not validate false-positive rates, solar diagnosis,
historical peer independence or long-term availability. Stuck-sensor peer
corroboration remains experimental; unknown metadata does not establish bad hardware.

Conclusion: obvious faults are detected by deterministic code and fixtures;
real-world sensor reliability is still INSUFFICIENT DATA.

Next steps: accumulate multi-day records and review flagged sensors alongside
their metadata and neighboring microclimates.

## EXP-0004 — PWS Predictive Value

Question: Do quality-filtered PWS observations improve out-of-sample prediction
of the next METAR temperature?

Hypothesis: prior-only calibrated PWS temperatures improve exact integer matches
relative to last-METAR persistence on future held-out targets.

Data: existing METAR observations/receipts and new PWS capture. No usable OOS
research evaluation sample yet; synthetic tests are not performance evidence.

Method: interval-aware quantized-reference corrections, rolling mean/median,
chronological walk-forward, strict label-availability cutoff, stable sensor
identity, shared raw/calibrated/baseline evaluation targets. Ranking minimum100
OOS samples and seven evaluation dates; hold final station selection fixed later.

Results: estimator/calibration/weighting and no-future-data paths are implemented
and regression-tested. No station accuracy score or incremental improvement is measured.

Limitations: integer METAR is not a continuous temperature reference; upstream
sensor parity, EPWA/EGLL reference collection and held-out station selection remain
unverified or unavailable. Current analysis is explicitly exploratory.

Conclusion: INSUFFICIENT DATA. No improved predictive performance is claimed.

Next steps: collect paired future targets, freeze selection/calibration choices,
then evaluate on a separate untouched chronological period.

## EXP-0005 — Real-time PWS Information Lead

Question: Do quality-filtered PWS observations produce useful temperature
predictions before the next METAR is publicly received?

Hypothesis: an immutable prospective prediction based only on already received
PWS data can precede the first monitored full METAR receipt with useful accuracy.

Data: prospective raw receive clocks and immutable forecasts; historical event
times alone and synthetic timestamps are excluded from timing evidence.

Method: observation receive<=decision, prior metadata/selections/calibrations/QC,
prediction completion timestamp and run-scoped monotonic marker; later reference
comparison separates exact accuracy, UTC receive difference and certified lead.

Results: prospective prediction persistence/evaluation is implemented. The
bounded collector does not yet certify continuous capture coverage, and records
capture_coverage_verified=false. No measured information lead is awarded.
Actual smoke prediction `b64b744e72b5451aa13c08887692c960` was completed at
2026-10-23T22:58:25.999406Z for EHAM23:25Z, using a previously received
Sensor.Community value11.8°C and predicting integer12°C. It remains pending
reference evaluation; this is not an accuracy result or timing-edge claim.

Limitations: startup censoring, polling gaps, unknown clock offset, shared upstream
providers and server-only sensor clocks preclude a strong timing conclusion.
First seen means our configured sources, not global public publication.

Conclusion: INSUFFICIENT DATA. Neither historical correlation nor a successful
HTTP response establishes an actionable pre-METAR edge.

Next steps: collect repeated bounded prospective runs, audit coverage and clock
continuity, then assess accuracy and receive-order lead separately.
