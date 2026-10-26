# EXP-0010 — frozen exploratory protocol

Baseline a473f6c; snapshot captured2026-10-26T19:06:15.753046Z,
SHA256666b06cad15c99b9fe8442dca27b67a180187dfbf9b03c398790860a158fb99f.
Written before reconstruction results. All EDDM/EHAM/EPWA/EGLL airport-associated
sensors with any stored records are audited; every timestamp-valid nearby sensor
is evaluated, including unselected sensors, without applying current selection
retroactively. Historical metadata and selection state are queried as of decision.
No production modifications, migrations, restarts, calibration or forecast writes.

Question: can already received PWS, corrected using earlier received airport
references, identify an upcoming integer METAR before OUR earliest reference
receipt? Success requires exact integer equality; compare matched persistence.
Primary summary endpoints: T−60s and LATEST_RECEIPT separately by EXP-A/EXP-B;
all other checkpoints and event search reported, never silently optimized away.

Targets: initial uncorrected routine METARs, one outcome per airport/nominal
clock. Conflicting initial-temperature variants and COR-only targets excluded
with counts; all versions retained for audit. Closure is earliest receipt of ANY
METAR version/COR through ANY configured provider. No prediction at or after
closure, including nominally early KNMI. Startup/coverage-censored initial reports
cannot support lead evidence. Prior baseline uses previous initial routine METAR
with nominal event<=decision and receipt<=decision (initial-version policy;
corrections are retained but not substituted retroactively). SPECI excluded.

CAL-0 raw. CAL-1 median midpoint offset over ALL available earlier independent
nominal cycles for that airport/sensor. CAL-2 same estimator on last12h nominal
cycles. Both require>=12 distinct earlier target cycles, receipt strictly BEFORE
decision and nominal clock<target and<=decision. Pair each past initial METAR with
latest valid SAME-instrument PWS available at its first receipt and within±300s
of nominal time. Freeze pair at this receipt, exclude censored captures. No target
outcomes in training. Offset point=median(PWS−METAR_integer), explicitly a
QUANTIZED_REFERENCE_MIDPOINT_ESTIMATE, not exact continuous bias. Quantization
bounds=offset±0.5C; report these separately. No affine: short history and too few
independent environmental regimes. No threshold/model search after outcomes.

Strict existing provenance, physical/exposure and300s freshness apply at receipt
and decision. Unknown measurement clocks stay unusable. Source event<=decision,
first receipt<=decision; first receipt never replaced. Conflicting duplicates
become ineligible when a second differing value has ACTUALLY arrived, not earlier.
Historical selection flags annotate but do not filter offline candidates.

Decision grid T−600/300/180/120/60s and T+30/60/90s. EXP-A decisions and inputs must
both precede nominal. EXP-B decisions>=nominal require input FIRST received in
[nominal,closure), so old inputs are not relabeled as new post-observation data.
NO_POST_OBSERVATION_RECEIPT distinguished from NO_ELIGIBLE_OBSERVATION. Also
latest actual eligible receipt per window and source-receipt event trajectory
from T−10min to closure. Earliest correct is earliest within this searched window,
not earliest ever. If report is delayed, post-observation event horizon continues
to closure and target/event offsets are disclosed. Every estimate is labeled
RETROSPECTIVE_AS_OF_RECONSTRUCTION, assuming negligible computation time; not a
recorded live prediction and not proof of market-wide publication advantage.

First correct/first stable correct, wrong-to-correct reversals and false alarms
all reported. Stable requires uninterrupted freshness from that decision through
closure (expiry boundaries considered), all subsequent event/grid decisions
correct, and no later loss of eligibility/calibration. Gaps break stability.
Report per-method trajectories and unique target cycles, never sum checkpoints
as independent events. Earliest-correct searches are hindsight diagnostics.

Complete scope: all sensors, all3methods, all8fixed checkpoints plus latest
receipt and event trajectories; statuses include insufficient calibration/no
input/target already known. Summary by airport/sensor/method/decision/window uses
identical candidate and persistence targets. Counts incremental correct, harm,
net and transition false alarms; retain all groups, even unfavorable small ones.
Descriptive sensor ordering by fixed T−60/CAL-2 net, then cycleN; >=30evalcycles
required for provisional ranking. No validated statistical significance/edge from
this short, multiple-comparison search. At least5local days and100matchedcycles
would be needed even for descriptive block uncertainty; otherwise INSUFFICIENT
DATA. Strongest examples choose calibrated incremental wins, one per distinct
METAR cycle, prioritize airport representation then stability then lead, and show
failures. This selection is explicitly outcome-conditioned, not performance proof.

Actual immutable forecasts/settlements evaluated independently using existing
integrity ledger, original models/checkpoints and same-target recorded baseline.
No attribution of causal sensor benefit from mere input inclusion. No model
activation. Any promising rule must be frozen and evaluated on future shadow data.
