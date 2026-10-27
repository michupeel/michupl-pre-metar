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


## Milestone 1.6.1 — timestamp integrity amendment (2026-10-24)

Question: how much trustworthy measurement-time evidence survives strict validation?

Baseline: the running continuous-v1 collector retained raw-first PWS records and
used a labelled Sensor.Community server-ingestion proxy in some analytical paths.
A consistent SQLite backup at16:53:18Z contained3503 PWS rows and1105 predictions.

Hypothesis: enforcing verified measurement semantics and300s freshness materially
reduces samples but improves the interpretability of prospective experiments.

Method: verified official API semantics, introduced an additive versioned ledger,
rehearsed on a supported SQLite backup, preserved hashes of original observations,
arrivals, predictions and settlements, and applied current policy in all analytical
paths. No missing date/time was inferred from HTTP receipt. Append-only exclusions
preserve original forecasts and settlements, including the four early-KNMI cases.

Observed pre-hotfix snapshot under the new policy:1094 openSenseMap rows contained
280 eligible-at-receipt measurements,3 stale and811 invalid/unknown rows;2409
Sensor.Community rows had no verified measurement time.562 of1105 forecasts were
excluded under stricter input/parameter/first-receipt checks. EPWA had114 eligible
measurements from two instruments on one station13.902km away, spanning14:12 to
18:47 CEST,9.12–12.78C. Neither instrument is an independent weather station.

Controlled deployment: old run ended17:26:47.853799Z; new run began17:26:55.579161Z
using the same task/database/cohort. The stopped-state backup migration assessed
3917 rows and excluded625 forecasts without changing original row hashes. Integrity
wasok and foreign_key_check empty. New forecasts subsequently used strict inputs.
Final live-cycle outcomes and report snapshots are recorded in reports/daily and
docs/TIMESTAMP_HOTFIX_VALIDATION.md; counts grow after those snapshots.

Clock evidence: W32Time stopped; automatic synchronization/source/last sync UNKNOWN.
Independent windows.com/cloudflare.com checks consistently reported about+1.05 to
+1.06s offset, outside our one-second research budget. No Windows settings/service
changes or timestamp corrections were made. This is approximate network evidence.

Interpretation: EXP-0006/0007/0008/0009 remain OPEN. Strict EPWA data comes from a
small subset of candidates. A roughly1C same-station sensor difference warrants
monitoring, not a permanent bias or solar-heating diagnosis. Historical proxy-based
results are superseded for analytical eligibility, never erased.

Limitations: API-level measurement semantics do not attest device clocks; no
Sensor.Community measurement clock was verified; very few independent stations,
short environmental coverage, quantized airport labels and uncertain UTC offset.

Conclusion: integrity safeguards implemented; useful pre-METAR skill remains
INSUFFICIENT DATA. No validated information advantage claimed. Next: retain the
prospective stream, inspect valid coverage over days, and freeze any future cohort
changes before evaluating them.


## 2026-10-25 — Milestone1.6.2 active sensor recovery

Baseline: read-only root-cause investigation established empty latest responses,
not parser failures or relaxed timestamp semantics. At controlled stop5464 OSM
normalized records included4036 empty polls. Hypothesis: actual latest-reading
preflight and versioned operational cohorts increase usable coverage without
weakening integrity. No future prediction outcomes enter selection.

Method: separate poll outcomes from source measurements; raw-first per-box latest
preflight over the four existing20km airport regions; strict300s measurement
clocks/physical/exposure checks; cap4 distinct provider station records with
one sensor each; bounded inactivity/recovery hysteresis. Repeatable additive
migration was rehearsed on a consistent backup and verified after graceful stop.

Observed12:42:26Z:216 sensor poll attempts,103 NO_MEASUREMENT outcomes,0 new empty
normalized records,109 new timestamped numeric measurements,72 fresh outdoor
measurements. Selected station/sensor counts EDDM4,EHAM3,EPWA4,EGLL3. Warsaw
preflight checked107 temperature instruments across104 temperature boxes;27
passed a latest check, versus the old cohort's single useful provider station.
Freshness expires: only4 Warsaw instruments remained currently eligible at the
snapshot; this is not evidence all27 remained live simultaneously. Forecasts use
only the selected sensors and as-of eligible receipts.14 old station records
were deselected,12 added,2 retained; all historical rows and forecasts preserved.

Operational validation:199 tests, Ruff/format and strict mypy passed. Task running
with new code; actual T−10 forecasts record selection versions;18 settlements
appended after restart. SQLite integrity/foreign keys and historical-row
preservation pass. Existing hourly QC blocked the writer for about164s; one AWC
timeout was isolated while other providers continued. These are limitations, not
hidden successful continuous coverage. See docs/PWS_RECOVERY_VALIDATION.md.

Decision: operational recovery deployed. EXP-0006/0007/0008/0009 remain OPEN;
INSUFFICIENT DATA for improved prediction accuracy or an information edge. Next:
collect prospective data, assess cohort freshness/coverage over days, separately
address shared-writer QC scalability, and review clock uncertainty before latency
claims. Qwen usage and rejected proposals recorded in the existing audit.


## Milestone1.6.3 — QC isolation and nearest EPWA sensor,25Oct2026

Baseline: one-worker SQLite queue held full hourly Python QC/transactions;
frozen EPWA187station cProfile run211.769s wall/209.516s CPU. Hypothesis:
shared prepared history and separate private-snapshot analysis reduce repeated
work and release time-critical ingestion. Candidate:10.983s profiled/10.938s CPU,
all187quality rows identical. Unprofiled5.455s is separately labeled. Real-payload
concurrent replay: PWS queue p95/p9914.265/63.568ms, METAR21.559/21.559ms,
publication28.201ms. Original full-history settlement failure retained; measured
receipt and as-of-quality indexes added after EXPLAIN evidence.

Final live4-airport QC cycle20:42:23–20:42:48Z completed while collection ran;
EPWA6.651s calculation,19–451ms writer publication across airports. Whole-run
METAR p95462ms, cold raw-capture p992493ms and checkpoint-delay p951.112s miss
proposed targets: remaining startup settlement/durability/serial forecasting
limitations are explicit. SQL integrity/FKs and preservation of all prior
observations/predictions/settlements pass. Two controlled restarts; original
Windows task retained; no time-setting changes.219tests, Ruff and strict mypy pass.

EPWA exactstation61c1f4ff80a739001cda08bb: initial77 then85 valid readings,
12:34:50–20:41:26Z,10.9–14.6°C, median update327.719s/age82.608s. One BMP180
instrument2.665km from airport;25h Warsaw DST day preserved.17quantized-reference
pairs show evening warm disagreement. Five observed cooling transitions had
matching PWS trend direction but no timely matching new integer; persistence
also failed these changes. Existing forecasts remain immutable,135linked inputs
do not establish causal improvement. EXP-0006/0007/0008/0009 remain OPEN;
INSUFFICIENT DATA for robust accuracy or information-edge claims. Next: measure
multi-day operation, cold-start latency, matched baseline comparisons and clock
uncertainty. Reports: reports/performance/qc_root_cause.md,
qc_benchmark_before_after.md; reports/daily/EPWA_2026-10-25_nearest_sensor.md.
Actual Qwen:2tasks, one partially adapted helper, one rejected test proposal;
17.439s/2465tokens; final tests/architecture independently reviewed.


## Milestone1.7 — EPWA sensor quality and incremental information

Frozen protocol docs/research/EPWA_M17_PROTOCOL.md precedes implementation/results.
Baseline59c377c; consistent backup26Oct12:26:35Z, SHA256706dd79d7f8a7fe6e689cc61489abadd3851523864a07e09b5966082356a4c1c.
H1 absolute PWS; H2 causal interval-residual median correction48h/min12prior
received outcomes; H3 previous METAR plus same-instrument change. Fixed four
provider stations; no retrospective selection or production changes. Compare
against same-target persistence/recent METAR trend; separate T−60 and T+60 replay
from genuine immutable forecasts. No random split or ML.

Observed first-receipt-valid records: Cybernetyki7/BMP180252, Czerniakowska/DHT11246,
SaveDnipro/BME280253, Przekorna/BME280280. Two stale receipts excluded. Median
updates327.15/342.73/333.48/298.01s; ages51.97/81.65/113.43/61.54s. All four
selected under original cohort3. Metadata saysoutdoor/fixed consistently across
stored discoveries, not physical installation verification. Observed decimals
are not accuracy: BMP180-labelled outputs have0.02Cdistinct steps versus0.1C
manufacturer reference conversion. No mounting/shielding evidence.

On46 shared measurement-time METAR cycles, mean absolute rounding-interval
distances1.233/1.513/0.215/1.320C respectively: SaveDnipro best meteorological
agreement, no predictive advantage shown. Raw and causal calibration models
fail to beat matched persistence. H3 T−60: Cybernetyki18/20 vs17/20 persistence,
Czerniakowska11/14 vs12/14, SaveDnipro9/13 vs9/13, Przekorna13/18 vs15/18.
Correct changed integers1/3,2/2,0/4,1/3; false alarms on unchanged cycles0,3,0,3.
These station percentages have different target sets and are not a valid ranking.
All-four shared targets: raw9, calibrated5, change1: INSUFFICIENT DATA for a
predictive ranking. Operational ordering follows preregistered validity/coverage/
age/gap lexicographic rules: Przekorna,SaveDnipro,Cybernetyki,Czerniakowska.
No arbitrary combined predictive/operational score.

Actual current-cohort forecasts1255 across43cycles; at T−60 productionnearest5/42,
median2/42,inverse-distance6/42 versus recorded persistence35/42 on SAMEtargets.
All-history eligible2345forecasts/90cycles;324excluded/unsettled including12
pending. Actual records remain untouched. A reconstructed25Oct21:30Warsaw
Cybernetyki change−0.6C would predict9C from previous10C before receipt, but H3
was not running live; actual nearest forecast11C was wrong. This is a hypothesis,
not a prospective success. Correct replay changes and false alarms are exported.

Ten prior unavailable checkpoints: six NULLquality-score weighted models,
fourEGLL T−180 methods lack selected readings<=300s; airportcountsEDDM3/EGLL6/
EHAM1/EPWA0. Original exceptions/gate state not recorded; attribution is a durable
state reconstruction. No scheduler defect demonstrated or production change made.

Verification: uv sync --locked,242tests19.60s,Ruff/format93files, strictmypy45
production+3researchfiles pass. Independent review added regression safeguards
for COR receipt versus initial outcome availability and future-event previous
METAR; no affected COR-order case in this snapshot. At12:56:31Z same collector
run/PID54608 with fresh heartbeat, existing taskRUNNING,112newvalidPWSmeasurements
across airports since snapshot. SQLite integrityok/FKs empty;0old raw/observation/
arrival/prediction/settlement/selection rows changed or removed. No restart.
Qwen3boundedtasks24.800s/3966tokens:2rejected, documentationpartiallyadapted;
substantive analysis/tests independently verified. No savings claimed.

Decision: H1/currentproduction does NOTimprove persistence in this short sample.
H2 improves raw readings but not matched persistence. H3 is a provisional research
candidate only; no robust edge. EXP-0006/0007/0008/0009 remainOPEN. Next: prospective
shadow evaluation of a preregistered change rule over more changing weather/days,
without replacing the production cohort from this evaluation set. Reports under
reports/research/epwa_station_comparison.*; no trading or paid API changes.


## EXP-0010 — Early METAR Temperature Reconstruction from Calibrated PWS

Question: can already captured nearby temperatures, causally corrected, identify
an upcoming METAR integer before our earliest full-report receipt, including
post-observation/pre-receipt opportunities? Distinct from30min forecasting.
Status: OPEN / EXPLORATORY; observed information-availability cases, no validated
reliable edge or deployment. Baselinea473f6c. Protocol written before results:
docs/research/EXP0010_PROTOCOL.md.

Hypothesis: systematic local offsets can conceal useful temperature information;
median correction from previously received reference cycles may reveal it.
Data: consistent online backup26Oct2026T19:06:15.753046Z, SHA256666b06cad15c99b9fe8442dca27b67a180187dfbf9b03c398790860a158fb99f.
EDDM/EHAM/EPWA/EGLL106/107/104/106uncensored target cycles.120instruments audited,
46with timestamp-valid records,39with eligible reconstructions;19with>=12causal
pair cycles. All available nearby stored sensors included, not only current
production cohort. Sensor.Community ingestion clocks remain ineligible.

Method: CAL0raw; CAL1median midpoint offset allprior data; CAL2rolling12h,
minimum12different earlier nominal cycles. Integer reference remains quantized,
offset±0.5C describes rounding ambiguity only, not confidence or all measurement
uncertainty. Pair PWS asof earlierinitial outcome receipt, sameinstrument,within
5minnominal. Calibrationoutcome receipt<decision, nominal<target; no target/future
references. Strict300s policy unchanged. Referenceclosure earliestANY provider/COR,
includingearlyKNMI; censored/ambiguousinitial outcomesexcluded. FixedT−600/300/180/
120/60,T+30/60/90; latestactualeligible receiptsbyphase and allreceipt/expiry/
metadata/calibrationboundarytrajectories. Oldpreinput isnot relabeledEXP-B.
Reconstructed decisions are RETROSPECTIVE_AS_OF_RECONSTRUCTION, not backdated
immutableforecasts. Same-targetpersistence/raw comparisons; gains/harms/falsealarms
and firstcorrect versuscontinuousfreshcorrectsuffixreported. NoML/affine/tuning.

Results: calibratedincremental examples exist atALL4airports. EDDM esride_krb1,
station5beb063756a15500193139f0/sensor5beb063756a15500193139f7,16.398km:
CAL2T−60 22/38 vsraw21/38,persistence21/38;gain8/harm7/net+1. LatestactualEXP-B
CAL2 19/33 vspersistence18/33,gain6/harm5/net+1. Themore favorableT+90subset17
cycles/net+4 is exploratory, not an independently validated selection. EPWA
SaveDniproCAL2T−60 11/17 vsraw6,persistence10,gain5/harm4/net+1. EGLLwd3-5CAL2
T−60 17/26 vsraw11,persistence19,gain3/harm5/net−2. EHAMCAL2latecheckpointshave
no sample; earlyKNMIcloseswindow. DiemenCAL1T−300 9/21 vs14persistence,gain4/harm9.

Realexamples: EDDM25Oct21:20Z previous7C,PWS7.30C withpriorbias−0.43→7.73→8C,
received21:18:52Z, METAR8Cfirst21:23:45Z,293.090slead. EHAM26Oct08:55Z previous12,
PWS12.13−0.775→11.355→11,receipt08:47:57,earliestKNMI08:52:11 BEFOREnominal,
254.461slead. EPWA26Oct15:00Z previous11,PWS10.49−0.64→9.85→10,277.020slead
(rawalsoalreadycorrect). EGLL26Oct11:50Z previous12,PWSmeasured11:50:47/received
11:51:07,12.39−(−0.68)→13.07→13, officialfirst11:54:59,232.314sEXP-Blead.
Theseareoutcome-conditioned selectedexamples,not independent successrates.
Eightuniquesuccesscycles plusfourSAMEsensor/methodfalsealarmexamples exported;
earliercorrectcompanionstates ofsamecyclesmustnot becounted asextraevents.
Firstcorrects atT−10left-censored bysearchwindow andofteninterrupted byfreshness
expiry; stablecorrects later, not all15minofapparentlead continuouslyusable.

Actualimmutableproduction audit separately: validforecasts EDDM2808/EHAM1639/
EPWA2757/EGLL2649,distinctcycles106/107/104/106;excluded236/154/312/248;42EHAM
pending. ActualnearestT−60 correct/persistence matched:22/82vs52/82,2/7vs4/7,
14/82vs53/82,25/75vs48/75; nets−30/−2/−39/−23. FourEHAM targetalreadyreceived
forecastsremainexcluded. Originalmethodsnot relabeled asnewcalibrationrules.

Limitations: shortcorrelatedhistory, manyairports/sensors/methods/checkpoints,
nonuniformavailability, hardware/exposure/microclimateunknown, quantizedreference,
clockverificationUNKNOWN, referencefirstreceipt isOURS notglobalpublication.
No statisticalsignificance/reliableedge claimed. CAL2EDDM is only a future-shadow
candidate: emit everynewvalidmeasurement, medianprevious12h/min12pairs,roundtoward
warmerexactties,closeonanytargetreceipt,recordactualcompletiontime. Nooraclelast
receipt, no retrospectivestationselection. Freezebeforefuturetest; recommend>=7
newdays/200matchedcycles/30transitions, reportallmissesandfalsealarms. NOTDEPLOYED.

Verification:294tests passed; Ruff/format104files, strictmypy45production+8research
files pass. Offlineanalysis~18s onfrozenDB; currentcollectorunchangedPID54608,
same run20261025T203720939894Z-d9e7826e; existingWindows taskRUNNING. At19:44:53Z
liveintegrityok/FKempty;0oldraw/observations/arrivals/predictions/settlements/
selection/calibration rowschanged/deleted;124newvalidPWSmeasurements sincesnapshot.
No production/source/config/migration/restart/clockchanges. Qwen1SQLreview adapted,
2.086s/576tokens;healthseparate31tokens; no savingsclaim. Reports:
reports/research/early_metar_reconstruction.md/csv,early_metar_examples.csv,
early_metar_sensor_ranking.csv,early_metar_stability.csv andtimelinePNG.


## EXP-0011 — HighTempTation public shadow copy and reconstruction

Status: OPEN. Prospective monitoring began27October2026.
Question: can publicly detected executions be copied at available prices, and
which competing information or microstructure hypotheses explain them?

Data: exact public profile association verified; separate immutable SQLite public
Gamma metadata, Data APIv2 trades/activity/status, CLOB full books/deltas and
unattributed tape. Initial full history:12keyset pages,11861economic fingerprints,
4950BUY/6911SELL,4718conditions/4724tokens,5March through27October08:50:59Z.
8692TMAX/3158TMIN/11other. No common fill/log ID; duplicate partition ambiguity
remains documented. Source time is whole-second block time, not decision time.

Method: independent process/WAL/OSlock/task; bounded128tradequeue/240pending
jobs/256tokens. Source, endpoint first receipt, creation, request and book clocks
remain separate. Raw first, immutable fingerprints and conservative copy groups.
Initial trades-only detector captured Ankara; final detector races both public
wallet feeds every3s. Nontrade activity cannot trigger orders. Bootstrap/restart/
outage catchup remains censored. COPY-HOLD/FOLLOW/frozen TP+0.05(cap0.99),
6delays and4budgets are alternative scenarios, not72independent observations.
Actual post-deadline REST depth, verified token/open state and explicit zero fee
schedule; nonzero/unknown fees prevent certified net economics.

Observed first prospective case: AnkaraNO16C27October. BUY38.35at0.98, source
09:22:30Z, received09:22:33.012009Z; SELL38.35at0.99 source09:22:35Z, received
09:22:38.983181Z. Approximate source-to-detection ages3s/4s; API positively
attributed both to taker, chain role/order placement unverified. The two public
cash flows differ0.3835USD gross, not original net/whole-position PnL.
All6actual direct-copy book windows had asks:[] and best bid0.99. Actual delays
from detection0.670366/1.400689/3.308606/5.342763/10.315210/30.625772s.
72NO_LIQUIDITY variant rows, zero copied positions, zero exits. No available ask
is invented or backdated. One case cannot establish global copy profitability.
Ankara context WEATHER_NOT_MONITORED; no retrospective weather substituted.

Historical characterization: TMAX3433BUY,3417with strictly later same-token SELL,
median8s;2322within10s. TMIN1507BUY,1481with laterSELL,median5s;1353within10s.
These are descriptive row intervals, not inventory attribution or liquidation.
Both extrema matter; a universal Tmax-only explanation is inadequate. H1-H7
remain competing. Prior EHAM KNMI receipt427.275458s beforeAWC demonstrates
possible feed differences, not HighTempTation's source. No archived forecast or
verified Ankara as-of settlement statistic establishes H1-H4. Fast turnover and
empty copy asks make execution/microstructure a priority for future tests.

Operational cutoff09:37:53Z:11865fingerprints(595bootstrap,11268historical,
2prospective),45activity records(44TRADE,1REDEEM),72entry attempts, zero lots.
Only one independent live market case. Two recoverable SERVICE_STATUS network
errors(ConnectTimeout/ReadError), polling continued. Six controlled research
reloads tested recovery; intervening catchup is censored. The corrected weather
context path comes from active config(data/continuous-v1.sqlite3), not legacy
standalone DB. No evaluated weather result used the wrong DB.

Verification:462tests passed21.57s, Ruff/format136files, strictmypy57modules,
uv sync locked48packages. Research integrity and weather quick_check bothok.
Actual read-only EGLL diagnostic yielded100recentofficialrows/1eligiblePWS/
1storedcausalcalibration at diagnostic time, not at Ankara execution.
Weather run20261025T203720939894Z-d9e7826e/PID54608 remained running unchanged;
latest METAR09:33:50.582164Z/PWS09:37:50.155409Z. Separate logon task
MichuplPreMetar-TraderShadow-v1 running Limited/Interactive/IgnoreNew, no password.
No weather migrations, QC/model/selection/forecast writes or clock changes.
LocalQwen2reviews rejected after independent checks,14.217s/3410tokens plus
health0.553s/31tokens; no savings claimed or runtime inference dependency.

Limitations: clock offset UNKNOWN, source-second timing, bounded book coverage,
REST opportunities are conservative rather than proven fastest execution,
nonzero fees UNKNOWN, incomplete weather geography, original order placement
unobservable, correlated market/day samples, long-duration validation pending.
Next: retain all future executable/missed copies and outcomes per frozen policy,
compare paired public-feed latency, audit exact settlement/legitimate weather
availability for traded cities. No real orders or production behavior changes.
Reports:reports/trader/hightemptation_initial_findings.md, required activity/
latency/shadow/weather/forensics/hypothesis outputs, book_windows/endpoint_race
CSVs and operational JSON.

## EXP-0012 — Tmax timing, limit exits and trade microstructure

Hypothesis: HighTempTation buys NO near expected Tmax and passively exits higher.
Data: frozen27Oct2026 read-only snapshots,11867public economic rows,4751NO weather BUYs, two saved Polygon receipts and hashed current official ExchangeV2 source. Neither monitor was restarted or changed.
Method: conditional trade-only FIFO, exact quantity closure, quarantine ambiguous tokens/oversells/nontrade activity; fixed price/time probes; UTC-day block resampling. No complete inventory ledger exists, so all historical FIFO remains conditional.
Results:4738cleanNO BUY lots,4271exact closures,467unclosed trade-ledger lots;6smedian source-block interval. Closed-only rates5/10/30/60s:35.92/79.23/91.55/92.46percent. Around0.90,305/395close higher in3–15s, but zero satisfy the fixed1–3cent improvement probe. Exact0.98is the mode878/4751. Same-city-dayTmaxNO14–16:833/3261(25.54percent), not measured forecast-Tmax alignment.
Ankara: chain-verified taker entry AND exit,38.35shares0.98to0.99,+0.3835pUSD after zero observed exchange fees, excluding gas/relay/rebates. Entry matches four sibling YES BUYs at0.02 via supported mint path; empty direct NO asks did not exclude this liquidity. Corrects EXP0011 interpretation without changing its historical records or runtime model. Warsaw loss counterexample:−136.05935gross; no whole-history net-profit claim.
Limitations:6863/6914SELL roles unknown; no proven passive placement or archived causal forecastTmax; no continuous pre-BUY sibling books; source seconds are block clocks, not decision/placement times. Unclosed lots and incomplete transfer/redemption history prohibit portfolio-return/win-rate conclusions.
Conclusion: fast higher exits repeat, passive-limit and weather-trigger explanations remain unresolved. One mint/aggressive route is evidenced, not a general profitable copy rule.
Next: freeze a bounded both-outcome watchlist, capture valid pre-entry depth, causal forecasts and no-trade controls in a separately authorized future experiment; no automatic activation.
Verification:547tests passed23.13s; Ruffcheck/format152files; strictmypy57production+15researchfiles. Snapshots quick_checkok. LocalQwen1accepted task4.327s/795tokens plus health0.606s/31tokens.
Artifacts:reports/trader/hightemptation_tmax_limit_exit.md and required CSVs, execution-path/depth/accounting audit exports and3charts.
