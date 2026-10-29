# EXP0016.1 — settlement truth baseline and protocol

Baseline8e99c3e; no strategy/cohort/probability promotion changes. Hypothesis:
actual historical settled Warsaw contracts can be independently reproduced using
their captured official rules and AWC observations. Primary outcome is independent
settlement days per evidence class, not a profitability claim. Start23/26Oct2026;
bounded expansion15–28Oct while official API history remains available.

Verification has two axes: current official-archive reproduction versus exact
source state at historical resolution. Fully matching archived source+market
labels require captured explicit rules, declared half-hour schedule coverage,
untruncated official query, qualifying report provider receipts before derived
rule cutoff, and no ambiguous correction versions. Historical cutoff snapshots
are NOT fabricated; current-archive certified labels retain NOT_ARCHIVED caveat.
Incomplete coverage/corrections/fallback evidence stays in a lower tier.
Raw HTTP and all reports/corrections remain immutable, with actual backfill
receipt timestamp; provider receiptTime is not our historical collector receipt.

D-1 checkpoints06/12/18Warsaw, original forecast initialization and availability
provenance retained. Archived forecasts without verified availability use only
explicit approximate replay, separate from prospective records. Independent days,
same target/horizon samples, raw daily versus hourly-point errors separate.
Probabilities remain blocked below existing30training+20heldout-day requirements.

Existing collectors/dashboard/EXP0014–16 processes must not restart. Add historical
panel using existing static-file delivery, not a new ASGI route/restart. Separate
research evidence DB and reproducible public summary. A dedicated limited current-
user logon task may register existing D1 observer; installing must not start it
or replace existing task, and lock wrapper exits0 if observer already running.
