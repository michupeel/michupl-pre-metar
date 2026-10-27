# EXP-0011 — initial observed findings

Cutoff: 2026-10-27T09:37:53.985735+00:00. Public profile matched HighTempTation/exact requested wallet.
The weather collector was not restarted or modified. Research had controlled
reloads during implementation; catchup remains censored, not relabeled live.

## Historical denominator

The initial full v2 keyset walk completed12pages through2026-10-27T08:56:54Z:
11861 economic row fingerprints,4950BUY/6911SELL,4718conditions/4724tokens,
2026-03-05T03:24:47Z through2026-10-27T08:50:59Z. This is returned public
history, not independently audited fill completeness.8692TMAX,3158TMIN,11other.
For TMAX3433BUY,3417had a strictly later same-token SELL, median8s;2322within10s.
For TMIN1507BUY,1481had laterSELL, median5s;1353within10s. These are descriptive
source-clock intervals, not order decisions, matched inventory lots or net profit.
Five TMAX BUYs also had same-second SELL ambiguity. Missing later SELL is not
proof of holding: redemption/merging and missing history remain alternatives.
Different budget/delay/exit variants are not independent observed transactions.

## First genuine prospective case — Ankara, NO16C27October

|Side|Source block time UTC|First monitor receipt UTC|Price|Shares|Role evidence|
|---|---|---|---|---|---|
|BUY|2026-10-27T09:22:30+00:00|2026-10-27T09:22:33.012009+00:00|0.98|38.35|API_ATTRIBUTED_TAKER|
|SELL|2026-10-27T09:22:35+00:00|2026-10-27T09:22:38.983181+00:00|0.99|38.35|API_ATTRIBUTED_TAKER|

Reported BUY-to-SELL source interval5s. Source-to-detection ages approximately
3s and4s; block timestamps have second precision and local clock offset remains
UNKNOWN. These ages combine indexing/polling/clock effects, not pure network lag.
The38.35share cash-flow difference is37.9665-37.583=0.3835USD gross. It does
not establish original total/net PnL or prove which inventory lot was sold.
No off-chain order-creation clock or independently decoded chain role exists.

|Delay policy(s)|Actual detection-to-book(s)|Best bid|Best ask|Result|Variant rows|
|---|---|---|---|---|---|
|0|0.670366|0.99|NONE|NO_LIQUIDITY|12|
|1|1.400689|0.99|NONE|NO_LIQUIDITY|12|
|3|3.308606|0.99|NONE|NO_LIQUIDITY|12|
|5|5.342763|0.99|NONE|NO_LIQUIDITY|12|
|10|10.31521|0.99|NONE|NO_LIQUIDITY|12|
|30|30.625772|0.99|NONE|NO_LIQUIDITY|12|

Raw HTTP200responses contain asks:[] for the verified exact token. Thus none
of the six recorded direct-BUY opportunities offered an executable ask, including
$10. Four budgets times three exit policies yield72NO_LIQUIDITY rows, but only
one underlying BUY/market opportunity. Zero copied positions, zero exits and no
realized copy profit. No later/missing ask is substituted. This does not prove
there were no transient quotes between snapshots or that copying never works.
Effective zero fee schedule was captured for our decisions; no fee is charged
on a nonexistent fill. Historical trader fees/portfolio PnL are not inferred.

Ankara weather is not covered by the four-airport production DB: both actual
trade contexts are WEATHER_NOT_MONITORED. No later-fetched weather/forecast is
inserted as known at execution. Before our own feed race was enabled, this case
used TRADES_V2 only; it cannot rank activity against trades retrospectively.

## Hypotheses

- H1: legitimate producer feeds can beat aggregators (prior EHAM KNMI/AWC race
 427.275458s), but no recorded Ankara source proves the trader used early weather.
- H2: earlier PWS research has matches and harms; no Ankara sensor evidence.
- H3: forecasts/versioned Tmax probabilities absent. TMIN cohort contradicts
 a universal Tmax-only explanation, not all probabilistic weather strategies.
- H4: exact Gamma rule text preserved; no as-of Ankara settlement statistic.
 No outcome is declared impossible based on integer METAR alone.
- H5: rapid repeated later SELLs and unavailable direct-copy asks make
 microstructure/execution access important. Cause of price changes remains unknown.
- H6: positive API taker attribution for this pair is evidence against simply
 assuming passive fills here; other roles and original placement time remain unknown.
- H7: TMAX/TMIN and timing regimes differ descriptively; hybrid remains a hypothesis.

## Operation and remaining evidence

The separateLimited/logon task continues. Both public wallet feeds now run3s
races with preserved endpoint first receipts and common copy-group protection.
Only paired uncensored observations compare endpoint speed. One copy intent per
wallet/transaction/token/side prevents row repartition/rounding from double-copying.
Nontrade activity is preserved separately and never triggers a BUY.

The initial legacy weather-DB default was corrected before any evaluated weather
context: active config points to data/continuous-v1.sqlite3. The actual Ankara
contexts were explicitly unavailable. A separate read-only EGLL diagnostic
returned100recentofficialrows/1validPWS/1storedcausalcalibration; this was context
at diagnostic time, not information known at Ankara execution.

Two recoverable SERVICE_STATUS network errors were recorded(ConnectTimeout,
ReadError); trade polling and market capture continued. Clock synchronization
UNKNOWN; no time settings changed. New nonzero-fee schedules remain UNKNOWN.
Only bounded256token WS coverage exists; pre-trade depth may be unavailable.
The sole live case does not establish profitability or reconstruct a private strategy.
Full report CSVs retain failures, source clocks and pending/unknown evidence.

Verification:462tests passed21.57s; Ruff/format136files and strictmypy57modules
passed. SQLite research integrity and weather quick_check passed. Existing
weather run/PID54608 preserved. Two localQwen reviews rejected, no repair loop.
See operationsJSON for actual cutoffs/counts and query outputs.
