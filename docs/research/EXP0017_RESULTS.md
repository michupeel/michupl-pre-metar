# EXP0017 — observed results and limitations

Final research revision v1.1, 30 October 2026. The original EXP0012 databases
and their checksums remain unchanged. No production strategy, source timestamp,
QC rule, position or prediction was modified.

## Historical sample

11,867 frozen trade records plus a compact independently pinned live extract
produce 11,950 unique economic rows and 4,782 weather NO BUYs. Main price range
0.90 <= p <= 0.99 contains 4,136 BUYs. The 646 cheaper BUYs are separate controls.
The source lookup recovers exact historical contract rules for all 4,540 frozen
NO conditions, spanning 50 explicit settlement stations. Newly captured rules
establish retrospective identity, not historical availability.

3,977 main-range BUYs align with an observed recurring nominal report series;
159 lack usable archive alignment. Of those aligned: 9.23% fall within30seconds,
24.52% within60seconds and 72.52% within180seconds. 81.37% execute after the
nearest nominal time, 18.61% before, one exactly at it. Median offset +73seconds.
There are 3,841 market/day clusters and 161 settlement-date clusters.

**These are nominal-series associations, not verified routine/publication results.**
All299,240 IEM archive records lack original METAR/SPECI prefixes. Its196,057
hourly and103,183 nonhourly labels cannot certify ICAO report type. Upstream IEM
code can reassign the hourly class. Every original type therefore stays UNKNOWN;
primary timing uses recurrent nominal-minute candidates, explicitly type-uncertain.
Strict original-type historical comparisons have zero eligible alignments.
Hourly-only sensitivity is exported, not promoted to authoritative routine truth.

The initial prototype misclassified type4 as SPECI and distorted EPWA :30 timing.
That research parser error was fixed using cached RAW, with no extra observation
requests. No collector record was changed. The v1 prototype and the final v1.1
publication clocks are separate; final revised knowledge is not backdated.

## Airport differences, main range

|Airport|BUYs/aligned|After nominal|Median signed offset|
|---|---:|---:|---:|
|EPWA|33/33|96.97%|+125s|
|EDDM|33/33|100%|+197s|
|EHAM|11/11|0%|-143s|
|EGLC|96/96|100%|+246s|
|LTAC|137/137|98.54%|+86s|
|KLGA|132/132|90.15%|+153.5s|
|LFPB|156/156|100%|+86s|
|RCSS|364/362|99.17%|+63s|

London is EGLC, not monitored Heathrow EGLL. EHAM differs materially from the
pooled pattern. Early producer dissemination and resting orders remain competing
explanations; no contemporaneous first local METAR receipt covers these historical
BUYs. Consequently before-nominal is not proof of before-publication information.

Exactly0.98: 892 economic rows, 845 aligned; median +77seconds and84.50% after
nominal. Purchases span all24 local hours. Rule-supported local-day-end timing is
known for only57 of those892; median1,148.5minutes (19h08m30s), range56.02–1411.35.
This small identified subset does not describe the whole0.98 population. End of
local day, market endDate, closedTime and certified final resolution are distinct.

## Mechanism hypotheses

|Hypothesis|Observed evidence|Unresolved discriminator|
|---|---|---|
|H1 Before nominal|EHAM11/11 before; pooled majority after|Exact first producer/aggregator receipts and order roles|
|H2 After nominal/pre-receipt|Timing consistent with some cases|Historical contemporaneous receipts absent|
|H3 Fresh METAR repricing|EPWA near+125s; several station-specific clusters|Receipt and market-wide repricing controls|
|H4 Near settlement|High prices also occur many hours before day end|Complete rule-supported boundaries/lifecycle controls|
|H5 Price level|0.98 common across all local hours|Eligible-price exposure denominator|
|H6 Momentum/imbalance|Historical before-entry depth generally absent|Prospective full book/trade continuity|
|H7 Heterogeneous mechanisms|Airport offsets differ markedly|Matched prospective samples|
|H8 0.98 need not mean imminent settlement|57 known-boundary cases mostly hours before day end|Selection bias in identified boundary subset|

The ±60second uniform-phase contrast is4.89, with market/day bootstrap interval
4.62–5.16 and day-cluster sensitivity4.58–5.19. This is **not a matched market
activity rate ratio or significance test**. Price range, lifecycle, selection and
trading-hour exposure are not fully observed. No causal clustering claim follows.

Conditional FIFO closes3,794 main-range lots;3 have negative closed gross
price-change PnL. First subsequent SELL and conditional closure medians are6s.
This is not verified opening inventory, true lot allocation, complete costs or
net profitability. A rapid SELL is execution evidence, not exit placement time.
Exact saved Ankara proof supports a taker BUY through complementary mint and a
taker SELL, not a universal maker explanation. Failed/open/ambiguous cases remain
in exports. The example set explicitly includes losses and incomplete positions.

## Prospective study and operation

By30October12:22UTC the separate journal recorded11 genuine NO entries,46endpoint
evidence joins,22role joins and55post-entry samples. Seven source-time anomalies
were rejected, not silently included. No pre-execution or detection-time book was
available for these11 entries; recorded contemporaneous weather state is UNKNOWN.
These are observed entries, not11 proven copy opportunities or11 independent days.
The last10 display cache recovers original immutable evidence; it never recreates
past weather information. Original records remain unchanged.

Weather PID11236, trader11748 and dashboard32732 remain unchanged. Only the new
EXP0017 sidecar was gracefully restarted for its own display/status fixes, with
durable source cursor and11-entry count preserved. Its dedicated current-user
logon task is installed, limited privilege, IgnoreNew, restart60sx3; no password.
No new exchange/forecast requests are made at runtime. Pre-entry coverage remains
limited by the existing watchlist. Control candidates are pending, not falsely
certified no-trade intervals. 500MB total journal budget and free-space guard stop
capture without deleting evidence.

The separate D1 task was found Ready with exit1 on30October; it was not restarted
or reconfigured in this experiment. This is an existing operational limitation,
not a claim that all forecast streams are healthy. Weather/trader/dashboard and
the new EXP0017 observer are running. Clock synchronization remains unverified.

Source acquisition:60successful public requests,61,352,833raw bytes, original
responses/hash/receipt preserved. Qwen endpoint authenticated/models worked but
no model was loaded; test generation HTTP400, no generated result accepted.

Reproduction and data schemas: EXP0017_PROTOCOL.md, EXP0017_SOURCES.md and
EXP0017_OPERATIONS.md. Generated report and exports are under reports/trader/.
The next blocker is a matched market-wide price/liquidity denominator plus reliable
pre-event books, exact market identity and earliest official receipts for the
same trades. No strategy or demonstrated information edge is promoted.
