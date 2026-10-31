# EXP0018 task queue

Plan baseline: `6d2c9e8`. Allowed changes only EXP0018 modules/tests, research
documentation/reports and an additive dashboard panel. Existing collectors stay
unchanged. All local tasks get explicit source, interface, constraints and tests.

| ID | Class | Deliverable / acceptance | Owner |
|---|---|---|---|
| P0 | CODEX_ONLY | Architecture, causal clocks, approval boundaries, plan commit | Codex |
| PROBE-A | QWEN_ANALYZE | Minimal DST clock review; independently verify | Qwen/Codex |
| PROBE-P | QWEN_IMPLEMENT | UTC signed duration, reject naive datetime; DST tests | Qwen/Codex |
| R1 | QWEN_RESEARCH | Official WS semantics and attribution limits; independently open docs | Qwen/Codex |
| I1 | QWEN_IMPLEMENT | Bounded snapshot ring, paired as-of lookup, invalidation, explicit coverage | Qwen/Codex |
| I2 | QWEN_IMPLEMENT | Pure causal price/depth features, missing inputs NULL, finite values | Qwen/Codex |
| I3 | QWEN_IMPLEMENT | Deterministic control matching and pending attribution, no future selection | Qwen/Codex |
| I4 | QWEN_IMPLEMENT | Small additive Polish dashboard panel, safe DOM, replay cutoff | Qwen/Codex |
| I5 | QWEN_IMPLEMENT | Auxiliary behavior tests for clocks/ring/features/controls | Qwen/Codex |
| I6 | QWEN_IMPLEMENT | After measured snapshot gap: absolute-level replacement utility | Qwen/Codex |
| A1 | QWEN_ANALYZE | Isolated independent implementation review | Qwen/Codex |
| C1 | CODEX_ONLY | Reader/runner, immutable provenance, source protection and restart correctness | Codex |
| C3 | CODEX_ONLY | Separate bounded paired socket, raw-first integration, frozen manifest and budget | Codex |
| D1 | DETERMINISTIC | Baseline tests, source coverage counts, bounded smoke, report generation | Tools/Codex |
| C2 | CODEX_ONLY | Interpretation, economic uncertainty, final diff/review and release | Codex |

Local-eligible tasks: PROBE-A, PROBE-P, R1, I1-I6, A1 (ten); all will be offered
locally where service remains usable. This is a task-count target, not evidence
of 80–90% code ownership or measured speedup. Retries do not increase task count.

Implementation sequence: probes -> plan commit -> I1/I2/I3 -> C1 -> I5 -> I4 ->
tests and A1 -> bounded smoke/report/UI -> final verification/commits/push.
Record accepted/adapted/rejected output and measured inference separately from
unmeasured review time. Inadequate evidence blocks trigger promotion, not truthful
coverage reporting. Persistent operation/new subscriptions require final approval.
