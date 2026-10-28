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


## Milestone 1.6.2 — bounded recovery delegation

The existing authenticated local worker passed model discovery and READY inference
at http://127.0.0.1:8888/v1. Actual active model:
`unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF` (17 model entries).
Two narrow proposals were requested, with relevant interface, constraints and tests:

| Task | Decision | Duration | Server tokens |
|---|---|---:|---:|
| m162-1: pure recovery counters | Counter structure partially adapted; malformed patch/docstring, UNVERIFIED logic and validation rewritten | 7.640s | 1246 |
| m162-2: isolated recovery tests | Rejected; malformed Python, incorrect one-failure inactivity and timestamp assertions; Codex wrote tests | 8.609s | 1384 |

Total substantive inference16.249s,2630 tokens. Separate health probe0.500s,31
 tokens. No automatic patch was applied. Corrected counter code and integration
are covered by regression tests. No repair loop followed the repeated defects.
No measured speedup or token savings is claimed. Sampling parameter acceptance
was observable; effectiveness was not independently verified except stream mode.
The existing JSONL audit records actual usage and review decisions. Collection has
no LLM dependency; no server settings changed.


## Milestone1.6.3

Existing authenticated worker at127.0.0.1:8888/v1 passed model discovery (17
entries) and READY inference. Actual model unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF.
M163-Q01 proposed a nearest-rank timing aggregation helper (8.719s,1248 tokens).
Grouping/percentile structure was partially adapted; Codex corrected bool metrics,
unknown success counting, strict typing and output shape. M163-Q02 proposed tests
(8.720s,1217 tokens); rejected for wrong package import, missing group keys, wrong
percentiles and invalid patch anchor. Correct tests were written directly; no
repair loop. Total substantive inference17.439s/2465 tokens; separate health31
 tokens. Actual decisions/usage logged in reports/dev/qwen_delegation.jsonl;
minimal proposals retained ignored under reports/dev/artifacts. Helper tests,
concurrent integration and actual measurements are independently reviewed.
No measured token savings or workflow speedup claimed. Weather runtime remains
independent of Qwen. Architecture and timestamp/publication semantics are Codex-owned.

## Milestone1.7

Health verified authenticated localhost8888/v1,17models, actual Qwen3-Coder-30B-A3B-Instruct-GGUF; READY generation31tokens/0.622s. Sampling parameters accepted but most effective values not exposed. Three bounded tasks:24.800s,3966tokens total. M17-Q01 metric aggregation rejected (wrong direction/baseline denominator/bias/validation); M17-Q02 tests rejected (Windows imports, datetime types and contradictory expected values). No repair loop. M17-Q03 general documentation cautions partially adapted; incorrect trend definition and12hours threshold rejected/corrected to same-sensor temperature change and12samples. Code/tests independently written and reviewed. No inference savings or validated workflow speedup claimed. Proposals retained ignored under reports/dev/artifacts; decisions in reports/dev/qwen_delegation.jsonl and m17_qwen_audit.json. Runtime never depends on Qwen.

## EXP-0010

Existing authenticated localhost8888/v1 Qwen3-Coder-30B-A3B-Instruct-GGUF verified active among16model entries; READY health generation0.525s/31tokens. Sampling accepted but effective values remain mostlyunverified. One bounded SQL-scope review E10-Q01:2.086s/576tokens, adapted into docs/research/EXP0010_SQL_REVIEW.md after independent source and test verification. Corrected wording clarifies that Python validatesUTC clocks/takesminimum, and startup/coverage censoring is separate. No scientific conclusions or production patches delegated to Qwen. Full audit in reports/dev/qwen_delegation.jsonl and exp0010_qwen_audit.json; proposal retained ignored under reports/dev/artifacts. No savings or validated inference efficiency claim.


## EXP-0011

Existing authenticated localhost8888/v1 worker verified active Qwen3-Coder-30B-A3B-Instruct-GGUF among17model entries; READY health0.553s/31tokens. Two bounded read-only parser reviews: Q01 6.620s/1193tokens and Q02 7.597s/2217tokens. Both rejected after independent verification: contract review confused a proposal with missing implementation; actual-code review alleged false integer/side/list-identity bugs. No output applied, no repair loop and no savings claim. Correct implementation and168newtests independently verified. Audit:reports/dev/exp0011_qwen_audit.json and qwen_delegation.jsonl. Runtime has no inference dependency.

## EXP-0012

Existing localhost8888/v1 worker verified Qwen3-Coder-30B-A3B-Instruct-GGUF among17models; READY health0.606s/31tokens. One bounded implementation proposal EXP0012-Q01 produced the pure Decimal price-bucket helper:4.327s,423prompt+372completion=795tokens. Accepted after independent boundary/NaN/range review and repository formatting; covered by automated tests. No rejection or repair loop. Position accounting, chain roles, matching paths, fees and scientific conclusions remained lead-owned. Audit:reports/dev/exp0012_qwen_audit.json and qwen_delegation.jsonl. No measured savings claim or runtime inference dependency.

## EXP-0013

28October2026 local worker health diagnosed localhost8888/v1 connection failure.
No active model or generation could be verified; zero actual delegated tasks,
unknown token usage, no savings claim. Continued with independently reviewed
implementation/tests rather than changing the inference server or either live
monitor. Sanitized audit:reports/dev/exp0013_qwen_audit.json. No runtime LLM use.
