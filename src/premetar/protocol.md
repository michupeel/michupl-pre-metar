# EXP-0001 — prospective baseline, version 1.1

Question: Can public high-frequency airport observations predict routine METAR
temperature before our earliest observed full-report receipt?

Baseline: round TT_10 to nearest Celsius integer, exact ties toward warmer.
No ML, fitted probability, trading or causal attribution. Source sensor parity is
unverified. EDDM/DWD is A; EHAM/KNMI is B. B awaits a verified 10-minute adapter/key.

Capture complete response receive wall clock and monotonic clock before disk IO.
Immutable fsynced raw precedes parsing. Missing upstream clocks stay NULL.
All provider receipts are retained. First successful poll is startup-censored.
New identities following a collection gap >2.5 polling intervals are gap-censored.
No historical-event-only, startup-censored or gap-censored rows enter latency tests.
Run monotonic clocks never join across restarts. Polling gives an upper bound on
first availability, not exact publication. Public-first means first among our
configured channels only. Known shared upstream and outages qualify source races.

Match candidate to the first routine nominal report at or after its event time,
same station, same run, within 30 minutes. A previously received target is rejected;
never skip it to find a favorable later report. SPECI and COR remain separate raw
versions and receipts; initial routine non-COR temperature is the baseline target.
Unexpected off-schedule routine reports interrupt next-report matching; do not
skip them. Multiple inconsistent initial reports at a nominal time are excluded.
Candidates must be known strictly before full-report receipt in receive order.
Candidate/request intervals overlapping the target request are marked uncertain.

Report event-relative delay separately from actionable monotonic lead. A positive
observed lead can result from polling: also report target request start minus
candidate complete receive to flag overlapping requests. This is NOT a lower
bound on publication lead; the target may already have been available before
the request began. Publication time and a publication-lead bound remain unknown.
Accuracy uses latest
candidate per target/source/lead bucket, not repeated polls. Report paired cycle N,
coverage, exclusions, MAE, bias and exact/±1 integer match. No threshold selection
after looking at outcomes. Insufficient data is distinct from no edge.
At least 100 paired routine cycles across 3 UTC days are required even for a
preliminary conclusion; strong/99% claims require a later frozen validation design.
Ex-post first/stable correct times are descriptive, not actionable estimators (M2).
