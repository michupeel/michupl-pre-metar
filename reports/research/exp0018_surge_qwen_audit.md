# EXP0018.1 local Qwen audit

Actual model: `unsloth/Qwen3.6-35B-A3B-GGUF`, configured local endpoint `http://127.0.0.1:8888/v1`. Models endpoint and actual inference verified; no server restart or cloud substitution. Non-thinking format worked. Effective sampler and server token-context limit remain unverified. Worker input cap 150000 characters is not model context length. Maximum requested output 8192 tokens; largest actual completion 3405.

Eight eligible task IDs (S1–S7 plus S11 exact transaction join helper), twelve patch generations, one health inference. Seven tasks yielded accepted useful contributions (87.5% task-level): state classifier, surge detector, liquidity diagnostics, delayed association helper, narrowed tests, narrowed safe DOM metric, exact raw transaction join. Five retained the original scope; two were substantially narrowed. S2 rolling buffer was taken over after two failed proposals. This is not 87.5% code ownership. Codex implemented integration, causal clocks, replay/chain review, safe UI and independent regression checks.

Measured native generation 181.941 seconds; health 0.773 seconds. Known patch tokens 25441 plus health 35 = 25476. Active review time was not instrumented and is NULL. No direct Codex timing baseline exists; acceleration is UNKNOWN. Review/correction overhead was substantial.

Rejected defects included unsafe innerHTML, future-data exposure, invalid clocks, timedelta.seconds, wrong liquidity identity, duplicate/eviction bugs and tests against nonexistent interfaces. Two test proposals failed the local patch envelope protocol; the narrowed complete replacement was manually reviewed and tested. No security restriction was bypassed. Each accepted result was integrated under the 1144-test suite, Ruff and strict mypy.

The append-only JSONL records actual attempts, durations, returned tokens, acceptance, reasons where recorded and test outcomes. `generated_replacement_bytes` in that existing log was measured with JavaScript string.length: it is UTF-16 code-unit count, not a reliable UTF-8 byte measure. Generated line counts and the integrated file sizes below are separate; integrated size includes Codex changes and is not an authorship metric.

| Integrated file | Lines | UTF-8 bytes |
|---|---:|---:|
|surge_states.py|68|1980|
|surge_detector.py|82|2814|
|surge_liquidity.py|188|7221|
|surge_associations.py|85|2885|
|surge_identity.py|54|1657|
