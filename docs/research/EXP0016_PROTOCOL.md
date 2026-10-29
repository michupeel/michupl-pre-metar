# EXP-0016 — frozen D−1 research protocol v1

Baseline: EXP0014/15 branch at d1b93aa. This adds a separate tomorrow-horizon
research track. Existing collectors, SIMPLE, WEATHER and HYBRID are unchanged.
Hypothesis: prospectively available D−1 forecast disagreement with executable
contract prices may identify value beyond intraday and Limit99 baselines.
This hypothesis is unproven; model consensus is not a probability.

## Predeclared primary analysis

EPWA only; target date is exactly the next Europe/Warsaw calendar date at the
entry decision. D0 remains a comparison/capture horizon, not a permitted D1 entry.
Calendar day boundaries use ZoneInfo: 23/25-hour DST days are not forced to24h.
Report independent settlement days, not token snapshots, model revisions or
latency variants. Match forecasts, forecast horizon, markets, costs, capital and
settlement days when comparing strategy families. No winner from a partial day.

Primary metric: net return on committed capital over complete settlement days,
including unresolved inventory, failed entries/exits, fees and capital-time.
Secondary: executable coverage, supported fills, drawdown, tail exposure, forecast
MAE, calibration error and chronological out-of-sample net advantage vs RAW/simple.
Acceptance: INCONCLUSIVE until prospectively recorded independent complete days,
verified final target values, auditable forecasts and supported execution exist.
No parameter search, historical best variant promotion or probability from votes.

## Frozen strategies and common constraints

Configuration: configs/experiments/epwa-d1-v1.json, copied/hash-recorded by caller.
Each strategy starts with the SAME100USD comparison budget; variants are separate
portfolios, never summed as independent capital or observations.5USD per entry,
25USD maximum day commitment,3open/pending positions. Exposure bounds include
pending/uncertain BUY debits and all correlated outcomes. Without a certified
mutually exclusive/exhaustive market partition, use full-cost worst-case loss;
never pretend several NO contracts are independent diversification.

* D1_FORECAST_VALUE_V1: eligible D−1 entry, attempt exit at first supported direct
  bid at/after D0 12:00 Warsaw. This is a scheduled observation checkpoint.
* D1_TO_D0_REPRICING_V1: same entry, attempt D0 exit only at a supported executable
  net return >=5%; fallback at D0 end with supported liquidity. Unfilled remainder
  remains inventory through verified settlement; no fictional midnight liquidation.
* D1_HOLD_TO_SETTLEMENT_V1: same entry, hold through verified official resolution.

All three require a calibrated probability advantage >=5percentage points AND
expected net return >=5% using actual direct asks and captured supported fees.
Minimum90% of5USD entry budget must be supported by displayed depth and real tick/
minimum-size constraints. Decision-depth quotes are conditional observations,
NOT arrival fills. Arrival latencies100/500/1000/3000/5000ms require independent
fresh recorded full books at/after arrival, at most2s later, depth age<=5s.
No arrival evidence =>UNKNOWN, never a manufactured fill. Maker queue position is
unknown; no assumed maker fills. Complementary matching remains THEORETICAL_ONLY
unless independently verified for the actual contract/version; do not doublecount.

Entry lifetime60s; cancellation latency250ms. Signal lapse/invalid inputs trigger
cancellation of unfilled entries with latency, not instant cancellation or sale.
No arbitrary all-day resting BUY. No assumed stop-loss execution. Failed/unfilled
exits retain inventory/risk; no selling unowned quantities. Retain all candidate
negative cases and execution uncertainty in immutable events.

## Eligibility and independent calibration promotion

Actual market identity must verify EPWA, local date/timezone, settlement source,
daily maximum definition and rounding. Explicit tail outcome labels are separate
from exact integer outcomes; unknown label semantics block. Latest metadata must
have been received<=decision and age<=1200s; market explicitly open/accepting.
Existing verified_fee is reused: only captured explicit current zero fee schedule
is supported in v1. Unknown/nonzero unsupported schedule BLOCKS economics. No
rebates or 1−YESbid-as-guaranteed-NOask assumption.

Production-facing default is SIGNAL_ONLY_CALIBRATION_PENDING and
calibration_promotion_id=null. A caller passing status=CALIBRATED cannot activate
an entry. An independently reviewed promotion must change the versioned frozen
configuration deliberately, retaining prior history and prospective split.
A future enabled certificate must match its promotion ID, condition identity,
minimum30 independent historical settlement days, matching D−1 horizon bucket,
calibration available<=decision (age<=1h), earlier received official outcomes and
training target dates strictly before both the evaluated target AND the decision's
local calendar day (today's final daily value cannot already be a training label). Audit references to
original horizon forecasts, verified settlement targets and chronological OOS
validation are mandatory, with artifact SHA256 and audit time<=decision.
The certificate is evidence to independently verify, not proof by self-labeling.
Current research must display PROBABILITY_UNVALIDATED, null YES/NO probabilities
and null EV whenever those requirements fail. No strategy is automatically
promoted by this milestone.

Canonical horizon IDs: D1_MORNING (<12:00), D1_AFTERNOON (12:00–17:59),
D1_EVENING (>=18:00) Warsaw local; D0_MORNING and D0_INTRADAY. D0 morning
and intraday separated. No stitched current or later forecast can backfill an
original run. Unknown run/publication times remain NULL; first receipt is the
verified availability bound. Daily API maximum and max hourly points are distinct.
Do not substitute maximum routine integer METAR for official final daily target.

## Research-only utilities

`d1_strategy.evaluate_candidate` is pure and returns both side-specific direct
quotes, all rejection reasons, probability/EV eligibility and strategy versions.
It never persists an order or mutates cash. `exit_policy` returns trigger only,
not a fill. `parse_outcome`, `outcome_wins`, `horizon_bucket` and
`local_day_bounds` provide deterministic testable semantics. The monitor is
responsible for raw-first capture, immutable persistence and distinct prospective
vs historical records. Paper ledger activation remains blocked until calibration
and real arrival evidence meet the frozen requirements.

Known limitation: public books do not establish our own queue/fill or guaranteed
execution. Current candidate records cannot support net profit, best exit,
forecast Tmax accuracy or an empirical NO9C win probability without verified
settlement and original D−1 calibration history. Report these as NOT IDENTIFIABLE.
