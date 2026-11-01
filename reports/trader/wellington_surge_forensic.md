# Wellington surge forensic — observed evidence

Classification: COMPLEMENTARY_LIQUIDITY_SUPPORTED; trigger causality: MULTIPLE_EXPLANATIONS_POSSIBLE.
Snapshot max ID 7437602; read bounds 6600284..6700284; 331 timeline rows, 16 threshold events. All analysis retrospective.

## New independently checked transaction evidence

BUY/BUY mint supported: True. Official ExchangeV2 logs, hash-checked receipts and block hashes verified. Public receipt backfills are NOT information available before the original trade.

| Side | Shares | Collateral | VWAP | Block / log | Block timestamp |
|---|---:|---:|---:|---|---|
|BUY|207.78|196.0404|0.9434998556165174704013860814|96487771/306|2026-10-31T08:58:33+00:00|
|SELL|207.78|205.7022|0.99|96487775/163|2026-10-31T08:58:39+00:00|

## Exact maker fills for BUY

| Maker side/token | Shares | Collateral | Effective NO cost |
|---|---:|---:|---:|
|BUY YES|5|0.4|0.92|
|BUY YES|37.28|2.6096|0.93|
|BUY YES|60.5|3.63|0.94|
|BUY YES|100|5|0.95|
|BUY YES|5|0.1|0.98|

## What this establishes

H3 is supported for the EXECUTED BUY: five opposite-outcome YES BUY makers fund the paired mint. Direct NO asks alone cannot explain all matching liquidity. The live snapshot's empty NO ask/YES bid is not contradictory to a prior fill that consumed those orders.
H4/H5: Data API BUY/SELL seconds equal their canonical block timestamps (two transactions). They are not verified matching-engine or submission clocks. Local receipts and exchange message timestamps are separate clocks; do not subtract them as precise causal lead.
H2 remains possible: the public depletion and trade messages may represent this same operation before later on-chain reporting. The owner of a new0.99bid cannot be inferred from aggregate depth. H1 independent reaction and H6 replenishment remain alternatives.
H7: replay checks same connection, full seeds and reported BBO, but no exchange sequence or clock synchronization guarantees. Snapshot transitions and gaps remain explicit.
The SELL is chain-verified TAKER207.78NO at0.99, not proof of a resting maker limit exit. Equal BUY/SELL quantity supports conditional cash difference 9.6618; fungible inventory, earlier transfers, gas/relay costs and order-placement time remain unknown. No full-portfolio or copy profit claim.

## Research surge events

| Local receipt UTC | Outcome | Kind | Before | After | Source event |
|---|---|---|---:|---:|---|

## Exact raw WebSocket transaction joins

| Side | WS local receipt | WS exchange timestamp ms | Canonical block timestamp | Raw event |
|---|---|---|---|---|
|BUY|2026-10-31T08:58:29.775972+00:00|1793437109909|2026-10-31T08:58:33+00:00|6650105|
|SELL|2026-10-31T08:58:35.371984+00:00|1793437115496|2026-10-31T08:58:39+00:00|6650309|

The RAW BUY print at08:58:29.775972UTC contains the EXACT BUY transaction hash; it precedes the bid insertion at08:58:29.863130UTC by87.158ms in local receive order. The source exchange timestamps also order BUY1793437109909 before bid1793437109963 (54ms). This falsifies interpreting this particular observed bid jump as preceding the public execution print for that BUY. It does NOT establish who owned the new bid or reveal off-chain order-submission time. The old normalizer omitted transaction_hash; raw evidence retained it, and the new normalizer now preserves it without retroactively modifying old records.
|2026-10-31T08:55:03.243317+00:00|no|ASK_SURGE|0.75|0.93|6645456|
|2026-10-31T08:55:03.243317+00:00|no|SPREAD_EXPANSION|0.61|0.79|6645456|
|2026-10-31T08:55:03.243317+00:00|yes|BID_COLLAPSE|0.25|0.07|6645456|
|2026-10-31T08:55:03.243317+00:00|yes|SPREAD_EXPANSION|0.61|0.79|6645456|
|2026-10-31T08:55:03.274342+00:00|no|SPREAD_EXPANSION|0.79|0.85|6645458|
|2026-10-31T08:55:03.274342+00:00|yes|SPREAD_EXPANSION|0.79|0.85|6645458|
|2026-10-31T08:58:29.863130+00:00|no|BID_SURGE|0.1|0.99|6650120|
|2026-10-31T08:58:29.863130+00:00|no|LIQUIDITY_APPEARANCE|49.99|249.99|6650120|
|2026-10-31T08:58:29.863130+00:00|yes|ASK_COLLAPSE|0.9|0.01|6650120|
|2026-10-31T08:58:29.863130+00:00|yes|LIQUIDITY_APPEARANCE|49.99|249.99|6650120|
|2026-10-31T08:58:29.870139+00:00|no|LIQUIDITY_APPEARANCE|210.0|322.0|6650128|
|2026-10-31T08:58:29.870139+00:00|yes|LIQUIDITY_APPEARANCE|210.0|322.0|6650128|
|2026-10-31T08:58:29.951190+00:00|no|LIQUIDITY_APPEARANCE|322.0|1022.0|6650130|
|2026-10-31T08:58:29.951190+00:00|yes|LIQUIDITY_APPEARANCE|322.0|1022.0|6650130|
|2026-10-31T09:00:44.448569+00:00|no|LIQUIDITY_APPEARANCE|110.0|222.0|6652906|
|2026-10-31T09:00:44.448569+00:00|yes|LIQUIDITY_APPEARANCE|110.0|222.0|6652906|

## Sources and limitations

Official protocol: https://docs.polymarket.com/api-reference/wss/market . Exchange source: https://github.com/Polymarket/ctf-exchange-v2/blob/main/src/exchange/mixins/Trading.sol . Raw public RPC receipts/block responses are preserved locally with SHA256 and new receive times. Historical evidence is not a contemporaneous executable opportunity. Adjacent bid increase does not reveal ownership or an independent trigger. No hypothetical order/fill/profit has been created.
