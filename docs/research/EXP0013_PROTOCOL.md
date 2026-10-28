# EXP-0013 — prospective forecast/weather/book observation

Baseline:070113f. Neither existing monitor may be stopped, restarted or changed.
No production database writes, trading, credentials, station/QC changes or
retrospective forecasts. Separate research store, raw-before-normalization.

Implementation v1.1 was frozen after a90second prototype revealed startup
METAR/current-forecast pairing and station-mismatch diagnostics defects. Original
v1 signals remain immutable with a separate EXCLUSION record; only v1.1 signals
enter analysis. v1 raw forecast/book evidence can remain evidence subject to its
original clocks and station/depth checks. The fixes preceded evaluation, with no
threshold fitting. Original METAR receipts are distinct from delayed sidecar
discovery notifications. Current forecasts cannot be attached to earlier receipts.

Resource bounds:128tokens/64binary markets, existing monitor's discovered universe
only (explicitly incomplete), forecast1800s/marketrefresh600s/weather30s; WS raw
is losslessly zlib/base64 encoded before parsing. Delta JSON is not duplicated;
the raw contains every observed delta. Book samples every5s retain controls.
At2GB mainDB+WAL or bounded duration the research sidecar stops; originals are
never deleted. Calibration uses a replaceable separate hourly analysis cache,
never production tables. No service/task configuration is modified. stop.request
inside the EXP0013 research directory gracefully stops ONLY this sidecar.

Hypothesis: forecast-guided windows contain more book movement and causally
available weather changes than outside-window controls. Null: no improvement.
This is an observation experiment, not an activated economic strategy.

Fixed rules v1: explicit hourly forecast snapshot every1800seconds; no fabricated
issue time. Transition windows ±10minutes around predicted ICAO integer changes;
Tmax windows ±60minutes around predicted hourly maxima. Freeze only windows whose
start is strictly later than forecast receipt AND schedule creation. Scheduled
METAR windows ±3minutes, also frozen before start. Forecast revision >=0.5C
is logged at actual receipt; it cannot retroactively schedule a window.

Window/control unit: same token, local settlement calendar day, nonoverlapping
5minute bins; require valid same-connection book observations at both ends with
<=10seconds age, both outcomes mapped to the exact contract. Primary response:
absolute midpoint change; secondary >=0.02movement. Controls must have no window
overlap. Group uncertainty by market/day, never count ticks as independent.
At least20distinct market-days and10matched window/control bin pairs per market
before comparative conclusions. No threshold tuning on this evaluation sample.

PWS policy remains verified measurement provenance, plausible temperature,
receive and event<=decision, <=300seconds freshness. CAL2 median past offset,
12hour lookback/minimum12prior independently received routine cycles. Quantized
METAR midpoint calibration is approximate, not exact thermometer truth. Raw and
calibrated values stay separate. Future/censored/ambiguous references excluded.

Immutable signals carry input IDs, first receipts, creation time, rule version
and separate subsequent outcome records. Signals are never instructions/orders.
Retrospective weather comparisons are labeled separately from live signals.

Both outcomes must be captured BEFORE a window for pre-window evidence. Old
connections, malformed/inconsistent deltas, subscription removal and stale books
invalidate executable status. No PONG-only freshness. Direct displayed asks and
complementary1-bid opportunities are separate; complementary price alone is NOT
a guaranteed fill. Unknown settlement station/day/rules, fees or depth blocks
economic claims. LondonCity/EGLC must never be silently mapped to EGLL/Heathrow.

No archived forecasts exist at baseline. Historical book/weather correlations
cannot prove forecast guidance. Weathercloud candidates remain unknown until
authorized read access and actual timestamp semantics are verified; no scraping.
