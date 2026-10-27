# EXP-0012 — Tmax timing, limit exits and microstructure

Retrospective forensic research; no services restarted, no production changes or real orders.

Trade snapshot: 2026-10-27T11:37:17.798402+00:00, SHA256 `6cddb1ee11e6a30d9bc9fac15ba659eb1a1a57045c7809e19db2bca3d3709b89`. Weather snapshot separately pinned 2026-10-27T11:37:22.760234+00:00; clocks are not treated as simultaneous.

Scope: 11867 public economic rows, 4953 BUY lots, 4943 weather BUYs, 4751 NO weather BUYs. Complete returned keyset history is not a complete on-chain transfer ledger. Opening balances remain unverified for every historical token.

## Quantity accounting

Conditional FIFO replaces first-later-SELL pairing. Partial sales, multiple buys and exact remaining quantities are retained. Same-second mixed sides and ambiguous transaction projections are excluded. Tokens with oversells/nontrade activity are flagged. Every reported matching statistic below is conditional on the trade-only ledger; none certifies unknown opening inventory.

Flags by BUY lot: `{"UNKNOWN_OPENING_OR_NONTRADE_INVENTORY": 5, "AMBIGUOUS_EXECUTION_GROUP": 4, "AMBIGUOUS_SAME_SECOND_BUY_SELL": 7, "NONTRADE_ACTIVITY_PRESENT": 1}`. Primary clean NO weather cohort 4738 BUYs; exactly closed 4271; not exactly closed 467. Median exact-closure source block interval 6.0s. Source clocks have second precision and may follow actual exchange matching. All-outcome control: 4926 eligible BUYs/4393 exactly closed; the holding chart includes both YES and NO.

|Interval|Exact closures|% all eligible BUY lots|% exactly closed lots|% purchased share quantity sold|95% day-block interval, all eligible|
|---|---|---|---|---|---|
|5s|1534|32.38|35.92|23.87|27.17–37.24%|
|10s|3384|71.42|79.23|65.69|66.92–75.56%|
|30s|3910|82.52|91.55|84.44|78.91–85.84%|
|60s|3949|83.35|92.46|86.30|79.72–86.55%|

UTC-day resampling uses2000replicates/seed12. Descriptive intervals do not fix non-random history selection, temporal dependence across days or missing transfer inventory. Open lots remain in the all-eligible denominator.

## NO prices and economic results

Buckets are left-closed/right-open;0.98 belongs in the final bucket,1.00 is included. Frequencies and fixed1cent clusters are descriptive, not optimized strategy parameters.

|Bucket|BUY rows|Shares|Notional|Clean exact-closed median(s)|Conditional gross, closed only|Verified full-cost net|
|---|---|---|---|---|---|---|
|BELOW_0.50|16|3524.649858|1129.0528732248730855|9.5|159.2469292162397127|UNKNOWN|
|0.50–0.70|41|30128.685465|19172.1586278194361521|6.0|3690.1000887637040182|UNKNOWN|
|0.70–0.80|125|91505.831172|70005.7179987006224261|7.0|11449.2321243724134855|UNKNOWN|
|0.80–0.90|459|223439.840731|192056.2808831774589745|8.0|22255.2974172314842560|UNKNOWN|
|0.90–0.95|879|337948.938293|313873.6724722198415553|6.0|16331.1090740410462072|UNKNOWN|
|0.95–0.98|2281|503376.949876|486705.8665944667717458|6.0|9900.3214882356685842|UNKNOWN|
|0.98–1.00|950|76525.83899|75125.612098942366679|6.0|708.0218856665112668|UNKNOWN|

Natural exact-price modes: `[('0.98', 878), ('0.97', 84), ('0.96', 31), ('0.9732075472', 27), ('0.9725', 17), ('0.9733333333', 14), ('0.975', 14), ('0.99', 12), ('0.974', 12), ('0.9699999993', 11), ('0.95', 11), ('0.86', 7)]`. Cent clusters: `[('0.98', 1444), ('0.97', 1046), ('0.96', 501), ('0.95', 329), ('0.94', 231), ('0.93', 185), ('0.92', 137), ('0.91', 130), ('0.90', 95), ('0.89', 80), ('0.88', 65), ('0.99', 54)]`. Gross positive/negative/flat clean closed lots: 4387/6/0. Capital and volume totals cover all buys, while gross columns cover only clearly labeled clean closed lots; they are not whole-wallet PnL. No full-cost historical net verified.

Conditional matched portions of still-open ledger lots add gross 35406.2149585483235825; all matched portions total 104496.8540885074813040. Unclosed ledger cost 3257.3090620469985232 is not current wallet holdings or mark-to-market loss: redemption/transfer history is incomplete. Closed-only results can omit settlement losses and must not be quoted as whole-wallet profit or accuracy.

NO entry median 0.9676577664; exact0.98 appears 878times. Of 4271 clean exactly-closed NO lots, 3548 exit VWAPs are within0.000001 of0.99. Executed BUY VWAP is not the original limit price; neither the median nor its clusters establish a predetermined order cap.

Predefined0.88–0.92NO /3–15s /+0.01–0.03 probe: 0 matches out of 395 eligible entry-range BUYs. This describes source-block timing and conditional gross performance, not passive order placement or profitability after unverified costs.

Allowing any positive executed-price improvement instead of only0.01–0.03 yields 305quick higher exits in that same entry-range denominator. This is a separately disclosed broad descriptive question, not a retuned profitability search.

## Roles and passive-exit hypothesis

All recorded rows: `{'UNKNOWN': 11761, 'API_ATTRIBUTED_TAKER': 104, 'CHAIN_VERIFIED_TAKER': 2}`; SELL roles: `{'UNKNOWN': 6863, 'API_ATTRIBUTED_TAKER': 50, 'CHAIN_VERIFIED_TAKER': 1}`. UNKNOWN is retained, and the known subset is selected by recent feed coverage. It cannot determine the maker/taker mix of all historical SELLs.

The positive API subset is explicitly sampled through taker_only=true: all-known-taker is an ascertainment artifact, not an unbiased population estimate. Only transaction-specific verified roles justify a mechanism classification.

Ankara BUY and SELL receipts were independently fetched once each and decoded against the official current CTFExchangeV2 ABI/address. OrdersMatched identifies HighTempTation as taker-order owner in both; the matching aggregate OrderFilled fee is0. This is a real counterexample to a universal passive-limit-exit explanation. Economic price limits on aggressive orders do not make an execution a passive maker fill. Original order creation remains unknown.

The pair exchanged37.583out/37.9665in for38.35shares: +0.3835quoted collateral units after observed exchange fees, excluding unverified gas/relay/rebate costs. Current collateral is pUSD, not an inferred historical USDC balance. Complete realized portfolio profit is not established by this incremental pair.

## Important correction: the entry used the opposite outcome

BUY: `0xcb4232e8436f1a076173d95a7941548bf7abf28f4c768acd56533dff0c0e4ca8`, OPPOSITE_OUTCOME_BUY_BUY_MINT_SUPPORTED; target quantity 38.35, collateral 37.583, counterparties 4.

SELL: `0x4ed9364153849bfcc780c33aec17ab44d0b565d6108204a962ce71827ba4e5b5`, DIRECT_SAME_TOKEN_SELL_TO_BUY_TRANSFER; target quantity 38.35, collateral 37.9665, counterparties 1.

For the Ankara BUY, four maker-side BUY orders on the exact sibling YES token paid0.02per share. Their quantities12.35+5+6+15 total38.35; their0.767collateral plus the target37.583 totals38.35. Both outcomes and condition mapping agree with captured Gamma metadata, and the ExchangeV2 implementation supports BUY/BUY mint matching. This is not a purchase from a direct NO ask. The SELL then matched a BUY on the same NO token at0.99. Original placement times and prior public visibility of these maker orders remain unverified.

Therefore the previous shadow NO_LIQUIDITY result established only that direct asks were empty. Its direct-asks-only model did not assess opposite-outcome mint liquidity. It cannot establish that every native matching path was unavailable, nor that a fast copy could not execute through such a path. Reliable same-epoch sibling depth at our decision time is missing, so that alternative copy result is UNVERIFIABLE. No production collector or shadow engine is changed here.

A future bounded measurement should capture both binary outcomes and compare direct askNO with1-bidYES after validating contract/version, available size, fees and quote freshness. That is a proposed test, not a claim those quotes coexisted or a deployed arbitrage rule.

## Local timing and Tmax

TMAX: 890/3436 BUYs in14:00–16:00city local time (25.90%), notional share 25.78%. Hour counts `{'13': 581, '11': 464, '15': 385, '14': 505, '16': 203, '0': 97, '12': 579, '10': 271, '3': 8, '9': 97, '17': 103, '5': 3, '7': 11, '18': 38, '1': 6, '23': 23, '4': 6, '8': 30, '22': 4, '20': 4, '19': 5, '21': 2, '2': 7, '6': 4}`.

Same city-calendar date as market: 3415; other local dates 21. Same-day14–16 count 890, fraction 0.26061493411420206. These are geographic calendar references, not verified settlement windows for uncaptured rules.

TMIN: 14/1507 BUYs in14:00–16:00city local time (0.93%), notional share 1.74%. Hour counts `{'23': 66, '12': 3, '0': 145, '3': 152, '4': 211, '5': 217, '7': 49, '22': 49, '2': 154, '1': 142, '20': 26, '6': 162, '19': 14, '10': 7, '21': 26, '13': 7, '17': 14, '18': 16, '8': 17, '14': 9, '9': 6, '11': 3, '16': 7, '15': 5}`.

Same city-calendar date as market: 1487; other local dates 20. Same-day14–16 count 14, fraction 0.00941492938802959. These are geographic calendar references, not verified settlement windows for uncaptured rules.

TMAX_NO: 833/3282 BUYs in14:00–16:00city local time (25.38%), notional share 25.55%. Hour counts `{'13': 561, '11': 455, '15': 358, '14': 475, '16': 181, '0': 97, '12': 562, '10': 266, '3': 7, '9': 97, '17': 91, '5': 3, '7': 11, '18': 31, '1': 6, '23': 22, '4': 5, '8': 28, '22': 4, '20': 4, '19': 5, '21': 2, '2': 7, '6': 4}`.

Same city-calendar date as market: 3261; other local dates 21. Same-day14–16 count 833, fraction 0.25544311560870897. These are geographic calendar references, not verified settlement windows for uncaptured rules.

TMAX_YES: 57/154 BUYs in14:00–16:00city local time (37.01%), notional share 34.72%. Hour counts `{'14': 30, '15': 27, '16': 22, '12': 17, '13': 20, '17': 12, '11': 9, '8': 2, '18': 7, '10': 5, '3': 1, '4': 1, '23': 1}`.

Same city-calendar date as market: 154; other local dates 0. Same-day14–16 count 57, fraction 0.37012987012987014. These are geographic calendar references, not verified settlement windows for uncaptured rules.

TMIN_NO: 14/1469 BUYs in14:00–16:00city local time (0.95%), notional share 1.79%. Hour counts `{'23': 63, '12': 3, '0': 144, '3': 148, '4': 208, '7': 48, '22': 49, '2': 152, '1': 141, '20': 26, '5': 203, '6': 154, '19': 14, '10': 6, '21': 26, '13': 7, '17': 14, '18': 16, '8': 17, '14': 9, '9': 6, '11': 3, '16': 7, '15': 5}`.

Same city-calendar date as market: 1449; other local dates 20. Same-day14–16 count 14, fraction 0.00966183574879227. These are geographic calendar references, not verified settlement windows for uncaptured rules.

TMIN_YES: 0/38 BUYs in14:00–16:00city local time (0.00%), notional share 0.00%. Hour counts `{'5': 14, '23': 3, '3': 4, '6': 8, '2': 2, '10': 1, '4': 3, '7': 1, '1': 1, '0': 1}`.

Same city-calendar date as market: 38; other local dates 0. Same-day14–16 count 0, fraction 0.0. These are geographic calendar references, not verified settlement windows for uncaptured rules.

Geographic IANA references permit descriptive local hours, not retroactive settlement-rule verification. Only captured exact token+condition metadata establishes a station reference. Captured London markets useEGLC, while the weather collector monitorsEGLL; Heathrow cannot stand in for LondonCity.

No archived causal forecast Tmax hour exists in these inputs. No true final settlement-source Tmax time is established. Those fields remainNULL. Optional local METAR subset maxima are explicitly retrospective/incomplete and not final daily Tmax or decision inputs. Current market endDate is not assumed to be local midnight.

Global historical market tape, depth-by-local-hour and matched no-trade controls are unavailable. Own-wallet SELL activity is not a global liquidity baseline. A14–16histogram cannot establish favorable expected Tmax timing or distinguish weather repricing from mean reversion.

## Actual book evidence and examples

All-history book classification: `{'NO_VALID_BOOK': 11828, 'BOOK_FIRST_OBSERVED_AFTER_TRADE': 37, 'PRE_TRADE_BOOK_OBSERVED': 2}`. Source-block-relative pre-trade status does not establish a physically pre-match book.

- BUY `f0f81d04fd20a50d3648e23a6a3c9d88060d2add14fb95afe5fd4f80b4592a13`: NO_VALID_BOOK; subscribed at source anchor=False; post-receipt empty-side=EMPTY_SIDE_CONFIRMED; role=CHAIN_VERIFIED_TAKER.
- SELL `1eb13fc1a1ead80a2e00989656221b72a1f28632bb7f61f9fe389e4da9ce275b`: PRE_TRADE_BOOK_OBSERVED; subscribed at source anchor=False; post-receipt empty-side=EMPTY_SIDE_CONFIRMED; role=CHAIN_VERIFIED_TAKER.
- BUY `6a79207e6786de74ea9c723e2636e816e81ed0659940ec8cefc8e40f4ba7943a`: BOOK_FIRST_OBSERVED_AFTER_TRADE; subscribed at source anchor=False; post-receipt empty-side=EMPTY_SIDE_CONFIRMED; role=API_ATTRIBUTED_TAKER.
- SELL `2228c6fd45f021ea61bd0652bb608ae272184afd15d15803bd42267f52205240`: PRE_TRADE_BOOK_OBSERVED; subscribed at source anchor=False; post-receipt empty-side=EMPTY_SIDE_CONFIRMED; role=API_ATTRIBUTED_TAKER.

A subscription existing earlier does not establish uninterrupted valid depth. Raw HTTP200asks:[] must match exact asset, condition, both sides and raw SHA before EMPTY_SIDE_CONFIRMED. Provider book clocks can lead local receipt; no millisecond event ordering or global liquidity absence is inferred. Replayed aggregated quantities do not identify order owners.

- TYPICAL_POSITIVE_CONDITIONAL_FIFO: `e977046c2fafbb53d9db71c555838a66c1ff4675fec3e5c8d0f338c12776294b`, taipei, BUY0.98, quantity317.39, matched317.39, remainder0.00, exact closure3.0s, sellVWAP0.99, conditionalgross3.1739, fee-netNone. CONDITIONAL_GROSS_ONLY.
  Source BUY 2026-08-17T02:01:03+00:00 (2026-08-17T10:01:03+08:00 local), last matched SELL 2026-08-17T02:01:06+00:00. BUY role UNKNOWN; SELL evidence {'UNKNOWN': 1}. Pre-entry book NO_VALID_BOOK; limit placement and forecast Tmax remain UNKNOWN.
- TYPICAL_NEGATIVE_NO_CONDITIONAL_FIFO: `498dd5ee92655c5f23be657ec692cd36be65ec8dfee713673a90846cca4152ef`, warsaw, BUY0.8463987896, quantity284.21, matched284.21, remainder0.00, exact closure1113.0s, sellVWAP0.5563002709184828120052074171, conditionalgross-82.448899994474, fee-netNone. CONDITIONAL_GROSS_ONLY.
  Source BUY 2026-06-11T14:02:10+00:00 (2026-06-11T16:02:10+02:00 local), last matched SELL 2026-06-11T14:20:43+00:00. BUY role UNKNOWN; SELL evidence {'UNKNOWN': 13}. Pre-entry book NO_VALID_BOOK; limit placement and forecast Tmax remain UNKNOWN.
- LARGE_NEGATIVE_COUNTEREXAMPLE: `9cca8aab4b0c8d168e0a356a162a498d8035b5929033cc7d0c96c5e46b98af24`, warsaw, BUY0.9539234974, quantity757.36, matched757.36, remainder0.00, exact closure1127.0s, sellVWAP0.7742739912446722826661033062, conditionalgross-136.059349981799, fee-netNone. CONDITIONAL_GROSS_ONLY.
  Source BUY 2026-06-11T14:02:10+00:00 (2026-06-11T16:02:10+02:00 local), last matched SELL 2026-06-11T14:20:57+00:00. BUY role UNKNOWN; SELL evidence {'UNKNOWN': 21}. Pre-entry book NO_VALID_BOOK; limit placement and forecast Tmax remain UNKNOWN.
- PROSPECTIVE_AGGRESSIVE_EXIT: `6a79207e6786de74ea9c723e2636e816e81ed0659940ec8cefc8e40f4ba7943a`, moscow, BUY0.9529849341, quantity201.78, matched201.78, remainder0.00, exact closure4.0s, sellVWAP0.99, conditionalgross7.468899997302, fee-netNone. CONDITIONAL_GROSS_ONLY.
  Source BUY 2026-10-27T10:00:17+00:00 (2026-10-27T13:00:17+03:00 local), last matched SELL 2026-10-27T10:00:21+00:00. BUY role API_ATTRIBUTED_TAKER; SELL evidence {'API_ATTRIBUTED_TAKER': 1}. Pre-entry book BOOK_FIRST_OBSERVED_AFTER_TRADE; limit placement and forecast Tmax remain UNKNOWN.
- PROSPECTIVE_AGGRESSIVE_EXIT: `f0f81d04fd20a50d3648e23a6a3c9d88060d2add14fb95afe5fd4f80b4592a13`, ankara, BUY0.98, quantity38.35, matched38.35, remainder0.00, exact closure5.0s, sellVWAP0.99, conditionalgross0.3835, fee-net0.3835. EXCHANGE_FEE_NET_ONLY_GAS_EXCLUDED.
  Source BUY 2026-10-27T09:22:30+00:00 (2026-10-27T12:22:30+03:00 local), last matched SELL 2026-10-27T09:22:35+00:00. BUY role CHAIN_VERIFIED_TAKER; SELL evidence {'CHAIN_VERIFIED_TAKER': 1}. Pre-entry book NO_VALID_BOOK; limit placement and forecast Tmax remain UNKNOWN.

Five real sequences are attempted; historical illustrations lack contemporaneous books/fees and are not five fully proven mechanisms. No wallet-attributable passive-limit example or causal forecast-Tmax example exists. Explicit unknown fields remain in the examples CSV.

## Conclusions and bounded next test

Fast higher-price NO exits are a common conditional execution pattern; passive limit placement is not demonstrated. Ankara supports an aggressive taker exit, and recent API evidence is consistent with another such case. The historical maker/taker denominator is mostly unknown. Weather timing versus repricing remains unresolved. A hybrid is plausible, not identified.

## Direct answers to the eight research questions

1. Around0.90: 305/395 cleanNO entries0.88–0.92 close higher within3–15source seconds. The stricter +0.01–0.03 probe has 0cases; many exits are around0.99. No evidence establishes immediate passive limit placement.
2. Exact quantity-closure rates are in the NO table above, with both all-eligible and closed-only denominators; not first-later-SELL intervals.
3. Whole-history SELL maker/taker majority is UNKNOWN; taker-only positive evidence is a selected sample. Ankara is independently chain-verified TAKER/TAKER.
4. NO/Tmax same-city-day14–16: 833/3261 (25.54%). Expected forecast Tmax alignment is UNTESTABLE without the original forecast archive.
5. Ankara0.98 is not an exceptional price: exact0.98 is the strongest exact-price mode, 878/4751NO buys; 408/3282specificallyTmaxNO. VWAP is not an order-limit observation.
6. No price/holding combination has fully verified historical all-cost profitability. Ankara has +0.3835pUSD after observed zero exchange fees; gas/relay/rebates and original wider inventory remain outside that statement. Gross-only groups and losses are exported completely.
7. Aggressive matching and a BUY/BUY mint entry are proven in Ankara. That does not identify the information trigger or exclude passive/hybrid behavior elsewhere; weather causality and mean reversion lack matched controls.
8. The demonstrated route can be measured prospectively through both outcome books. Its pre-entry availability and post-detection copy profitability are not established here; the direct-ask-only shadow model was incomplete for that route. No execution rule is activated.

Faithful replication requires a causally recorded entry signal and executable pre-entry book, not a hindsight rule based on the trader's fills. Existing delayed copies found no direct ask at the sampled opportunities, but omitted the demonstrated opposite-outcome matching path. No profitable replication rule or general impossibility of copying is established.

Propose only: freeze a bounded watchlist by weather event/date before activity (include sibling outcomes), preserve valid full snapshots plus same-epoch deltas, and record canonical market identity/clock evidence. Current late subscription on some tokens prevents pre-entry reconstruction. Do not change current services in this experiment. Add legitimate forecast archives and matched no-trade periods before evaluating Tmax causality.

Reproduce: `uv run python -m scripts.research.hightemptation_tmax_limit_exit --snapshot-dir data/research/exp0012 --output reports/trader`. Sources/method details: docs/research/EXP0012_PROTOCOL.md, EXP0012_METADATA.md and EXP0012_BOOK_AUDIT.md. Immutable snapshots and original public RPC responses are retained ignored locally; normalized research outputs are committed.
