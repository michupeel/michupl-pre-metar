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

## EXP-0006 — Continuous PWS Availability (OPEN)

Question: Can selected open PWS sources deliver fresh, usable observations continuously?

Hypothesis: a provider-balanced DISCOVERY_CANDIDATE cohort can supply useful
temperature readings without requiring unavailable historical accuracy scores.

Data: genuine public AWC/KNMI/DWD and PWS requests, raw envelopes, normalized
observations, distinct arrivals, poll events and heartbeat records in the ignored
continuous-v1 database. Synthetic fault tests are separate from this dataset.

Method: daily discovery; frozen candidates, up to4 per provider/airport; conservative
adaptive>=300s PWS polling, receive clocks, deduplication and minute health snapshots.
Measure usable availability, event-age distribution, intervals, gaps and provider errors.
Sensor.Community server-ingest age is explicitly not measurement age.

Results: an actual660-second run completed2026-10-24T12:23:55Z, followed by a
scheduled restart using the same database. Real repeated requests, raw capture,
normalization, predictions and settlement succeeded. Exact measured counts and
verification evidence are maintained in docs/CONTINUOUS_VALIDATION.md and generated
reports/continuous/. No multi-day availability claim has been measured.

Limitations: short soak; many openSenseMap records are stale or unsuitable; public
provider restrictions are not unlimited quotas; machine sleep/network/logon affect
coverage. Absolute clock offset was unverified (Windows Time Service stopped).

Conclusion: IMPLEMENTED and initial live operation OBSERVED; long-duration
availability remains INSUFFICIENT DATA.

Next steps: retain prospective collection for multiple days, audit gaps and
observed sensor cadence, then review candidate replacements prospectively.

## EXP-0007 — Next METAR Prediction (OPEN)

Question: Can quality-filtered PWS measurements improve predictions of the next
routine METAR temperature?

Hypothesis: selected PWS add out-of-sample value beyond recent official-report
persistence and a simple recent-report trend.

Data: immutable forecasts at configured pre-observation checkpoints, input IDs,
receive cutoffs, prior QC/calibration IDs, and append-only real METAR settlements.

Method: compare previous METAR, its explicit persistence alias, two-report trend,
nearest PWS, median ensemble, inverse distance and quality weighting. Unavailable
methods remain unavailable. Compare matched airport/target/checkpoint samples.
Integer errors and continuous interval-distance errors remain separate.
Confidence intervals use whole UTC-day blocks only after100 matched targets over
7 days; they do not assume independent consecutive reports.

Results: automatic creation and actual settlement were observed. Initial forecasts
span only a handful of nominal targets. No model advantage is established.

Limitations: insufficient history for reliable station scores/calibration; quantized
reference; correlated reports; frozen initial candidate selection; incomplete
checkpoint coverage during startup.

Conclusion: INSUFFICIENT DATA. No positive predictive finding declared.

Next steps: accumulate a frozen prospective cohort and evaluate an untouched future
period, including persistence on identical eligible targets.

## EXP-0008 — Information Availability Lead (OPEN)

Question: How long before our fastest configured reference receipt can an
accurate prediction exist?

Hypothesis: some genuinely prospective PWS forecasts precede our monitored full
reference receipt. This is not equivalent to global publication or market advantage.

Data: real completion, receive and request clocks, run IDs and monotonic markers.
Historical event-only observations and retrospective forecasts cannot establish lead.

Method: EXP-A (before nominal observation) only in continuous-v1; EXP-B
(post-observation/pre-receipt) remains disabled. Exclude forecasts created after
first receipt and startup/gap-censored timing claims. Retain separate UTC and
same-run monotonic differences where available; never compare monotonic clocks
across restarts.

Results: direct KNMI's nominal12:25 EHAM report was received at approximately
12:21:58Z on2026-10-24. This demonstrated the need to block already-known targets
even before nominal time. The first soak exposed a baseline gate defect; affected
forecasts remain immutable and are excluded by settlement validity. The gate is
fixed and covered by a deterministic early-nominal-future regression test.

Limitations: unverified UTC offset, polling cadence, source coverage gaps, shared
upstreams and short measurement period. First receipt is our collector's receipt,
not proof of worldwide publication time.

Conclusion: INSUFFICIENT DATA. No validated actionable information lead claimed.

Next steps: monitor clock diagnostics and collect many uncensored target cycles;
evaluate EXP-B under a separate future protocol if implemented.

## EXP-0009 — Station Stability (OPEN)

Question: Which PWS retain useful predictive performance under changing conditions?

Hypothesis: only some candidates remain fresh and consistent across day/night
and changing environmental conditions; disagreement may reflect microclimate.

Data: frozen discovery cohort, repeated sensor observations, metadata history,
hourly deterministic QC and future matched-target results.

Method: existing temporal/spatial/solar suspicion checks, prior-only calibration,
minimum samples and evaluation days. Forecast trajectories preserve first correct,
last incorrect, observed stable-correct checkpoint and revision count. Missing
checkpoints do not demonstrate stability. Inspect day/night and changing conditions
before any prospective selection revision.

Results: pipeline and descriptive reports implemented. Environmental coverage is
too short to identify stable predictive stations.

Limitations: unknown exposure/hardware, server-only event semantics, genuine
microclimates and insufficient seasonal/weather diversity.

Conclusion: INSUFFICIENT DATA; experiment remains OPEN.

Next steps: collect days/weeks, inspect deterministic flags and temporal coverage,
then freeze a new validation cohort without retrospective performance selection.
