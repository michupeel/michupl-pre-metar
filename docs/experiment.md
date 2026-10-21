# EXP-0001

Question: Can legal public high-frequency airport observations predict the
integer temperature in the next routine METAR before our first observed receipt?

Baseline is `TT_10` rounded under WMO FM15. Hypothesis A: EDDM/DWD supplies timely
and sufficiently close values. Hypothesis B: EHAM/KNMI10min may do so; it remains
pending adapter/key verification. There is no assumption that sensors coincide.

See the executable run-frozen [protocol](../src/premetar/protocol.md). Expected
routine minutes configure monitoring; they do not guarantee actual issue or
publication times. Retain SPECI and COR but do not merge them into routine targets.
M1 reports basic same-station next-report pairs and provider receive race. M2
adds stable prediction, confidence intervals and held-out calibrated probabilities.

Do not fit a method using target temperature or choose only correct early rows.
Historical event-only data can support accuracy/training, never latency evidence.
Even captured first receipt is interval-censored by polling and may miss an earlier
publication through an unmonitored channel. Clock diagnostics do not prove a
subsecond absolute UTC offset. Within-run monotonic subtraction avoids wall-clock
steps. Observation-relative delay is a different column from actionable lead.

No data means INSUFFICIENT DATA. A negative edge result requires enough monitored
cycles, documented coverage, accuracy and uncertainty. Do not call a handful of
correct rows a 99% estimator. M1 always labels its conclusion as preliminary and
insufficient for strong claims. Read reports/latest.json for explicit exclusions.

Roadmap: M2 KNMI NetCDF + authorized notifications, METAR.ws adapter and source
race coverage for EDDM; M3 documented D-ATIS, EPWA, EGLL. Market integration would
be a separate future research milestone; no trading is implemented here.
