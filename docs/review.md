# Milestone 1 review notes — 2026-10-21

The local Qwen code-analysis connector received only `analysis.py`, without keys,
network access or write permissions. Its two findings were checked against code:

- Claimed next-report list was unsorted: rejected. `targets` is explicitly sorted
  by event time before filtering. An unsorted-input behavioral test verifies it.
- Claimed missing clocks become zero in source race: rejected. `eligible()` rejects
  None clocks before grouping/comparison. A missing-clock behavioral test verifies it.

Independent manual review did identify and fix three real issues before release:

- Acquiring a DB lock after opening/writing the run could leave a phantom run from
  a rejected second process. Acquire lock before Store.open; test checks no new run.
- Request start is not a lower bound on publication time. Version1.1 protocol and
  output call it request-overlap context, with publication bound unknown. Version1
  smoke manifest is preserved; it produced zero latency pairs.
- Windows `monotonic_ns` had reported15.625ms clock resolution in first smoke.
  New runs use monotonic high-resolution `perf_counter_ns`; resolution and clock
  name are frozen in the manifest. No timestamps in previous runs are rewritten.

Additional guards: preserve first source/row receipt across duplicates, exclude
startup and gaps, never bridge run clocks, retain COR/SPECI, distinguish nominal
AWC reportTime from TAC observation time. Provider race cannot prove global first
publication. Read docs/verification.md for actual smoke evidence and limitations.
