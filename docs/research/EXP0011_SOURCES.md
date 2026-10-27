# EXP-0011 — public source verification

Verified 27 October 2026. These are research sources; none authorizes orders,
authentication with trading credentials, or changes to the weather collector.
Documentation can change. Preserve original API captures and the protocol version.

## Wallet identity — OBSERVED

One public GET to `https://gamma-api.polymarket.com/public-profile` with
`address=0x6011655c4afb76f36dd1b08a137a1ba73466b31e` returned HTTP 200:

```json
{"proxyWallet":"0x6011655c4afb76f36dd1b08a137a1ba73466b31e","name":"HighTempTation","pseudonym":"Dual-Aunt","displayUsernamePublic":true,"verifiedBadge":false}
```

This verifies the current public display-name association, not the person's legal
identity. Refuse to start a new capture if the expected name/wallet association
changes. [Official profile endpoint](https://docs.polymarket.com/api-reference/profiles/get-public-profile-by-wallet-address).

## Public trade, activity and freshness APIs — VERIFIED

| Purpose | Public GET | Important semantics |
|---|---|---|
| Wallet trades | `https://data-api.polymarket.com/v2/trades?user=<wallet>&taker_only=false&limit=100` | `data` array plus `pagination`; follow opaque `next_cursor`; repeat the same filters on every page; no request `offset`; maximum page size 1000 |
| Wallet activity | `https://data-api.polymarket.com/v2/activity?user=<wallet>&type=TRADE&limit=100` | Cursor pagination; `sort_direction=DESC` or ASC; timestamp-only sort; other activities include merges, splits and redemptions |
| Service clocks | `https://data-api.polymarket.com/v2/status` | `computed_at`, snapshot `age_seconds`, serving lag, ingestion block cursors; does not timestamp publication of each individual trade |

Trade fields observed and documented include `proxy_wallet`, `side`, `token_id`,
`condition_id`, `size`, `price`, `timestamp`, `transaction_hash`, `title`, `slug`,
`event_slug`, `outcome`. The source clock is integer block epoch seconds. There
is no documented per-row publication clock, order creation clock, unique log index
or reliable execution-role field in this response. An opaque cursor internally
anchors sequence order but is not a trade identifier.

`taker_only=true` is the default and returns taker-side fills; `false` includes
maker rows. A positive exact match from a separately recorded taker-only response
can support API-attributed taker status. Absence from an incomplete page cannot
establish maker status. Otherwise role is UNKNOWN. Identical content fingerprints
deduplicate repeated public rows but cannot distinguish genuinely identical fills
without additional source identifiers; disclose that ambiguity.

[Trades](https://docs.polymarket.com/api-reference/feeds/list-trades),
[activity](https://docs.polymarket.com/api-reference/feeds/list-account-activity),
[freshness](https://docs.polymarket.com/api-reference/service/get-data-freshness).

Published v2 limits: all v2 routes 800 requests/10 seconds; trades 300/10 seconds;
activity 200/10 seconds; status 100/10 seconds. CLOB books 500/10 seconds. Limits
are ceilings, not recommended polling frequencies; respect Retry-After and bound
retries. [Official rate limits](https://docs.polymarket.com/api-reference/rate-limits).

At verification, status HTTP 200 reported `computed_at=2026-10-27T08:38:25Z`,
`age_seconds=7`, serving lag 1 second, worst stream `activity_feed`, Polygon chain
137, maximum synced block 96256622 and minimum 96256621. This is one service
snapshot, not a measured distribution of wallet detection latency.

The two-row startup probe returned Tel Aviv NO 26°C / 27 October:
BUY 9 shares at 0.98, source epoch 1793087526,
transaction `0x0a5049fe093a64ea3ce21d2fffab15aa586d7b0dad3d3eae0f6e8905783ad03e`;
SELL 9 shares at 0.99, epoch 1793087532,
transaction `0x5d4eb9106f0b43a437039392773b57ca084ae8246a62a116ea95e4b2e57c9bbc`.
At 08:43:00.845448 UTC, a separate `taker_only=true&limit=20` public query
returned both exact rows (same transaction, wallet, token, side, size and price).
Under the documented filter semantics, both have positive API-attributed TAKER
evidence; this has not been independently decoded from chain logs. Those historical
rows establish a six-second public execution interval, not our live copy
feasibility, precise decision time or net PnL.

## Live market data — VERIFIED

Public socket: `wss://ws-subscriptions-clob.polymarket.com/ws/market`.
Subscribe with `{"assets_ids":["<token>"],"type":"market"}`; send text PING every
10 seconds. Raw API messages use `event_type`, `asset_id`, `market`; `book`
contains bids/asks, `price_change` contains level changes, and `last_trade_price`
may include transaction hash. It does not identify trader wallets. SDK normalized
events use another envelope; do not confuse the schemas. Reconnect invalidates
local continuity until a new snapshot. PONG alone does not certify depth freshness.

[Official realtime data, including raw API schemas](https://docs.polymarket.com/market-data/realtime-data),
[market channel](https://docs.polymarket.com/api-reference/wss/market).

The simplest verified wallet-specific route is public Data API polling. Public
chain logs are another legitimate attribution route but must be independently
timed; no evidence yet that they are faster here. A public market trade event
cannot trigger a wallet copy without attribution evidence.

The monitor also polls documented `/v2/activity` independently of `/v2/trades`.
Both feeds expose a source block timestamp, not an individual publication clock.
Only `type=TRADE` activity enters the same strict trade normalizer; non-trade
activity such as REDEEM is separate inventory evidence and cannot initiate a BUY.
The shared economic fingerprint preserves a single immutable first local trade
receipt, while per-endpoint receipt evidence permits a later trades-versus-activity
race analysis. Each route has its own bootstrap/outage censorship. A detection
record identifies which route actually delivered it first. Compare endpoint
latencies only after both loops were active with known polling coverage; startup
backfills, service status ages and second-resolution block clocks cannot establish
a globally fastest detection route.

## Discovery, fees and settlement — VERIFIED with explicit limits

`GET https://gamma-api.polymarket.com/tags/slug/weather` returned id `84`.
`GET /markets?tag_id=84&closed=false&limit=2` returned two open annual NASA
temperature markets: weather tag alone is not a daily-maximum filter. Paginate
and inspect exact market identity. Targeted lookup supports `condition_ids` and
`closed=any`; raw descriptions must remain available.
[Tag lookup](https://docs.polymarket.com/api-reference/tags/get-tag-by-slug),
[market listing](https://docs.polymarket.com/api-reference/markets/list-markets).

At 08:40:32 UTC, targeted Gamma lookup of condition
`0x911a04456977c617d1f0bccad136293017bbc80c14aa9cc796fe2962ff593aa8` returned
market 6175141, Tel Aviv 26°C / 27 October, active/open/accepting orders.
Its actual rules specify LLBG routine observations, T-group tenths where present,
body temperature otherwise, SPECI excluded, station local date, half ties toward
warmer whole Celsius, specified AWC source and Wunderground fallback. Corrections
and next-day resolution-read deadlines are explicitly described. This must not be
generalized to other markets or replaced with the largest routine integer.

Gamma returned `feeType=zero_fees`,
`feeSchedule={"exponent":1,"rate":0,"takerOnly":true,"rebateRate":0}` despite
`feesEnabled=true` and `takerBaseFee=1000`. CLOB
`GET /clob-markets/<condition>` also returned `fd={"r":0,"e":1,"to":true}` and
`tbf=1000`; `GET /fee-rate?token_id=<token>` returned `base_fee=1000`.
Thus the base fee alone cannot establish the effective charge. Preserve both;
the documented Gamma effective rate and independently matching CLOB curve rate
are explicitly zero for this market, so the verified curve charge is zero.
Other markets require their own recorded parameters; otherwise economics stay UNKNOWN.
[Effective fee schedule semantics](https://docs.polymarket.com/market-data/market-details).
[CLOB market info](https://docs.polymarket.com/api-reference/markets/get-clob-market-info),
[base-fee endpoint](https://docs.polymarket.com/api-reference/market-data/get-fee-rate).

Current general fee documentation specifies `shares * rate * p * (1-p)`, taker
fees only and five-decimal precision. Its category weather rate is not authority
to override an individual market's zero fee schedule or a different exponent.
[Fee formula](https://docs.polymarket.com/trading/fees).

For final payouts, `GET https://data-api.polymarket.com/v2/resolutions?condition=...`
returns status, payout vector, lifecycle and provenance. Proposed/disputed values
are not final payouts; resolved token identity must be matched exactly.
[Resolution state](https://docs.polymarket.com/api-reference/markets/get-resolution-state).

## On-chain role evidence — VERIFIED interpretation, integration optional

Official exchange sources expose OrderFilled and OrdersMatched. A field named
`maker` is the signed order's funder and can occur in the taker-side aggregate
event too. OrdersMatched identifies the taker-order maker; correlate transaction,
token, side, amounts and log order, accounting for mint/merge matches. ABI differs
between exchange versions. Do not classify by address field name alone.
Neither event establishes when the off-chain order was submitted or conceived.

[CTF v2 event ABI](https://github.com/Polymarket/ctf-exchange-v2/blob/main/src/exchange/interfaces/ITrading.sol),
[matching implementation](https://github.com/Polymarket/ctf-exchange-v2/blob/main/src/exchange/mixins/Trading.sol),
[current protocol exchange](https://github.com/Polymarket/polymarket-v2-external/blob/main/src/exchange/Exchange.sol).

## Faster weather candidates and prior evidence

Existing local raw METAR/PWS receipt history is available only for covered sources
and airports. It cannot establish global publication time. Read it with bounded,
read-only queries; source event time alone is insufficient for as-of knowledge.
PWS provenance, freshness and existing ingestion eligibility remain unchanged.
Forecast versions without recorded publication/receipt are retrospective context.

The parent lab's read-only `docs/HIGHTEMPTATION_RECONSTRUCTION.md` records earlier
Taipei executions, ANWS receipt measurements, Mexico City counterexamples and
maker/taker caveats. These are previously selected historical discovery cohorts,
not the new monitor's prospective observations; no runtime dependency is created.
The reported ANWS samples do not explain selected earlier Taipei executions.
KNMI/IMGW/CHMI existing public producer captures are candidates where geography
matches; ATIS/internal aviation feeds and paid providers are UNVERIFIED/DISABLED.
Do not fabricate measured access or latency for an untested source.
