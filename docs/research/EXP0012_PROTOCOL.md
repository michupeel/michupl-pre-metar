# EXP-0012 — Tmax timing, exits and execution microstructure

Baseline: `bef6931`, EXP-0011. Both live services remain untouched. Research uses
consistent SQLite backups through read-only connections. Snapshot hashes and UTC
cutoffs are recorded in `data/research/exp0012/manifest.json` and the public report.

## Hypothesis and fixed questions

H1: favorable local Tmax-window NO entry followed by a higher passive limit exit.
Alternatives: H2 aggressive entry/exit, H3 passive entry/passive exit, H4 weather
repricing, H5 intraday mean reversion and H6 heterogeneous mechanisms. Correlated
market/day fills are not independent decisions. No threshold is tuned to profit.

Primary descriptive endpoints: quantity-matched closure within5/10/30/60seconds,
gross price improvement, observed maker/taker evidence, and local14:00–16:00 share
where timezone identity is verified. Actual causally available forecast Tmax time
is distinct from realized Tmax time. Missing archived forecasts or market-wide
historical depth means the corresponding hypothesis is INCONCLUSIVE.

## Inventory and clocks

Use source block UTC seconds, original first receipt, transaction/token/side and
economic-row identity. Preserve ambiguous duplicate projections rather than count
them twice. Rows within the same second lack guaranteed matching order. Token
positions begin UNKNOWN, not zero by convenience. Report a strict subset whose
initial zero inventory is supported by complete observed lifecycle evidence,
and separately report explicitly conditional FIFO reconstruction from available
history. Never call first later SELL a complete exit.

FIFO is a transparent accounting convention, not knowledge of the trader's tax
lots. Preserve partial exits, unsold remainders, oversells/unknown opening holdings,
same-second ambiguity, acquisitions outside the trade feed, and redemption gaps.
Verified net economics require historically applicable fee evidence; current fee
schedules do not establish past rates. Gross-only results stay gross-only.

Price buckets are left-closed/right-open: [0.50,0.70),[0.70,0.80),[0.80,0.90),
[0.90,0.95),[0.95,0.98),[0.98,1.00]. Out-of-range purchases are reported separately.
Natural clusters use exact quoted-price frequencies and fixed0.01bins; no fitted
cluster count optimized against returns. Quick-spread probe: entry0.88–0.92,
fully matched exit3–15seconds later and VWAP improvement0.01–0.03. Report its
full denominator, counterexamples and selection uncertainty.

## Roles, books and Tmax

Positive exact public taker-only matches remain API-attributed, not independently
decoded chain roles. Maker is never inferred merely from absence in a truncated
feed. Aggregated order-book size changes do not establish ownership or placement.
Preserve connection epochs, token/condition mapping, raw full snapshots and deltas.
Do not invent missing depth or carry a disconnected book forward. Empty asks
require verified mapping/completeness and comparison with available raw evidence;
they describe observed direct-ask opportunities, not global absence of liquidity.

Resolve airport/station and local timezone from verified descriptions/reference
data. A location name alone does not establish settlement rules. Local boundaries
use calendar midnights and zoneinfo, including23/25hour days. Current descriptions
are retrospective identity evidence unless captured before the relevant trade.
Forecast and global market/no-trade baselines require their own availability clocks.
Absent historical information is UNKNOWN, not an assumed afternoon Tmax window.

At least five representative requested example categories are attempted; missing
passive-role, historical-book or forecast evidence remains explicitly unavailable.
No simulated orders, model/QC changes, service restarts or live database writes.

## Final accounting and evidence notes

The strict verified-zero-opening subset is empty: no complete transfer/mint/
redemption ledger exists. All FIFO metrics are conditional. Primary closure
requires exactly zero remaining quantity. A2e-6share dust tolerance is flagged
only and cannot create a primary closure. NO weather is the primary cohort;
all-weather YES/NO is an explicit control. Descriptive uncertainty resamples
UTC source days,2000replicates, seed12, without treating each lot as independent.

The report is bound to the exact frozen snapshot SHA256 pair in the manifest.
Two read-only public Polygon transaction-receipt requests independently verify
Ankara's taker roles and zero exchange fees. Current official ExchangeV2 ABI,
implementation and exact captured binary token mapping support BUY/BUY mint
entry. No prior public visibility or creation time of the counterparties' orders
is inferred. A direct-ask-only shadow model omits this route; missing sibling
book continuity prevents a reliable alternative historical fill simulation.
The finding changes research interpretation, not either running service.
