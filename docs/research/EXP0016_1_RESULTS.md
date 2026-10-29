# EXP0016.1 — observed result,29October2026

Baseline8e99c3e.14 Warsaw Tmax events discovered15–28Oct,14 fully settled market
labels certified by all closed/UMAresolved/binary payout markets and one Yes
winner. OutcomePrices alone are not sufficient.23Oct event1227844=14C;
26Oct event1244351=11C. Source references/rules preserved separately per event.

Important regime change:15–22Oct PRIMARY source was NOAA WRH timeseries
(https://www.weather.gov/wrh/timeseries?site=epwa), with Wunderground only as
fallback. Those8 labels remain VERIFIED_MARKET_ONLY; no historicalWRH table was
reconstructed or silently replaced with AWC. An early diagnostic description
calling their primary source Wunderground was incorrect and corrected after
reading the actual stored source/rules. No evidence rows were deleted.

23–28Oct use explicit AWC routine T-remark/body-fallback rules. All6 reconstructed
maxima match settled brackets:14,11,14,11,13,10C. Selected routine reports48/48/
50/48/48/48 respectively;25Oct has25localhours and distinct repeated02hour.
Exact resolution-source RAW and broader structured EPWA query are both retained,
including the next local day's routine report used for the provider-receipt cutoff.
The AWC schema defines receiptTime as source observation receipt, NOT our historical
collector receipt. Full expected half-hour coverage plus additional routine reports
and eligible provider receipts are the explicit current-archive certificate basis.

All6 labels are VERIFIED_SOURCE_AND_MARKET for independent reproduction, while
source_cutoff_certified=false and historical_source_state_at_resolution=NOT_ARCHIVED.
This does not claim possession of the source snapshot read by the resolver at that
past instant. Backfilled inputs and label creation remain dated29Oct. No observed
conflict among the6 verified days; the other8 cannot be tested against their proper
source with current evidence. A zero-data API response never authorizes lowest-bin
fallback; fallback and exceptional7day correction conditions stay explicit.

Forecasts: old14 ICON captures retained. Added35 individual00UTC model-run
normalizations in7batched successfulHTTPrequests (7dates21–27Oct×5models),
not stitched Forecast API history.
49 captures represent35 unique model/initialization pairs. The source API rejected
start_date and rejects daily aggregation for00UTC runs not aligned with requested
Warsaw midnight. Those actual HTTP400 bodies remain captured; valid requests use
hourly points and retain dailyAPI Tmax=NULL instead of substituting silently.
Original historical publication/availability is unknown. The predefined init+6h
scenario is APPROXIMATE_REPLAY, not proof of actual early availability.

30 approximate model/day pairs have fully verified labels (5models×6days), and
0 strict pairs have verified original forecast availability. Repeated06/12/18local
checkpoints and dependent models do not multiply independent days. Below are RAW
hourly-point-maximum deviations at D-1 noon, not direct dailyAPI forecasts or a
precision thermometer validation:

Model | Independent days | MAE C | Signed bias C | Exact integer
---|---:|---:|---:|---:
ICON Global |6|0.917|+0.217|2/6
ICON Europe |6|0.833|+0.300|2/6
ECMWF IFS |6|1.317|+0.217|1/6
ECMWF AIFS |6|1.350|-0.650|1/6
GFS |6|1.117|+0.817|3/6

Targets are reported qualifying maxima, predominantly quantized body integers;
these decimal errors are not precise physical-temperature bias. Interval-aware
agreement is exported separately. No fitted probability or robust model ranking
is supported by6days. Progress6/30trainingdays, plus20independent heldoutdays still
required. Model disagreement/error association is underpowered, not validated.
Existing frozen strategy rules and their calibration promotion NULL remain intact.

Dashboard uses existing static-file delivery of a thin audited catalog, so no
stable server or collector restart is needed. It hides labels when replay cursor
precedes catalog publication. Full chosen/excluded TAC observations and source
receipts are in report CSV/JSON and immutable local evidence. --report-only
regenerates fixed artifacts without network or database writes.

Dedicated taskMichuplPreMetar-D1Research-v1 installed with limited current-user
logon, no passwords, IgnoreNew, restart60s×3 and original absolute environment.
Actual task launch returned0 because the existing monitor lock was ALREADY_RUNNING;
no observer restart/duplicate. This is login startup, not pre-login boot execution.
No actual reboot, collector failure or live interruption was induced.

Primary documentation:
* https://aviationweather.gov/data/api/ — limited scoped queries and historical API.
* https://aviationweather.gov/data/schema/openapi.yaml — obsTime/receiptTime fields.
* https://open-meteo.com/en/docs/single-runs-api — requested UTC initialization is
  not public availability; actual parameter restrictions noted above.
* Captured per-event Gamma resolutionSource and complete descriptions are in
  reports/research/epwa_settlement/settlement_truth.json.
