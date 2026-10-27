# EXP-0012 — book and execution-role audit

Read-only input: `data/research/exp0012/trader_pinned.sqlite3`, consistent backup
pinned27October2026 at11:37:17.798402UTC. No live writes, subscriptions, collector
code or services were changed. `scripts/research/hightemptation_books.py` exposes
`audit_books(snapshot,trades)`, `role_evidence(snapshot)`,
`decode_v2_receipt(saved_envelope)` and `verify_event_topics()`.

## Distinguish recorded state from the moment of matching

Book classifications use source block time as a descriptive anchor and require
local receipt no later than that anchor and trade detection. Source block time
is not exact off-chain matching time. A state labeled PRE_TRADE_BOOK_OBSERVED is
observed before that recorded source clock; it is not proof that the trader's
execution had not already affected it. Clock offset remains UNKNOWN.

Replay applies documented level-size updates only after a full snapshot on the
same connection. Zero size deletes a level. Subscription removal, reconnect,
process STOP/new connection, malformed data and inconsistent top quotes invalidate
continuity until another full snapshot. No sequence guarantee is invented.
Reported best_bid0/best_ask1 are empty-side sentinels, not invented orders. Size
changes alone cannot identify an owner or establish a private limit placement.
[Current public market schemas](https://docs.polymarket.com/market-data/realtime-data).

## Actual prospective cases in this snapshot

|Case|BUY source UTC|Original local detection UTC|Pre-BUY coverage|SELL source UTC|
|---|---|---|---|---|
|Ankara NO16C27Oct|09:22:30|09:22:33.012009|NO_VALID_BOOK at source anchor|09:22:35|
|Moscow NO10C27Oct|10:00:17|10:00:17.068730|BOOK_FIRST_OBSERVED_AFTER_TRADE|10:00:21|

Ankara was first subscribed08:57:20.410839UTC and had a full snapshot at
08:57:20.740531. That fact alone does not demonstrate continuous pre-BUY coverage.
Its last earlier replay state,09:17:14.626006, belonged to an earlier connection;
the development restart replaced it. At09:22:30 the token was not in the current
subscription list. The old state cannot be carried forward as the BUY book.

Moscow's first recorded book was a REST reply10:00:17.692140UTC, already after
BUY source/detection; first WS subscription was10:03:28.548220UTC. No pre-BUY
snapshot may be manufactured from that later reply.

The first Ankara REST reply at09:22:33.682375 preserves correct exact `market`
and `asset_id`, HTTP200, both bid/ask arrays and original SHA256
`683abaa8c952d74d0f1356329089ff87a3a929d2282ea89402ec92d998ac2178`.
It has asks:[] and a0.99best bid of1424.34shares. The source book timestamp
09:22:34.334 is0.651625s ahead of the local receipt; timestamp precision cannot
be equated with verified clock accuracy. EMPTY_SIDE_CONFIRMED means this exact
recorded direct-ask response was empty, not proof that no other execution path
or transient liquidity existed.

Ankara's recorded0.99bid depth subsequently fell1424.34→1385.99, exactly38.35.
Moscow's recorded0.99bid depth fell1517.94→1316.16, exactly201.78. In Moscow that
decline was already observed10:00:20.389550UTC, before the SELL's source block
second10:00:21. These are consistency clues, not wallet-attributed order changes
or proof of a private decision clock. It would be wrong to call the earlier
Moscow book necessarily unaffected by its matching execution.

## Ankara: independently verified on-chain TAKER/Taker

Exactly two `eth_getTransactionReceipt` requests were sent to the single public
Polygon Bor endpoint `https://polygon-bor-rpc.publicnode.com`. Raw HTTP responses,
request/receipt clocks and SHA256 hashes are saved in
`data/research/exp0012/rpc/1.json` and `2.json`, before interpretation. This is
retrospective execution-role evidence, not a measurement of RPC detection speed.
[PublicNode's public Polygon service](https://www.publicnode.com/).

Both receipts succeeded on the documented current NegRisk CTF ExchangeV2,
`0xe2222d279d744050d28e00520010520000310f59`.
[Official current contract registry](https://docs.polymarket.com/resources/contracts).
The Gamma market's version label identifies the position system; it must not be
used alone to choose an older Exchange event ABI.

The offline decoder verifies Ethereum Keccak256 event topics against the official
signatures, then requires OrdersMatched.takerOrderMaker to equal the target
wallet and a matching aggregate OrderFilled with identical order hash, side,
token and amounts. A field named OrderFilled.maker alone is insufficient.
[ExchangeV2 event ABI](https://github.com/Polymarket/ctf-exchange-v2/blob/main/src/exchange/interfaces/ITrading.sol),
[matching implementation](https://github.com/Polymarket/ctf-exchange-v2/blob/main/src/exchange/mixins/Trading.sol).
Exact retrieved source hashes are retained under the ignored source_verification/
directory. No extra RPC searches, account credentials or paid endpoints were used.

|Side|Block|Transaction index|OrdersMatched log index|Token quantity|pUSD collateral|Exchange fee|
|---|---:|---:|---:|---:|---:|---:|
|BUY|96258386|27|295|38.35|37.583|0|
|SELL|96258389|65|1039|38.35|37.9665|0|

BUY transaction:
`0xcb4232e8436f1a076173d95a7941548bf7abf28f4c768acd56533dff0c0e4ca8`.
SELL transaction:
`0x4ed9364153849bfcc780c33aec17ab44d0b565d6108204a962ce71827ba4e5b5`.

Both are CHAIN_VERIFIED_TAKER. This is a concrete counterexample to interpreting
this SELL as passive liquidity provision. The historical aggregate exchange fee
is0 in both receipts; current fee metadata is not used to infer it. The two
collateral flows differ+0.3835pUSD after those exchange fees, excluding gas,
off-chain charges, rebates and wider portfolio inventory attribution. Transaction
senders paying gas are relayer/operator addresses, not inferred order owners.
OrdersMatched establishes active execution role, not order creation or decision
time; the user may have chosen a limit long before matching, but it executed as
the active order in these transactions.

## Role denominator and bounded next step

Public `taker_only=true` positive exact-row matches support API-attributed TAKER;
absence from that bounded feed never proves MAKER. The snapshot contains106such
role records against11867economic trade rows. Two Ankara roles have additional
chain proof; it would be invalid to extrapolate that coverage to all SELLs.
[Official public trade feed](https://docs.polymarket.com/api-reference/feeds/list-trades).
The original parser's source clock is block seconds, not placement time.

No passive exit candidate has wallet-attributable order placement in these
records. Missing book coverage remains INSUFFICIENT_BOOK_HISTORY, not evidence
against every passive strategy. A bounded research-only improvement would select
complete currently tradable city/day temperature-bucket cohorts before expected
activity, retain a fixed token budget and explicit coverage ledger, and verify
full-snapshot continuity across refreshes. Waiting until a specific token's first
BUY to subscribe cannot establish its earlier book. This is a proposal only;
neither monitor was modified or restarted for EXP0012.

## Verification

Fifteen deterministic tests cover future snapshots, delta deletion, top-quote
inconsistency, reconnect/STOP/unsubscribe, stale and wrong-market data, raw-verified
empty sides, unknown ownership, API role limits, Ethereum Keccak vectors and
strict current-ABI decoding. Focused pytest15passed; Ruff check/format and strict
mypy for the research module passed. Tests contain labeled synthetic fixtures,
not claimed live observations. Main experiment inventory/fee interpretation and
independent verification remain with the lead agent.

## Lead integration: opposite-outcome matching

The strict matching-path decoder and captured Gamma binary mapping establish
that Ankara's38.35share No BUY matched four maker-side BUYs on the sibling Yes
token at0.02:12.35+5+6+15shares. Their0.767collateral plus target37.583collateral
sums to38.35. The official ExchangeV2 Trading.sol BUY/BUY mint path supports
this interpretation. The subsequent No SELL matched a same-token BUY at0.99.
Both target roles are chain-verified TAKER, not passive-maker proof.

Consequently EXP0011's direct asks:[]/NO_LIQUIDITY did not establish absence of
implicit mint liquidity. Missing valid sibling depth at detection prevents
claiming either an executable profitable copy or its impossibility. No monitor
or shadow engine was changed. Normalized evidence is in
reports/trader/hightemptation_matching_paths.csv; original receipts and hashed
official source captures remain ignored under data/research/exp0012.
