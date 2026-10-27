# EXP-0011 — prospective HighTempTation shadow protocol

Version: EXP0011-v1, frozen before shadow performance evaluation. Research only.
The production weather process, database, forecasts, QC, station selections and
Windows task remain untouched. This protocol defines the intended experiment;
runtime reports must explicitly identify which capabilities actually ran.

## Questions and denominators

Can a public execution be copied after observed detection plus controlled delays,
and what evidence distinguishes the trader's information source, modeling and
order behavior? Report every detected trade, all excluded/unknown attempts and
coverage, not just profitable examples. Group uncertainty by market/day; related
fills are not independent forecasts. No claim of replicated strategy or profitability
from a short smoke capture or selected historical winners.

## Capture and availability

Verify public profile association with wallet
`0x6011655c4afb76f36dd1b08a137a1ba73466b31e` before capture. Separate SQLite/raw
storage and singleton lock; bounded buffers, restart recovery and short writes.
Persist raw payload before normalization. Only public unauthenticated read APIs
and market-data subscriptions; no keys, signed orders or order submission.

Record run, request start/end UTC, receive UTC and run-scoped monotonic durations.
Preserve integer-second block timestamps and unknown publication clocks. Detection
age = actual first local receipt minus reported source time; it combines upstream
chain/indexing, polling and clock effects and is not pure API propagation latency.
Record service status independently. Startup/history/backfill and outage catchup
must remain censored; they cannot become fresh live signals after restart.

Fingerprint repeated public rows while retaining source responses and ambiguity
when no unique fill ID exists. Keep original first receipt immutable. Cursor pages
retain filters, and incomplete pagination produces an explicit coverage gap.
UNKNOWN role is valid; off-chain order placement remains unobserved even if chain
execution role is established. A public WebSocket trade does not identify a wallet.

## Predefined shadow variants

Independent position-size scenarios: $10, $25, $50, $100 notional; independent
execution-delay scenarios 0, 1, 3, 5, 10, 30 seconds after first live detection.
Do not combine hypothetical scenarios into one funded portfolio or reuse depth
across simultaneous child fills without modeling competition. Record each actual
simulation creation time, target due time, chosen book receipt and market metadata.

Choose the first genuinely recorded executable book available on/after due time,
with receipt after detection and bounded waiting/staleness. It is an observed
execution opportunity at that later receipt, not a fabricated fill at due time.
Reject wrong-token, closed, disconnected, stale, crossed or incomplete books.
No reliable depth means UNKNOWN, not execution at last price. Traverse asks for
BUY and bids for SELL; retain partial quantity, unfilled notional and VWAP. Visible
depth is an optimistic conditional fill estimate, never proof of a real execution.

Fetch exact token identity, active/open order acceptance and effective fee parameters
before estimating net economics. Unknown fee or settlement identity prevents
verified net PnL. Do not treat base_fee as a percentage without verified semantics.
Use decimal arithmetic and preserve the applied fee schedule and rounding.

COPY-HOLD waits for verified final payout. COPY-FOLLOW responds only to later
observed target SELL receipts and never sells more than that scenario holds;
partial allocations and unavailable inventory remain explicit. COPY-TAKE-PROFIT
must use a frozen threshold and prospective bids; it cannot be chosen by maximizing
the same capture's returns. Report any unimplemented variant as unavailable.

## Books, weather and forensics

Prewatch relevant active daily weather markets; unknown future tokens may lack
pre-detection depth. Keep market metadata and subscription coverage. Around a fill,
request offsets −60, −30, −10, −5, 0, +1, +5, +15, +30, +60, +300 seconds from
recorded event time; only contemporaneous recorded states qualify. Mark missing
history UNVERIFIABLE. Block timestamp may lag matching and cannot alone prove a
book precedes the trader's influence. Do not infer causality from price movement.

At detection, use only weather records received by detection, with valid source
clocks and established provenance/freshness. The original rule’s station, source,
unit, local day, Tmax definition, rounding and corrections must match. The highest
integer METAR is not universally the settlement statistic. Unknown rules block
impossibility claims. Calibration requires prior received references and explicit
stored as-of parameters; absent calibration/forecast provenance means unavailable.
This monitor must not invent those fields or alter production weather models.

## Competing explanations and discriminating observations

| Hypothesis | Existing supporting clue | Contradiction or limitation | Future discrimination |
|---|---|---|---|
| H1 early official information | Selected historical entries near nominal cycles | Our aggregator receipt is not global dissemination; no proven private source | Capture legitimate producer and aggregator first receipts before executions, including COR and no-trade controls |
| H2 PWS information | EXP0010 found some causal as-of integer matches | Weak gains and false alarms; no demonstrated source used by trader | Frozen sensor/calibration signals, disagreements and matched trades/no-trades |
| H3 probabilistic Tmax | Prior Mexico City example differed from simple observed crossing | No archived model/forecast decision state proving causality | Archive forecast versions and trade probabilities across full city/day denominator |
| H4 known-information mispricing | Some outcomes may become unlikely after observed temperatures | Impossibility requires exact settlement and correction rules | Exact as-of settlement statistic, impossible and still-possible bucket controls |
| H5 microstructure | Prior selected Taipei depth matched a sweep | Matching depth does not identify signal or prove leader/follower | Independent pre-detection tape, depth, competing wallets and executable copy prices |
| H6 resting limit orders | Execution can follow much earlier placement | Some prior chain evidence indicates aggressor executions; role varies | Verified version-specific matched-order role; placement time remains unobservable publicly |
| H7 hybrid | Historical timing and exit patterns differ across cities | Flexible hybrid explanation risks unfalsifiability | Predefine observable regimes, evaluate held-out days and counterexamples |

These are hypotheses, not conclusions. Historical parent-lab findings are selected
discovery evidence and must remain separate from this run's prospective denominator.

## Reports and stopping interpretation

Report source/executable prices, age, spread, market impact, depth, effective fees,
partial quantities, exclusions, pending positions, realized and unrealized values
separately. Do not call unresolved holdings wins or convert missing prices to zero.
Execution coverage uses all intended attempts as denominator. Win rate/ROI, drawdown,
profit factor and net profitability need complete enough marked/final outcomes;
otherwise INSUFFICIENT DATA or UNKNOWN. Historical target-wallet PnL is separate.
Observe all wins, losses, abstentions, unavailable books and alternate explanations.
Any future live-money use or production change requires a separate explicit request.


## Implementation audit amendment27October

Detection initially used maker-inclusive trades; the first live Ankara case
09:22:30Z was detected in that phase. The final monitor races trades and activity
with independent cursors/censoring and endpoint receipt records. Only future
paired uncensored receipts can compare route speed. RUN records carry code hashes
and detector version; do not relabel the initial case as a dual-feed observation.
One copy intent per wallet/transaction/token/side conservatively avoids double
copying alternate public projections; economic fingerprints remain separate.
Daily TMAX and TMIN histories are distinct;11other historical records are not
weather evidence. Rule/forecast availability remains independently required.
