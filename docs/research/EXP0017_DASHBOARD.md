# EXP-0017 dashboard integration

The independent **HIGH TEMPTATION — ENTRY TIMING** panel reads the locally
generated `/static/entry_timing_summary.json` once per minute. It makes no
external API requests and performs no database writes or order submission.
It can be served by the already running dashboard without a Python restart.

Include the following assets in the existing page head:

```html
<link rel="stylesheet" href="/static/entry_timing.css">
<script defer src="/static/entry_timing.js"></script>
```

The panel is inserted after the settlement history section, or after the D−1
section when the history section is absent. All data-derived text is inserted
using `textContent`; source metadata is never treated as HTML. Percentages in
the JSON contract are values from zero to one hundred. NULL means unknown,
never a zero event count. Samples and schedule-matched denominators are shown
separately. All-airport and EPWA results have independent controls.

Historical replay uses the existing `window.dashboard.state` inspection cutoff.
The audit is hidden before its actual `published_at` time; it is not presented
as information available when the historical trades occurred. The underlying
research may contain retrospective source evidence, which is not a live signal.

Visible distinctions include:

- Nominal report time versus first local receipt versus unknown decision time.
- Raw number of executions versus a matched-background rate.
- Grouped economic executions versus independent trader decisions.
- End of the local calendar day versus actual market resolution time.
- Executed subsequent SELL versus unknown exit-order placement.
- Conditional reconstructed inventory versus a complete on-chain ledger.

No financial performance is fabricated when execution or inventory evidence is
missing. Empty, unknown and not-identifiable states remain explicit.

The dependency-free synthetic DOM smoke checks rendering, literal untrusted
text, the EPWA switch, pre-publication replay hiding and bounded local requests:

```powershell
node --check src/premetar/dashboard/static/entry_timing.js
node tests/js/test_entry_timing.mjs
```
