# michupl-pre-metar

## Project commands

- Setup: `uv sync --locked` (Python 3.12+).
- Test: `uv run pytest`.
- Lint/type check: `uv run ruff check .` and `uv run mypy`.

## Repository-specific constraints

- Independent research repository: no runtime dependency on the parent lab.
- Research only: no order submission, private keys, or authenticated trading.
- Raw payloads must be durable before parsing. Never log credentials or signed URLs.
- Preserve provider receipt events, COR, AUTO, SPECI and full original TAC.
- Missing source timestamps stay NULL. HTTP Last-Modified is not a sensor/publication clock.
- Only uncensored prospective first receipts support latency evidence. Monotonic clocks are run-scoped.
- Document verified adapters in docs/sources.md. Credential-dependent optional adapters default disabled.
- Preserve working baselines and unrelated user changes.
