# Milestone 1 architecture

`sources.py` owns expected UTC schedules and verified public endpoints. Each
HTTP source has an isolated async poll loop in `collector.py`. `httpx` buffers
the full response, then the collector immediately records UTC and monotonic
request/receive clocks. Native certificate trust is enabled via `truststore`;
TLS verification is never disabled. Redirects and 401/403 disable only that source.
429 respects Retry-After and exponential backoff. No burst polling is enabled.

`store.py` serializes blocking work in one dedicated disk thread. It writes an
exclusive, fsynced, immutable raw envelope with byte-exact Base64 body, SHA256,
safe URL and selected headers. Only after that acknowledgement does it parse and
commit observations to SQLite (WAL, FULL synchronous, foreign keys). Parser errors
preserve raw; storage failures are visible collector failures. Work in flight is
bounded by the number of sources. Shutdown drains writes and closes the run.

SQLite has runs, raw_payloads, observations, canonical_reports, report_receipts,
source_health and errors. `data_json` retains the entire typed observation model;
commonly queried identity and clock fields also have SQL columns. An identical
report from different sources has distinct observations and receipts, linked to
one canonical identity. Every repeated METAR response adds a receipt; the first
normalized source/run observation is immutable. DWD row revisions are separate
identities; repeated unchanged rows retain their first receipt. All HTTP bodies
remain available, even if parsing or DB insertion fails. Manifests freeze the
protocol and configured source set. Historical rows never acquire fabricated
receive clocks.

`analysis.py` joins only within a run. It chooses the next nominal report before
testing receipt order, never skips an inconvenient report, and rejects startup,
gaps, ambiguous initial versions, historical-only and late inputs. Main accuracy
uses latest candidate per report/source/lead bucket (selection independent of
correctness). Request overlap is reported separately from receive-order lead;
request start is not a bound on earlier public availability.
Raw parsers are independently reusable for future rebuild tooling. Automated raw
DB rebuild/migrations, full stability analysis and probabilities are M2.

One process owns a database lock. A crashed process can leave a lock; confirm
the process is dead before manually removing that exact lock. Do not run a second
collector against the same DB. Restart starts a new run and startup baseline,
without deleting earlier data. One DB/schema version is currently supported.

Optional KNMI10min, METAR.ws and D-ATIS are explicit disabled capabilities. Their
keys are not read, copied, logged or used by M1. No network activity reaches the
existing weather bot or its files/processes. No trading code is present.
