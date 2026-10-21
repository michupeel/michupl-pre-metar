# Research log

## EXP-0001 — public high-frequency observations before routine METAR

Date:2026-10-21 UTC.

Question: Can airport observations predict the next integer METAR temperature
before our first full-report receipt from monitored dissemination paths?

Data: prospective immutable HTTP captures, initially EDDM/DWD (A), EHAM/KNMI(B),
with AWC/KNMI METAR receive comparison. No historical-only latency evidence.

Method: naive WMO Celsius rounding; target chosen by station/nominal order before
correctness is evaluated. Exclude startup, gaps, historical and cross-run clocks.
Report accuracy/MAE/bias and receive lead by fixed buckets. Frozen protocol is
copied into each run manifest. No ML/probability fitting in M1.

Result: initial smoke confirms working AWC, DWD10min and KNMI full-report capture.
It is too short and startup-censored to establish edge. See docs/verification.md
for actual counts and identities. Version1 produced no latency pairs; version1.1
clarifies request overlap is not a publication lower bound and records the precise
monotonic clock implementation.

Conclusion: INCONCLUSIVE / INSUFFICIENT DATA. A successful HTTP/parser test is not
an information edge result. Any negative conclusion requires adequate coverage.

Next: collect multiple days, review freshness and exclusions; implement authorized
KNMI10min/notifications and expand EDDM full-report race only after verification.

### EXP-0001A — EDDM / DWD

Verified DWD01262 München-Flughafen (WMO10870). Live ZIP contains TT_10,TD_10,QN,
pressure and UTC MESS_DATUM. TT_10 is documented instantaneous2m temperature.
Publication cadence is a bottleneck to measure: `now` is documented as hourly/
less than1h, unlike10-minute observation sampling. Sensor parity unverified.

### EXP-0001B — EHAM / KNMI

Direct no-key KNMI full METAR works and preserves original TAC plus upstream
translation receipt. Second path AWC works. KNMI10min candidate adapter is pending
API-key/format verification, so no EHAM predictive accuracy is claimed.
