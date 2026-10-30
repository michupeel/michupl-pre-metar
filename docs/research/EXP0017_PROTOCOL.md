# EXP-0017 — HighTempTation entry timing (frozen v1)

Final source-quality amendment v1.1 (30 October): IEM does not preserve original
report-type prefixes; hourly/nonhourly classes cannot certify routine/SPECI.
Keep unknown types unknown. Descriptive primary alignment uses observed recurring
nominal minutes (>=24 unique occurrences, >=50% of modal minute count, at most4
slots), with explicit original-type and hourly-only sensitivity. This corrects
a source-classification defect, not a trading parameter search. Source receipts
remain NULL for historical availability. The original plan below is retained for
audit; its routine-type certification assumption is superseded by this amendment.

Baseline: EXP0012 frozen trader SHA256
`6cddb1ee11e6a30d9bc9fac15ba659eb1a1a57045c7809e19db2bca3d3709b89`;
working baseline commit `1803eb0`. Original snapshots remain untouched.

Question: are weather NO BUY executions associated with nominal routine METAR
times, actual locally captured receipts, settlement proximity or price levels?
Execution time is not order placement or a known information-decision time.

Primary population: all deduplicated weather NO BUY economic records, including
outside the primary 0.90–0.99 range as explicit controls. Preserve exact Decimal
prices. Price partitions: <0.90; [0.90,0.95]; (0.95,0.98); =0.98;
(0.98,0.99); =0.99; >0.99. Never turn a VWAP into a quoted tick.

Only exact market condition/token rules establish a settlement station. Geographic
city mappings establish civil time only. Missing stations remain unknown. Any
newly downloaded rules are retrospective identities, never historical availability.
Current schedules are not automatically certified for March–October history.

Schedules are discovered from recorded routine observations (SPECI separate),
requiring at least 24 unique nominal cycles across two UTC days and >=80% minute
concentration for the smallest minute set covering 90% of observations. Corrections
at the same nominal time count once. Extrapolation outside observed dates is a
separate descriptive schedule projection, not an observed historical report.
Nearest schedule ties choose the earlier nominal time. Offsets are trade minus
nominal time. Boundary bins are left-closed/right-open, with final upper infinity.
Exact nominal time is neither strictly before nor after. ±30/60/180 is inclusive.
Source time is whole-second; boundary membership has >=1 second uncertainty and
block time is not exact submission time. No global public-release time inferred.

Transaction+token+side forms an execution cluster, not a proven parent order.
Report economic-row and cluster denominators. Settlement units are local calendar
days; daylight-saving boundaries are independent adjacent midnights. Final market
resolution is distinct from local day end. Unknown cutoff stays NULL.

Controls: compare entry rates with equal-duration off-window opportunities within
the same market/day when contemporaneous coverage permits. Where no complete
market-wide/price-conditioned observation exists, report only duration-normalized
uniform-phase contrasts and clustered descriptive intervals, NOT a matched causal
effect. Do not infer a price-driven or meteorological strategy from those contrasts.
Resampling is deterministic, seed 17, clustered by market+settlement day and by
settlement day separately. No optimized window or strategy parameters.

Weather context uses actual first local receipt <= source trade clock, exact
station, valid measurement provenance/freshness; actual provider publication stays
unknown. Archived source receipt cannot replace our receipt. Books require recorded
pre-event token/epoch and freshness. Missing context is UNKNOWN, not zero.

Conditional FIFO/first subsequent SELL are descriptive, not true initial inventory,
placement time or net profit. Reuse original chain proofs only for exact matching
transactions/quantities. No new trading or forecast rule. No service restarts.

Prospective extension reads existing monitors through bounded read-only queries,
writes a separate EXP0017 journal, marks startup snapshots censored, and never
backdates receipt or simulates missing pre-event books. Retention uses existing
bounded research store segments, not unlimited depth copies. No new external poller.

Acceptance: reproducible counts with explicit unknowns, every record in exactly one
price/time partition, no look-ahead, deterministic exports, full tests/lint/types,
database integrity and unchanged existing monitor PIDs. Missing evidence yields
INCONCLUSIVE, never an invented positive finding.

Local Qwen probe on 29 October: models endpoint accessible, 16 available models,
no model loaded; test generation HTTP400. No output accepted and no inference
server configuration changed.
