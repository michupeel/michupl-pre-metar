# EXP0017 — HighTempTation METAR entry timing

Version `EXP0017-ENTRY-TIMING-v1.1`. Frozen EXP0012 + independently frozen current extract.
Snapshot cutoff 2026-10-29T20:04:43.473128+00:00; historical source backfills available no earlier than 2026-10-30T12:26:54.084832+00:00.

**Execution time is not order submission or trader decision time. Nominal METAR time is not public release.**

## Population

4136 weather NO BUY rows; 4136 transaction/token execution clusters (not proven parent orders). 3977 align with archived recurring nominal candidates (original ICAO type unverified); 0 unknown exact stations. Baseline frozen raw trade rows 11867; merged raw economic rows 11950.

**Main price population: 0.90 <= p <= 0.99. All-price control has 4782 rows. 3977 primary alignments have unverified original ICAO report type; strict original-type aligned count is 0.**

IEM's hourly/nonhourly classes do not certify routine versus SPECI. Recurring minute candidates use unique nominal timestamps: at least24 occurrences and at least half the dominant minute frequency, maximum4slots. This source-quality correction is not a tuned trading rule. Raw unknown types stay unknown; off-cadence records are excluded from primary timing.

Hourly-only sensitivity (NOT authoritative routine): {"n": 4092, "schedule_n": 4092, "unknown_station_n": 0, "independent_executions": 4092, "percentages": {"within_30s": 7.3069403714565, "within_60s": 20.01466275659824, "within_180s": 54.37438905180841, "before": 36.87683284457478, "after": 63.09872922776149, "exact_nominal": 0.024437927663734114}, "median_offset_seconds": 52.0, "hist": [{"label": "<-5m", "count": 1069}, {"label": "[-5m,-3m)", "count": 166}, {"label": "[-3m,-1m)", "count": 212}, {"label": "[-60s,-30s)", "count": 24}, {"label": "[-30s,0s)", "count": 38}, {"label": "[0s,30s)", "count": 252}, {"label": "[30s,60s)", "count": 476}, {"label": "[1m,3m)", "count": 1222}, {"label": "[3m,5m)", "count": 306}, {"label": ">=5m", "count": 327}], "receipt_known_n": 0, "known_before_trade_n": 0, "median_minutes_to_day_end": 785.2833333333333}

Source-quality correction: upstream IEM hourly/reset-time heuristics cannot certify ICAO METAR/SPECI. Earlier prototype counts are not final routine-METAR evidence. Strict type-verified historical analysis is insufficient; recurring-nominal candidate analysis and hourly-only sensitivity are descriptive.

## Mandatory questions

1. Within ±30s / ±60s / ±180s: 9.228061352778477% / 24.515966809152626% / 72.51697259240633%, denominator 3977 economic rows. Unknown alignments excluded explicitly. Whole-second timestamps make threshold membership uncertain within1s.
2. Before / after / exact nominal: 18.606990193613278% / 81.367865225044% / 0.025144581342720643%; median signed offset 73.0s.
3. Matched background clustering: **NOT IDENTIFIABLE**. {"status": "UNMATCHED_UNIFORM_PHASE_DESCRIPTIVE_ONLY", "description": "No complete market-wide price/liquidity-conditioned denominator; nominal ±60s share / duration-uniform expectation. Cluster bootstrap, not causal or significance proof.", "rate_ratio": 4.891304347826087, "ci_low": 4.616905585763718, "ci_high": 5.159817351598174, "independent_executions": 3977, "settlement_day_clusters": 3841, "cluster_by": "market_day", "seed": 17, "matched_market_activity_status": "NOT_IDENTIFIABLE"}
4. Exactly0.98 (strict Decimal equality, no near-tick merging): {"price_bucket": "EXACT_0.98", "n": 892, "schedule_n": 845, "unknown_station_n": 0, "independent_executions": 892, "percentages": {"within_30s": 9.112426035502958, "within_60s": 25.443786982248522, "within_180s": 76.33136094674556, "before": 15.502958579881657, "after": 84.49704142011835, "exact_nominal": 0.0}, "median_offset_seconds": 77.0, "hist": [{"label": "<-5m", "count": 31}, {"label": "[-5m,-3m)", "count": 25}, {"label": "[-3m,-1m)", "count": 62}, {"label": "[-60s,-30s)", "count": 4}, {"label": "[-30s,0s)", "count": 9}, {"label": "[0s,30s)", "count": 66}, {"label": "[30s,60s)", "count": 126}, {"label": "[1m,3m)", "count": 377}, {"label": "[3m,5m)", "count": 96}, {"label": ">=5m", "count": 49}], "receipt_known_n": 0, "known_before_trade_n": 0, "median_minutes_to_day_end": 1148.5, "within_60s_pct": 25.443786982248522, "conditional_fifo_closed_n": 846, "first_later_sell_n": 865, "median_first_later_sell_seconds": 6.0, "median_conditional_full_closure_seconds": 6.0, "closed_gross_loss_n": 0, "closed_gross_pnl": "563.251319916290", "unrealized_pnl": null, "net_pnl": null, "inventory_note": "CONDITIONAL_FIFO_NOT_VERIFIED_OPENING_INVENTORY; FIRST_SELL_NOT_PROVEN_LOT_EXIT"}
5. Time-to-settlement uses rule-supported local day end only; closedTime/endDate are not certified final-resolution times. Price-specific medians below; unknown boundaries remain missing.
6. Airport heterogeneity: 50 exact station groups; see full table and CSV. All-airport pattern cannot be transferred to EPWA.
7. Target first local receipt known 0; target received before/at source trade 0. Earliest trustworthy local source receipt, not historical archive receipt. Freshness and coverage still matter.
8. Price movement vs price level: historical pre-entry book/market-wide transaction denominator generally absent; cannot separate momentum/imbalance from price selection. Prospective sidecar records controls without new external polling.
9. Immediate exit-order placement: **UNOBSERVABLE**. Later SELL execution and conditional FIFO closure are not submission evidence. Opening inventory unknown; net costs not established.
10. H1–H8 remain competing explanations; descriptive timing may support association but cannot establish METAR anticipation, access or causation. No profitable strategy/edge is established.

## By airport (observed nominal reports, economic-row denominator)

|Station|NO buys|Aligned|±60s %|Before %|After %|Median offset s|First local receipt known|
|---|---:|---:|---:|---:|---:|---:|---:|
|CYYZ|79|79|22.78481012658228|2.5316455696202533|97.46835443037975|70.0|0|
|EDDM|33|33|0.0|0.0|100.0|197.0|0|
|EFHK|45|45|77.77777777777777|0.0|100.0|6.0|0|
|EGLC|96|96|0.0|0.0|100.0|246.0|0|
|EHAM|11|11|18.181818181818183|100.0|0.0|-143.0|0|
|EPWA|33|33|0.0|3.0303030303030303|96.96969696969697|125.0|0|
|FACT|189|187|10.16042780748663|77.00534759358288|22.994652406417114|-195.0|0|
|KATL|68|68|19.11764705882353|8.823529411764707|91.17647058823529|77.5|0|
|KAUS|75|75|26.666666666666668|2.6666666666666665|97.33333333333333|75.0|0|
|KBKF|73|73|6.8493150684931505|10.95890410958904|89.04109589041096|559.0|0|
|KDAL|47|47|23.404255319148938|8.51063829787234|91.48936170212765|70.0|0|
|KDEN|1|1|0.0|0.0|100.0|165.0|0|
|KHOU|48|48|25.0|6.25|93.75|79.5|0|
|KLAX|70|70|45.714285714285715|2.857142857142857|97.14285714285714|61.5|0|
|KLGA|132|132|4.545454545454546|9.848484848484848|90.15151515151516|153.5|0|
|KMIA|139|139|19.424460431654676|14.388489208633093|85.61151079136691|81.0|0|
|KORD|65|65|21.53846153846154|6.153846153846154|93.84615384615384|83.0|0|
|KSEA|57|57|35.08771929824562|7.017543859649122|92.98245614035088|69.0|0|
|KSFO|69|69|7.246376811594203|4.3478260869565215|95.65217391304348|103.0|0|
|LEMD|65|65|0.0|3.076923076923077|96.92307692307692|249.0|0|
|LFPB|156|156|0.0|0.0|100.0|86.0|0|
|LIMC|24|24|0.0|0.0|100.0|313.0|0|
|LLBG|123|123|43.08943089430894|0.0|100.0|75.0|0|
|LTAC|137|137|8.02919708029197|1.4598540145985401|98.54014598540147|86.0|0|
|LTFM|86|86|12.790697674418604|0.0|100.0|84.0|0|
|MMMX|218|100|37.0|35.0|65.0|21.5|0|
|MPMG|131|130|18.46153846153846|63.84615384615385|35.38461538461539|-71.0|0|
|NZWN|181|181|4.972375690607735|90.05524861878453|9.94475138121547|-86.0|0|
|OEJN|68|68|89.70588235294117|7.352941176470588|92.6470588235294|9.0|0|
|OPKC|109|107|1.8691588785046729|14.953271028037383|85.04672897196262|83.0|0|
|RCSS|364|362|46.68508287292818|0.8287292817679558|99.17127071823204|63.0|0|
|RJTT|55|55|1.8181818181818181|1.8181818181818181|98.18181818181819|123.0|0|
|RKPK|76|75|40.0|24.0|76.0|34.0|0|
|RPLL|95|94|28.72340425531915|0.0|100.0|152.0|0|
|SAEZ|144|143|9.090909090909092|0.0|100.0|148.0|0|
|SBGR|163|162|11.728395061728396|91.9753086419753|8.024691358024691|-197.5|0|
|UUWW|36|35|51.42857142857143|0.0|100.0|52.0|0|
|VILK|195|194|57.21649484536083|13.402061855670103|86.5979381443299|43.5|0|
|WMKK|125|125|0.0|4.0|96.0|210.0|0|
|WSSS|81|81|80.24691358024691|1.2345679012345678|98.76543209876543|52.0|0|
|ZBAA|33|33|72.72727272727273|3.0303030303030303|96.96969696969697|43.0|0|
|ZGGG|11|10|30.0|20.0|80.0|53.5|0|
|ZGSZ|1|1|100.0|0.0|100.0|41.0|0|
|ZHCC|12|12|33.333333333333336|0.0|100.0|62.0|0|
|ZHHH|12|12|66.66666666666667|0.0|100.0|48.5|0|
|ZSJN|25|0|None|None|None|None|0|
|ZSPD|11|11|9.090909090909092|9.090909090909092|90.9090909090909|65.0|0|
|ZSQD|31|31|25.806451612903224|0.0|100.0|62.0|0|
|ZUCK|15|13|84.61538461538461|0.0|100.0|42.0|0|
|ZUUU|23|23|65.21739130434783|0.0|100.0|47.0|0|

## Price and day-end cohorts

|Price bucket|Rows|Aligned|±60s %|Median signed s|Median minutes until rule-supported day end|
|---|---:|---:|---:|---:|---:|
|0.90_TO_0.95_INCLUSIVE|895|867|24.567474048442907|76.0|691.4166666666666|
|ABOVE_0.95_BELOW_0.98|2277|2194|24.38468550592525|71.0|683.5916666666667|
|ABOVE_0.98_BELOW_0.99|60|59|15.254237288135593|82.0|None|
|EXACT_0.98|892|845|25.443786982248522|77.0|1148.5|
|EXACT_0.99|12|12|25.0|61.0|None|

## Execution evidence

{
  "first_sell_known_n": 4103,
  "conditional_full_closure_n": 3794,
  "sold_at_099_n": 3335,
  "inventory_status": "UNKNOWN_OPENING_INVENTORY_CONDITIONAL_FIFO_ONLY"
}

Conditional gross-only FIFO; fees/gas, prior inventory, open remainder and simultaneous records prohibit claiming verified net profits. Known Ankara BUY/BUY mint entry and taker SELL proof is joined only by exact transaction/token/side/quantity. Unknown block/log fields stay NULL. Exact prices may be economic-row VWAPs.

## Representative real records

Selection is deterministic: first two in each price/closure cell, first five EPWA, first three conditional gross losses and ambiguous cases, exact chain-proven entries, and last three EHAM. Not maximum-profit examples. Full identifiers/roles/flags in execution_examples CSV.

|UTC execution|Station|Price|Nominal offset s|First later SELL s|Conditional gross PnL|Status|
|---|---|---:|---:|---:|---:|---|
|2026-05-23T07:01:15+00:00|VILK|0.9478224179|75.0|885.0|2.789690000271|CONDITIONAL_FIFO_CLOSED|
|2026-05-24T04:52:02+00:00|KLGA|0.9325936367|62.0|1975.0|11.542090005173|CONDITIONAL_FIFO_CLOSED|
|2026-05-22T17:58:13+00:00|SBGR|0.9630723627|-107.0|222.0|2.060449999155|CONDITIONAL_FIFO_CLOSED|
|2026-05-23T05:38:28+00:00|RKPK|0.9556313993|-1292.0|543.0|4.447450001785|CONDITIONAL_FIFO_CLOSED|
|2026-08-20T09:51:24+00:00|LTFM|0.9836594174|84.0|3.0|1.537739999824|CONDITIONAL_FIFO_CLOSED|
|2026-08-20T22:58:22+00:00|LIMC|0.9886450775|502.0|21.0|10.723039994875|CONDITIONAL_FIFO_CLOSED|
|2026-04-02T22:17:49+00:00|VILK|0.6799999728|-731.0|526.0|0.569412993600352|CONDITIONAL_FIFO_CLOSED|
|2026-04-02T22:23:11+00:00|VILK|0.699999972|-409.0|76.0|1.940001474000128|CONDITIONAL_FIFO_CLOSED|
|2026-05-22T10:51:06+00:00|EFHK|0.98|66.0|990.0|0.5700|CONDITIONAL_FIFO_CLOSED|
|2026-05-23T17:55:15+00:00|KMIA|0.98|135.0|7.0|0.28728|CONDITIONAL_FIFO_CLOSED|
|2026-08-21T08:20:25+00:00|LTFM|0.99|25.0|5.0|0.16821|CONDITIONAL_FIFO_CLOSED|
|2026-08-23T02:01:10+00:00|RCSS|0.99|70.0|242.0|0.03006|CONDITIONAL_FIFO_CLOSED|
|2026-05-22T09:52:19+00:00|LTFM|0.9420032302|139.0|9.0|1.778869185458|UNRECONCILED_OR_OPEN|
|2026-05-23T10:20:38+00:00|EFHK|0.9272560786|38.0|569.0|7.581897613552|UNRECONCILED_OR_OPEN|
|2026-05-22T01:00:37+00:00|RCSS|0.969999999|-1763.0|467.0|0.5858000202|UNRECONCILED_OR_OPEN|
|2026-05-22T12:57:23+00:00|SBGR|0.9779999998|-157.0|11.0|1.683360016032|UNRECONCILED_OR_OPEN|
|2026-05-20T01:56:31+00:00|RJTT|0.9889999901|-209.0|5595.0|-0.049489990001|UNRECONCILED_OR_OPEN|
|2026-08-21T02:24:06+00:00|EGLC|0.988|246.0|6.0|1.0814410360030050|UNRECONCILED_OR_OPEN|
|2026-05-22T01:30:59+00:00|RCSS|0.8942965762|59.0|868.0|2.294052015458|UNRECONCILED_OR_OPEN|
|2026-05-22T02:00:26+00:00|RCSS|0.8273366804|26.0|362.0|6.099197745388|UNRECONCILED_OR_OPEN|
|2026-05-24T17:52:58+00:00|KATL|0.98|58.0|None|None|UNRECONCILED_OR_OPEN|
|2026-05-28T06:31:41+00:00|RCSS|0.98|101.0|817.0|0.417630070|UNRECONCILED_OR_OPEN|
|2026-09-09T15:55:13+00:00|SBGR|0.99|-287.0|None|None|UNRECONCILED_OR_OPEN|
|2026-09-10T16:54:24+00:00|KLAX|0.99|84.0|None|None|UNRECONCILED_OR_OPEN|
|2026-05-26T12:39:17+00:00|EPWA|0.9558078192|557.0|1389.0|17.713977189696|UNRECONCILED_OR_OPEN|
|2026-05-26T22:02:09+00:00|EPWA|0.9722611456|129.0|11.0|5.643769998208|CONDITIONAL_FIFO_CLOSED|
|2026-06-01T12:02:05+00:00|EPWA|0.9047382274|125.0|461.0|27.683739994894|CONDITIONAL_FIFO_CLOSED|
|2026-06-02T12:32:05+00:00|EPWA|0.8612294735|125.0|482.0|70.5440206380038475|UNRECONCILED_OR_OPEN|
|2026-06-02T12:32:05+00:00|EPWA|0.9530901408|125.0|5000.0|7.17112000704|CONDITIONAL_FIFO_CLOSED|
|2026-04-04T10:58:33+00:00|VILK|0.0191789|-87.0|2106.0|-5.49195951231|CONDITIONAL_FIFO_CLOSED|
|2026-06-11T14:02:10+00:00|EPWA|0.8463987896|130.0|489.0|-82.448899994474|CONDITIONAL_FIFO_CLOSED|
|2026-10-27T09:22:30+00:00|LTAC|0.98|150.0|5.0|0.3835|CONDITIONAL_FIFO_CLOSED|
|2026-09-04T07:52:37+00:00|EHAM|0.9569169896|-143.0|5.0|14.088399978840|CONDITIONAL_FIFO_CLOSED|
|2026-09-09T23:24:39+00:00|EHAM|0.9475141805|-21.0|3.0|4.269400001555|CONDITIONAL_FIFO_CLOSED|
|2026-09-15T21:20:42+00:00|EHAM|0.9775|-258.0|4.0|0.25000|CONDITIONAL_FIFO_CLOSED|

## Method, clocks and unknowns

See docs/research/EXP0017_PROTOCOL.md and SOURCES.md. Every trade belongs to one exclusive price partition and one offset bin or UNKNOWN. Raw TAC/COR and IEM hourly classes are preserved; original METAR/SPECI prefix is absent in all archived rows. No unknown report is certified routine. Nearest actually archived recurring nominal candidate within60min, tie earlier; missing reports create uncertainty, no synthetic timestamps. Cadence/projection exposed separately. Current parsed rule descriptions are exact-contract retrospective identity, never proof trader knew them earlier. Forecast/PWS/book context absent at source time stays UNKNOWN; archived later records never fill that gap. Uniform-phase descriptive contrast is not a matched market-activity test; correlated fills are grouped and uncertainty resamples settlement dates. Missing complete price/liquidity/market-lifecycle denominators prevents a causal or significance claim. Final resolution time remains unknown when only a market closed timestamp is returned.

Sources: [Polymarket market metadata](https://docs.polymarket.com/api-reference/markets/list-markets), [public trade feed](https://data-api.polymarket.com/v2/docs), [IEM raw METAR archive](https://mesonet.agron.iastate.edu/request/download.phtml), [AWC API](https://aviationweather.gov/data/api/). IEM is a university archive of reports, not a verified historical publication clock.

Reproduce: `uv run python -m scripts.research.hightemptation_entry_timing`; source network capture is separate and cached. Reports and static JSON regenerate from frozen files; no collector data modified. New sidecar is public-record observation only, with startup/gap censoring, independent storage and bounded rings. No order execution or model changes.
