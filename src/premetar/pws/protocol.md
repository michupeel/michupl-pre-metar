# PWS protocol 1.0

Research only. Durable byte-exact RAW capture precedes parsing. Preserve provider,
station and sensor identities, metadata discovery snapshots and every arrival.
Never merge stations merely by coordinates. Unknown clocks/units stay unknown.
Sensor.Community timestamps are provider-server clocks, not measured/published
timestamps. Historical API imports are HISTORICAL_EVENT_ONLY.

PWS collection is bounded to at most 86400 seconds, with conservative provider
spacing, periodic discovery, explicit selection, Retry-After and no bursts.
One shared disk worker/database owner can run existing METAR and PWS tasks.
First station snapshots are startup-censored for latency. Station age is distinct
from HTTP freshness. A failing data provider must not silently discard RAW or
terminate other providers; infrastructure failures remain fatal.

QC is deterministic, configured and versioned. Unknown metadata is not a hardware
fault. Spatial/solar disagreement alone is suspicion, not destructive exclusion.
Ranking uses prior chronological OOS results and minimum sample/evaluation dates;
missing support means UNVERIFIED/NULL score, never an invented score.

METAR is quantized. Use existing ICAO ties-warmer rounding and interval-aware
errors, with exact integer matches separate. Calibration labels, metadata,
selections, observations and weighting statistics must be available by decision
time. No target result may train its own forecast. Do not insert historical
replays as prospective predictions. Predictions are immutable and created before
their explicit future target.

Report accuracy separately from receive timing. UTC differences alone cannot
certify measured information lead. Current bounded capture does not certify
continuous coverage, so capture_coverage_verified=false. No information edge or
economic claim is established by discovery, fixtures, correlation or this smoke.
