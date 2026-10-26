# Receipt-query review

Local Qwen reviewed the existing first_target_receive query and returned the
following verified observations. Codex checked these against source and tests:

- The join uses report_receipts.observation_id=observations.id; it preserves
  separate source receipt events rather than a station discovery/update clock.
- There is no provider or COR filter, so every configured provider/version
  participates. Python parses aware UTC clocks, checks exact nominal equality
  after the SQLite julianday filter and takes the earliest valid receipt.
- product_type=METAR excludes SPECI from routine target matching.
- No source publication timestamp is invented by the query or join.
- Earliest receipt closes the opportunity even before nominal observation,
  including previously observed early KNMI reports.
- This is OUR recorded first receipt, not proof of global public availability.
  Startup/coverage censoring and clock uncertainty remain separate checks.

No production SQL or policy was changed. Qwen's note was adapted for precision;
Codex owns timestamp semantics and the scientific interpretation.
