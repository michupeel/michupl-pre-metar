# Local Qwen development workflow

## Actual milestone use

The installed `local_worker` connector was discovered and reused. Its DPAPI-backed
credential remained inside the connector. No credential file was opened, copied
or committed by this task. An unauthenticated `/v1/models` request returned 401;
the connector's authenticated health probe returned 17 models and identified the
active `unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF` at
`http://127.0.0.1:8888/v1`. A real generation returned READY.

The server reports native non-thinking Instruct mode and no reasoning support.
The connector verified its requested sampling fields against the API schema;
most fields' effective values were **not** independently confirmed. The server's
global configuration was not changed.

Seven bounded tasks plus one health generation were actually invoked:

| Task | Result accepted after review | Rejected/corrected |
|---|---|---|
| Geometry implementation | haversine scaffold | pole/antimeridian bounds; antipode numeric clamp |
| Temporal QC implementation | diagnostic structure, median/p90 direction | age/span, duplicate conflicts, future samples, stuck logic |
| Temporal repair | none as a complete patch | unresolved defects; Codex took over |
| Geometry tests | useful edge-case list | invalid Python and incompatible tuple signatures |
| Geometry test repair | several regression cases adapted | invalid antipodal coordinate and bbox expectations |
| Analysis review | more explicit datetime comparisons | incorrect <= exclusion change, unsupported race/empty-list claims |
| Methodology draft | clocks/QC outline adapted | invalid patch match and invented station/tie/provenance behavior |

All accepted code was manually integrated and exercised by offline tests. No
Qwen patch was automatically applied. Outputs are review material, never API or
licensing authority. Invalid proposals were not counted as successful tests.
The recorded calls returned 18,771 total tokens, including 31 for health, and
about 90.3 seconds of reported generation time. These are local server-reported
counts, not a cloud-token savings estimate. Sampling settings and connector
overhead prevent a meaningful speed comparison. Local assistance helped produce
bounded artifacts, but correctness review and repair were substantial.

`reports/dev/qwen_delegation.jsonl` contains task IDs, audit timestamps, generation
duration, status, model, returned token usage and acceptance decisions. Timestamps
label audit-record creation, not reconstructed generation start times. Full prompts
and source files are not logged. Generated proposals are saved locally under
ignored `reports/dev/artifacts/`. Only the small sanitized JSONL audit is committed.

## Reusable CLI fallback

The connector remains the preferred interface on this workstation. The repository
also provides `scripts/dev/qwen_worker.py` for ordinary OpenAI-compatible private
servers without coupling collectors to a particular Codex installation:

```powershell
$env:LOCAL_LLM_ENABLED="true"
$env:LOCAL_LLM_BASE_URL="http://127.0.0.1:8888/v1"
$env:LOCAL_LLM_MODEL="auto"
$env:LOCAL_LLM_TIMEOUT="120"
$env:LOCAL_LLM_MAX_CONCURRENCY="1"
# Set LOCAL_LLM_API_KEY through your credential manager if the server needs it.
uv run python scripts/dev/qwen_worker.py health
uv run python scripts/dev/qwen_worker.py ask --task "Review temperature validation" --file src/premetar/pws/quality.py --max-tokens 2048
uv run python scripts/dev/qwen_worker.py ask --task-file tasks/review.md --json
```

No automatic .env loading. The client only accepts local/private destinations,
does not follow redirects or expose a server, bounds context/output and timeouts,
discovers a unique Qwen ID or requires an explicit model, retries transient
transport/5xx failures and respects bounded Retry-After. JSON requests are opt-in;
unsupported JSON mode fails visibly. A file lock enforces one CLI generation at
a time. It supports selected repository source/docs/config inputs, not arbitrary
data/credential directories. Review selected files for secrets before delegation.

The fallback does not decrypt the connector's DPAPI key or assume an arbitrary
model-specific thinking flag. Its localhost authentication failure is expected
without an externally supplied key; actual milestone implementation used the
authenticated connector. Logs contain safe classes/usage, not exception text,
headers, credentials or full source. Artifacts are ignored and must be reviewed.

## Milestone 1.6 — actual local delegation (2026-10-24)

Health/model discovery and a genuine inference probe succeeded through the existing
authenticated local-worker connector at http://127.0.0.1:8888/v1. Actual model:
unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF. The /models response exposed17 model
entries; the connector identified the active Qwen rather than assuming its ID.
The small generation health probe returned READY (2 output tokens, about0.634s).
No credential was read, copied into the repository or exposed. No server/global
sampling setting changed. Accepted sampling parameters do not prove effectiveness;
the connector's sampling efficacy checks remain partly unverified.

The existing scripts/dev/qwen_worker.py remains the reusable CLI fallback; no
second wrapper was introduced. Development used its already documented authenticated
connector route. The weather collector has no inference dependency.

Six substantive calls were made, including one narrowed test retry:

| Task | Scope | Decision | Measured generation |
|---|---|---|---|
| M16-Q01 | Median cadence, bounded backoff, provider-state helper | Partially adapted; added finite-bound validation and naive-clock rejection | 9.740s,1348 tokens |
| M16-Q02 | Windows task XML proposal | Rejected: invalid patch anchor and incorrect Task Scheduler schema elements | 7.004s,958 tokens |
| M16-Q03 | Polling unit tests | Rejected: truncated4096-output-token response | Duration unavailable,4474 tokens |
| M16-Q04 | Narrowed polling tests | Rejected: misspelled imports, wrong timestamp types and incorrect sample-count expectations | 6.211s,848 tokens |
| M16-Q05 | Descriptive lead percentiles | Partially adapted; fixed positive infinity passing validation | 5.657s,780 tokens |
| M16-Q06 | Independent Windows ownership review | Partially accepted SID verification issue; rejected unsupported path-injection claim and false return-code finding | 7.043s,2809 tokens |

Returned total usage:11217 tokens including prompt/output and cached prompt tokens
as reported by the server. Known generation durations sum to35.655s, excluding the
truncated response whose duration was unavailable. These are local usage metrics,
not cloud-token savings or end-to-end speedup measurements.

All proposals were reviewed. No unrestricted file edits or autonomous agent loop
was allowed. Two unsuccessful test outputs ended local repair; Codex wrote the
tests. Accepted helpers/settings changes have deterministic tests and strict typing.
The final suite and live validation are recorded in CONTINUOUS_VALIDATION.md.

Net assessment: small helper proposals supplied useful starting points. Tests and
Windows schema generation were unreliable, and the review included confident false
positives. Review cost was substantial; no measured workflow speedup is claimed.
The audit appends to reports/dev/qwen_delegation.jsonl. Full proposals remain in
ignored reports/dev/artifacts; credentials and unnecessary source context are not
included in the committed audit.


## Milestone 1.6.1 — actual bounded delegation

Health/model discovery and a small READY inference succeeded on the existing
authenticated local worker at http://127.0.0.1:8888/v1 (17 model entries). Actual
model: unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF. Three substantive tasks:

| ID | Task | Decision | Measured duration / tokens |
|---|---|---|---|
| H161-Q01 | Local calendar bounds and fold-preserving buckets | Partially adapted; corrected inclusive end to next midnight | 6.873s / 961 |
| H161-Q02 | Isolated timestamp tests | Rejected; wrong imports/statuses and malformed test cases; rewritten by Codex | 8.718s / 1153 |
| H161-Q03 | Independent timestamp policy review | Rejected; false path-traversal claim and unsafe absolute-age suggestion | 9.748s / 3735 |

Total substantive inference: 25.339 seconds, 5849 server-reported tokens. The
separate tiny health probe used 31 tokens/about0.627s. No token savings estimate
is claimed. Review overhead again limited benefit; no repair loop was used. The
accepted date helper was tested for Warsaw day bounds and both DST transitions.
Proposal artifacts remain ignored, sanitized decisions/usage are appended to the
existing audit JSONL. Audit timestamps identify recording time, not inferred
inference-start times. Weather collection has no LLM dependency.
