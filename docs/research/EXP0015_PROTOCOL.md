# EXP-0015 frozen prospective protocol v1

Baseline:0c8f8ab. Freeze configuration epwa-battle-v1.json and its hash in every
run. No real orders, wallet or private-key handling. No existing collector restart.
Primary outcome: complete net portfolio economics per independent Warsaw settlement
day, including open holdings and failed attempts. Accept an edge only after future
matched days and uncertainty; the implementation smoke is not evidence of profit.

SIMPLE uses no weather. BUY NO strictly0.91<p<0.98, exit0.99. Boundary0.98 is a
separate control, never silently admitted. Per variant:100USD initial cash,5USD
maximum order debit,25USD cumulative daily committed including fees,3 open/pending
contracts, one attempt per contract/day. Variants have independent identical capital:
marketable-limit taker and post-only best-bid maker;100/500/1000/3000/5000ms arrival.
Actual tick/minimum size and current explicit zero-fee evidence are mandatory;
unknown/nonzero unimplemented fees block rather than assume free execution.

Entry expires60s after decision, cancellation effective250ms after request. A
market/day close requests cancellation, not instant deletion. Exit is a0.99 SELL
only for filled inventory, with the same arrival delay. An immediately marketable
limit SELL is taker; otherwise maker. No discretionary stop or favorable rescue:
unexited inventory stays at risk until verified resolution. No short sales.

Use only recorded full-depth states received at/after modeled arrival, and within
2seconds of it; a later book is unresolved, never backdated. Missing arrival evidence
creates UNKNOWN execution, not a confirmed exchange rejection or a nonfill. Worst
case entry cash stays reserved, possible inventory remains explicit, and economic
PnL/equity stays unknown. Prototype mislabels are preserved with versioned accounting
exclusions; they cannot contribute zero-PnL observations to valid aggregates.
Displayed taker depth
supports conditional paper execution, not observed exchange fills. Paper actions
cannot consume the real book. Within each variant, one incoming depth/trade event
cannot be spent repeatedly by competing orders. Exact Decimal cash/quantity ledger.

Maker scenarios stay separate. PESSIMISTIC: no fill identifiable without our own
order/queue evidence. EVIDENCE_SUPPORTED: conditional queue model; visible same-price
quantity at arrival remains ahead, only subsequent same-token, same-price opposite
side public trade volume removes it. Cancellations never improve priority. A lost
connection/gap invalidates evidence, not a free fill. OPTIMISTIC_UPPER_BOUND ignores
queue ahead but still needs subsequent actual trade volume; merely touching0.99
does not fill anything. Trade-side/aggressor and queue assumptions are explicit;
none is an observed hypothetical order execution. Maker profitability is unidentified
without a meaningful guaranteed lower bound. No rebates assumed.

Complementary YES bids imply candidate1-bid prices only. Existing ExchangeV2 mint
evidence from EXP0012 is not proof of executable liquidity in today's EPWA contract.
Record THEORETICAL_ONLY separately, with zero complementary simulated fills.

WEATHER is SIGNAL-ONLY: no validated rule maps a forecast error into a defensible
settlement-outcome probability. HYBRID applies identical SIMPLE mechanics only if
the current frozen realization gate is true and a verified exact integer contract
lies at least1C above experimental adaptive Tmax. This is an exploratory safety
filter, not certainty that the outcome is impossible; tails can lose the whole NO.
Log rejected SIMPLE candidates and match their subsequent SIMPLE variant outcomes.

Controls, fixed before capture:0.98 boundary; inside/outside forecast Tmax±60min;
inside/outside nominal EPWA METAR±3min. SIMPLE is never gated by these annotations.
Randomized wait control uses seed20261028 and uniform0..60s deterministic delay
per market/day/variant. It is analytical only, requires matched price±tick, depth
at least desired size, same market and time-to-settlement±60s; otherwise UNMATCHED.
No synthetic random-control fills or ex-post optimized thresholds. Report all
opportunities, including misses, and no effect estimate without matched controls.

Marks require fresh executable liquidation depth; insufficient depth gives unknown
equity plus explicit zero-recovery stress bound, not an invented mark. Keep original
realized/unrealized/settlement PnL, fees, reserved cash, cost basis, committed capital,
capital-time, drawdown, every possible single winning outcome's correlated payout.
Unresolved positions never count as wins. Profit factor/expectancy/exit horizons and
day-block intervals remain NOT IDENTIFIABLE until appropriate complete outcomes exist.

All decisions are actual prospective creation times; original feed receipt is
separate from this sidecar's processing time. Do not reconstruct a submission in
the past. Bootstrap data only seeds context, never orders or new confidence events.
Restart restores cash/inventory/orders/cursors atomically, invalidates old queue
evidence and requires a new full snapshot. Engine config hash mismatch blocks.
Independent bounded daily/size segments,2GB total,1GB free-space floor; no automatic
research deletion. Continue across midnight, no arbitrary24hour shutdown. At total
storage cap stop safely and report intervention required rather than lose evidence.

Competing hypotheses: weather vs price/queue/mean-reversion/time-to-resolution.
Do not infer meteorological causality from preceding price movement. The current
producer has incomplete WS sequence guarantees; microsecond storage is not clock
accuracy. Preserve stale, unknown and loss cases in reports.
