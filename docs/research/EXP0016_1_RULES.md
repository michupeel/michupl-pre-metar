# EPWA settlement reconstruction — EXP0016.1

Implementation: `premetar.research.settlement_rules`, version
`EPWA-SETTLEMENT-v1`. Pure functions only, no network or database mutations.
The caller must preserve public raw responses before normalization and attach
source references, exact actual collection times and source payload hashes.

## Captured rule families

`parse_rules(market)` inspects that historical market's own description and
resolutionSource. It recognizes current AWC routine T-remark/body-fallback
clauses separately from legacy Wunderground Daily table rules. An old WU rule
does not acquire current AWC rules merely because both refer to EPWA. Unknown
rounding/cutoff remains unknown. The rule description and SHA256 are retained.

Current explicitly recognized clauses include: EPWA, Celsius, local observation
day, every report not beginning SPECI (including off-hour/unlabelled routine
reports), exact Txxxxxxxx remark if present, body fallback when no valid remark,
ties to the warmer integer, source report versions through the following-day
datapoint cutoff, D+1 23:59 America/New_York deadline, and exceptional seven-day
technical-error/clarification language. Parser flags describe captured clauses,
not proof that each historical source view was archived at that cutoff.

`parse_temperature(raw, rules)` retains full TAC, decimal value, float export,
precision semantics, COR flag and exclusions. T-group sign and tenths take
precedence over the integer body. Malformed remarks cannot create a decimal
temperature; a valid body fallback is labelled. Conflicting valid T remarks or
body temperature groups are rejected. SPECI is excluded regardless of its value.
Temperature is never inferred from the dew point. `round_integer` uses Decimal
floor(value+0.5):16.5→17,−8.5→−8,−0.5→0; Python banker's round is not used.

No observation, fallback table or verified no-data proof means no source-derived
winning bracket. The lowest bracket is NOT inferred simply from an empty API
response. WU/fallback rules are retained but METAR reconstruction cannot certify
a WU daily maximum. Such dates require actual permitted fallback source evidence;
until then the market can be VERIFIED_MARKET_ONLY. No unauthorised scraping is
implemented by these pure utilities.

## Source clocks, corrections and local dates

`reconstruct_day(day,rules,reports,cutoff=...,evidence=...,market_result=...)`
accepts original event clocks under observation_time_utc/observation_time/
nominal_time/obsTime/reportTime. A UTC DDHHMMZ TAC may be dated using the explicit
requested local day anchor; this derivation is labelled and does not manufacture
a collector receipt or publication time. Adjacent Warsaw calendar midnights
produce the real23/24/25hour UTC interval; its end is exclusive. Repeated02:xx
local labels at DST fallback stay separate UTC observations.

Source receipt clocks may be supplied as source_receipt_time,
provider_receipt_time or receiptTime, always timezone-aware. Collector receipt
clocks remain separate. Backfilled collection in2026-10-29 does not become a
historical2026-10-23 arrival. Unknown/naive timestamps stay unknown.

Only when provider receipt/cutoff semantics have been independently verified by
the caller may provider receipt clocks select the final eligible report version.
A post-cutoff correction cannot replace an earlier eligible version. If only a
post-cutoff correction survives, the prior value is missing; it is not fabricated.
Without that verification, present archive versions can support a reconstruction
but cannot certify a historical cutoff view. Exact TAC duplicates retain earliest
known collector/source receipt, distinct raw-capture hashes and arrival count;
they do not inflate qualifying observations. Original versions are preserved.

## Market resolution evidence

`resolved_market(event_or_market_list)` requires every included binary market to
be closed, UMA status resolved, and have exact0/1 binary outcome vector; exactly
one bracket must have YES=1. Last-trade prices, best bids, near-one prices,
proposals and incomplete markets do not establish resolution. Winning tail
brackets remain bounds, not invented exact daily temperatures.

## Two distinct verification axes

Classifications:

* VERIFIED_SOURCE_AND_MARKET: resolved bracket agrees with independently verified
  qualifying official-source reconstruction, supported by one of the evidence
  bases below.
* VERIFIED_MARKET_ONLY: market label established, but source reproduction or its
  eligibility/coverage is insufficient.
* SOURCE_RECONSTRUCTED: source-derived maximum without confirmed market label.
* CONFLICT: reconstructed integer does not fit the resolved bracket. The separate
  conflict_certified flag distinguishes certified reproduction from a possible
  disagreement due to incomplete/uncertain historical evidence.
* INSUFFICIENT_EVIDENCE: neither sufficient source reconstruction nor market label.

The strict archival certificate requires official_source, coverage_complete,
correction_cutoff_verified and source_snapshot_at_cutoff_certified all true,
source_reference, source_snapshot_sha256, and certification_basis equal to
ORIGINAL_CUTOFF_SNAPSHOT or AUTHORITATIVE_VERSIONED_CUTOFF_ARCHIVE.

Independent current-archive reproduction may instead use certification_basis
CURRENT_OFFICIAL_ARCHIVE_REPRODUCTION_WITH_PROVIDER_RECEIPT_CUTOFF. It requires
official_source, coverage_complete, rule_eligibility_verified,
provider_receipt_cutoff_verified and correction_versions_unambiguous all true,
source_reference, source_snapshot_sha256 and an explicit cutoff. Every chosen
report must have verified provider receipt no later than cutoff, with no missing
eligible correction version. These flags require actual evidence in the caller;
agreement alone cannot set them. A SHA string alone does not prove coverage.

Both bases may establish source_reproduction_verified and, with agreement,
VERIFIED_SOURCE_AND_MARKET. Only the first establishes source_cutoff_certified.
For current archive reproduction, historical_source_state_at_resolution remains
NOT_ARCHIVED and CURRENT_BACKFILL_IS_NOT_A_HISTORICAL_CUTOFF_VIEW is retained.
This label certifies independent reconstruction, not an impossible assertion of
perfect knowledge of every historical source version. Backfilled labels become
available to research at the actual collection time and must remain retrospective
in chronological forecast validation.
