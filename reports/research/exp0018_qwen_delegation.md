# EXP0018 local delegation audit

Model actually used: `unsloth/Qwen3.6-35B-A3B-GGUF`, existing
`qwen3.6-35b-a3b` MCP profile at local127.0.0.1:8888. No new wrapper,
model/sampling/quantization/server/credential/MCP changes. Connector health verified
18 models, selected model match, real generation, `enable_thinking=false` and
zero reasoning tokens in the health response. Health is DEGRADED solely because
effective sampler settings aren't exposed; API acceptance isn't verification.

Plan committed first: `fc3d7e2`. Architecture/integration/concurrency/clocks,
financial interpretation and acceptance owned by Codex. All10 identified local-
eligible tasks offered locally (100% task delegation, NOT code/token ownership).
12 actual MCP calls: health1, analysis2, patch8, research1. I1 had two attempts;
repeated contract errors triggered Codex takeover. No cloud-worker substitution.

| Task | Result | Independent review / tests |
|---|---|---|
| PROBE-A | REJECTED | Missed DST/naive-time risk |
| PROBE-P | ADAPTED | UTC helper, naive/DST tests pass |
| R1 | URL DISCOVERY ONLY | Snippets, zero verified findings; Codex opened official docs |
| I1 attempt1 | REJECTED | Wrong nested fields, clock call and serialization; memory cap broken |
| I1 attempt2 | REJECTED | Repeated interface errors, wrong ask sort, time cap missing |
| I2 | ADAPTED | Feature/delta structure; import, NULL/zero, staleness/reversal corrected |
| I3 | ADAPTED | Matching/ranking; ISO clocks, finite/missing metadata/output corrected |
| I4 | ADAPTED | Additive DOM layout; SVG/replay/timeouts/labels rebuilt and DOM tested |
| I5 | ADAPTED | 16 helper tests corrected for exact interfaces; causal tests added by Codex |
| A1 | REJECTED | Findings contradicted the explicit guards, retracted themselves |
| I6 | ADAPTED | Absolute-level replacement accepted with numeric error/finite-check corrections |

Eight actual patch proposals, six partially adapted (75% proposal adaptation;
six/seven unique implementation tasks85.7%). No raw proposal was applied blindly.
Unmodified first-attempt acceptance:0/7; raw-patch test-pass rate NOT MEASURED
(review precedes application). Accepted/adapted versions are verified with project
tests. First-attempt partially usable tasks6/7, within<=3 attempts also6/7; this
does not mean their raw code passed. Detailed JSONL records attempts and token
counts; ownership of integrated code remains Codex's responsibility.

Measured inference/research wall time209.162s excluding0.690s health generation.
Known task tokens25,413 plus35 health=25,448. Research token usage unavailableNULL;
total across ALL calls therefore UNKNOWN. Local research performed14 searches and
3 approved fetches within its native budget, yielding snippet-only evidence.
Human/model review and correction elapsed times weren't instrumented:NULL.
Task-specific per-call timestamps unavailableNULL; date is2026-10-31, sequence
recorded by task/attempt. End-to-end elapsed baseline wasn't instrumented:NULL.
No token savings, speedup or 80–90% code-ownership claim. Review overhead was high;
the read-only analyses supplied no useful independent correctness assurance.
Small patch scaffolds/auxiliary tests helped, but measurable net acceleration is
NOT ESTABLISHED. Prefer very small exact-interface helpers for future local work.

## Preservation note

The original JSONL is preserved unchanged. Its `sequence` field is report-assembly
order, NOT chronological tool-call order. Actual invocation order in this session:
HEALTH, PROBE-A, PROBE-P, R1, I1attempt1, I1attempt2, I2, I3, I5, I4, A1, I6.
Per-call UTC timestamps were not recorded; they remain unknown. Health metrics
are reported separately above, not present as a task row in the original JSONL.
An attempted JSONL rewrite was rejected by automatic approval review because it
could obscure the original audit trail. No rewrite was applied or retried.
