# EXP0016.1 — EPWA settlement ground truth

Evidence audit published UTC:2026-10-29T17:49:01.926337+00:00. RETROSPECTIVE_BACKFILLED_LABELS_NOT_HISTORICALLY_AVAILABLE_SIGNALS.

Date | Raw qualifying maximum | Rounded integer | Market winner | Class | Source at historical cutoff
---|---:|---:|---|---|---
2026-10-15 | None | None | 13°C | VERIFIED_MARKET_ONLY | NOT_ARCHIVED
2026-10-16 | None | None | 14°C or higher | VERIFIED_MARKET_ONLY | NOT_ARCHIVED
2026-10-17 | None | None | 13°C | VERIFIED_MARKET_ONLY | NOT_ARCHIVED
2026-10-18 | None | None | 11°C | VERIFIED_MARKET_ONLY | NOT_ARCHIVED
2026-10-19 | None | None | 10°C | VERIFIED_MARKET_ONLY | NOT_ARCHIVED
2026-10-20 | None | None | 14°C | VERIFIED_MARKET_ONLY | NOT_ARCHIVED
2026-10-21 | None | None | 16°C | VERIFIED_MARKET_ONLY | NOT_ARCHIVED
2026-10-22 | None | None | 14°C | VERIFIED_MARKET_ONLY | NOT_ARCHIVED
2026-10-23 | 14.0 | 14 | 14°C | VERIFIED_SOURCE_AND_MARKET | NOT_ARCHIVED
2026-10-24 | 11.0 | 11 | 11°C | VERIFIED_SOURCE_AND_MARKET | NOT_ARCHIVED
2026-10-25 | 14.0 | 14 | 14°C | VERIFIED_SOURCE_AND_MARKET | NOT_ARCHIVED
2026-10-26 | 11.0 | 11 | 11°C | VERIFIED_SOURCE_AND_MARKET | NOT_ARCHIVED
2026-10-27 | 13.0 | 13 | 13°C | VERIFIED_SOURCE_AND_MARKET | NOT_ARCHIVED
2026-10-28 | 10.0 | 10 | 10°C | VERIFIED_SOURCE_AND_MARKET | NOT_ARCHIVED

Current official archive reproduction is a backfilled LABEL certificate, not proof of original collector availability or an archived resolution-time source view. Provider receiptTime is preserved separately from actual backfill receipt. Exact-source RAW plus structured archive and full half-hour schedule coverage required; off-hour routine reports included, SPECI excluded.

Counts:{'VERIFIED_MARKET_ONLY': 8, 'VERIFIED_SOURCE_AND_MARKET': 6}. Required independent training days30 plus20heldout; probabilities remain blocked.

Forecast errors and sample counts: calibration/ files; dailyAPI Tmax never silently replaced by maximum hourly points. Approximate init+6h replays are distinct from verified availability.

Fallback Wunderground/no-data lowest-bracket conditions are not assumed from missing API records. Missing corrected predecessor or incomplete cutoff/coverage lowers verification. No production or frozen strategy changes.
