# EXP0014 — forecast-realization rules v1.1

V1.1 preserves thresholds and corrects remaining warming to use future same-day
points only. A past daily maximum is not remaining warming. Original V1 events
are retained; no paper trades existed before this correction.

Baseline: Milestone2 dashboard commit0c8f8ab. Hypothesis: repeated causal
temperature and categorical cloud disagreement can identify departures from the
ICON trajectory before relevant market repricing. This qualitative state is not a
probability, a validated confidence interval, a trading direction or evidence of
incremental profit. Keep unsuccessful states and unchanged/normal conditions.

Implementation is pure `premetar.research.realization`; no production policy,
collector process or historical database is modified. Runtime event persistence,
deduplication and chronological source ingestion belong to the isolated experiment
runner. Immutable event records must retain inputs and this exact rule version.

## Availability and reference

For every routine EPWA METAR use the latest explicit ICON Global snapshot whose
first receipt is strictly before BOTH that METAR's nominal observation time and
the earliest report receipt for its nominal cycle. Early reports/corrections cannot
admit a forecast revision obtained after the target was already known. Both METAR
event and first receipt must be no later than the state decision. Never evaluate
an early nominal-future report before its nominal time. Never use a forecast
revision received between nominal observation and report receipt to evaluate that
observation. Forecast age at observation must be at most3hours. SPECI,
startup-censored and collection-gap references are excluded. Latest available COR
replaces a single nominal cycle; it is not an additional independent observation.
Later CORs cannot alter an earlier as-of state or its stored event.

An exact forecast hour is a direct hourly point. A METAR between points uses
linear interpolation across at most60minutes, labeled interpolated. Do not bridge
missing hours. Direction and precipitation/radiation accumulations are not linearly
interpolated as instantaneous point quantities. Unknown model/publication clocks
remain unknown. Duplicate valid-time forecast points reject alignment.

METAR integer k represents [k−0.5,k+0.5), with the upper endpoint open under the
project's nearest/warmer tie convention. Signed residual is the negative of the
forecast's interval-projection error: negative means colder than forecast. Signed
midpoint difference is stored separately and is not exact thermometer error.
Zero interval distance at an open endpoint does not establish an integer match.

## Deterministic states and persistence

Temperature classification uses absolute interval residual r:

|Magnitude|State prefix|
|---|---|
|r <=0.25C|ON TRACK|
|0.25 < r <=0.75C|SLIGHTLY COLDER/HOTTER|
|0.75 < r <=1.75C|COLDER/HOTTER|
|r >1.75C|SIGNIFICANTLY COLDER/HOTTER|

The signed direction follows the residual. A0.15C deadband retains the previous
adjacent same-direction state near a boundary, only when the prior rule version
matches and its creation time is not after this decision. This is engineering
hysteresis, not an optimized scientific threshold.

Confidence needs3 distinct eligible nominal cycles spanning at most2hours.
Current reference age>75minutes or forecast age>3hours gives STALE DATA and blocks
risk/adaptive estimates. An available newest METAR lacking prior forecast alignment
gives INSUFFICIENT DATA rather than silently recycling an older classification.

Rates use actual elapsed time across the3 cycles, restricted to0.5–2hours.
Observed rate is integer-midpoint change/hour with quantization uncertainty
±1C/elapsed_hours. Forecast rate uses a SINGLE trajectory received before the first
observation, so revisions cannot masquerade as warming. Expected rate>=0.25C/h is
warming; <=−0.25C/h is cooling; flatter trajectories remain TREND UNCERTAIN.
Mismatch must exceed max(0.5C/h,1C/elapsed_hours) to classify slower/faster;
otherwise it is AS EXPECTED. Error-trajectory endpoints may use different
appropriate forecast snapshots and are flagged when they do.

With3 fresh cycles, confidence is ON TRACK when median absolute signed residual
is<=0.25C; otherwise MINOR DEVIATION. All3 residuals<=−0.75C establish persistent
cold disagreement; all3>=0.75C establish hot disagreement. FORECAST AT RISK needs
expected hourly-point peak from1hour ago to3hours ahead and either persistent hot
disagreement, or persistent cold disagreement plus WARMING SLOWER or more low
cloud during positive solar elevation. FORECAST HIGH RISK additionally needs
absolute median residual>=1.75C and peak at most1.5hours ahead. A prior risk state
becomes FORECAST RECOVERING when median magnitude<=0.75C and latest magnitude is
smaller than the first of the3. Insufficient/stale observations never grant these
states. Prior states and full evidence are recorded for replay; no probability is
invented.

## Cloud and meteorological parsing

Preserve original TAC, reported temperature/dewpoint, wind direction/speed/gust and
units, visibility qualifier, weather groups and precipitation indication. Unknown
or malformed cloud groups remain unknown; trend/remark cloud groups are not
confused with the current observation. FEW/SCT/BKN/OVC remain categories with
reported base and okta range, not fabricated exact percentages. Vertical visibility
is separately identified. CAVOK, NSC and NCD do not mean a completely cloudless sky.

Model low cloud is an area fraction up to3km. The conservative comparison uses
reported cloud bases<=6500ft and explicitly discloses that these are not equivalent
measurements and cloud tops are unknown. Model fraction<30% plus observed OVC gives
UNEXPECTED OVERCAST; BKN/VV gives MORE LOW CLOUD THAN EXPECTED. Model>=70% plus
CAVOK/NSC/NCD gives FORECAST LOW CLOUD NOT OBSERVED (with reporting-envelope caveat),
or FEW/SCT gives LESS LOW CLOUD THAN EXPECTED. Remaining informative combinations
are BROADLY CONSISTENT. Missing either side gives INSUFFICIENT DATA. No cloud
causality coefficient or claimed added predictive value is inferred.

Astral computes solar elevation for EPWA reference52.163N,20.961E at the actual UTC
decision. Positive elevation is only a daytime context gate; night disagreement
does not automatically imply suppressed warming.

## Experimental adaptive Tmax

Not promoted and never a substitute for validated calibration. Requires3 fresh
cycles, complete exact local-day23/24/25 hourly forecast points, available current
forecast alignment and a peak not already passed. With median signed interval
residual m and hours to peak h:

offset = clip(d*m,−1.5C,+1.5C)

adaptive = max(observed integer maximum−0.5C,
               hourly-point RAW Tmax + offset*exp(−max(0,h)/6))

d=0.5 with one forecast snapshot across residuals, else0.25. The observed maximum
is independently computed from all eligible received routine METAR cycles, not
restricted to forecast-aligned ones. It is neither true daily continuous Tmax nor
verified final settlement. The future peak time is retained as an experimental
forecast time; timing performance is unvalidated. No estimate is displayed after
the peak merely to force a number. Missing history yields EXPERIMENTAL /
INSUFFICIENT DATA. PWS IDs are context only and must pass the existing strict
timestamp/freshness/QC assessment at decision time. No PWS-derived free coefficient
or cloud-effect estimate is learned from this same sample.

The narrow boolean weather_gate requires fresh persistent colder-than-forecast
disagreement, more low cloud, and risk/high-risk confidence. It is merely an
experimental observational filter; alone it does not identify which contract to
buy or establish settlement impossibility. WEATHER therefore may remain SIGNAL-ONLY.

## Acceptance and limitations

Accept the measurement implementation only after deterministic causality/parser/
DST tests. Accept a predictive claim only on frozen future independent settlement
days, matched RAW controls, complete losses and fees. Assess whether deterioration
precedes repricing rather than attributing observed price changes to weather.
Until enough prospective evidence exists: INSUFFICIENT DATA for incremental value.
