# EXP-0014 / EXP-0015 operations and source audit

Baseline0c8f8ab; feature branch research/epwa-forecast-vs-limit99. Independent
research only. No signed API, wallet, key, authenticated trading client or order
submission endpoint exists in this subsystem. Dashboard controls are GET-only.

## Commands (PowerShell)

```powershell
Set-Location D:\metar-execution-lab\michupl-pre-metar
uv sync --locked
uv run python -m premetar.research.battle_monitor watch
uv run python -m premetar.research.battle_monitor status
uv run python -m premetar.research.battle_monitor report
Start-Process 'http://127.0.0.1:8766/'
```

Reproduce the exported journal cutoff against retained immutable segments:

```powershell
$studyReport = Get-Content .\reports\trader\exp0015_summary.json -Raw | ConvertFrom-Json
uv run python -m premetar.research.battle_monitor report --at $studyReport.journal_cutoff
```

`cutoff` is the latest portfolio metric timestamp; `journal_cutoff` includes the
last exported event. Replaying this exact journal cutoff excludes later outcomes.
Closed known positions receive limited resolution-only checks after their day
ends, even if the reused source omits closed contracts. This adds no quote polling
when there is no overdue known inventory.

Do not launch watch when its research monitor.lock is held. The already running
instance survives terminal closure via a hidden process. No new Windows task was
installed: after workstation reboot manual watch startup is required. Weather and
HighTempTation task configurations/processes are untouched. Restart restores cash,
inventory, pending orders, control cohort and source cursors; it is not a fresh100USD
deposit. Bootstrap restores subscription identity, censors the interrupted feed
range and waits for a newly received full snapshot. It cannot turn offline history
into prospective fills. Current queue evidence is invalidated on restart/gap.

Graceful stop of this experiment ONLY:

```powershell
Set-Content -LiteralPath .\data\research\epwa_battle\stop.request -Value stop
# Wait until this experiment's monitor.lock disappears.
# To resume deliberately, remove only this experiment's stop marker:
Remove-Item -LiteralPath .\data\research\epwa_battle\stop.request
uv run python -m premetar.research.battle_monitor watch
```

## Storage and continuation

The separate journal data/research/epwa_battle uses immutable hash-linked events
and an atomic mutable checkpoint. Daily UTC or100MB segment rotation inherits
state before publishing a manifest. Settlement days still use Warsaw calendar
midnights, including23/25hour days. Total storage cap2GB, free disk floor1GB, maximum
segment count and bounded readers; no automatic deletion. At the cap the study
stops safely and requires a retention/storage decision. Logs rotate5MB×4. There
is no arbitrary24hour stop. Read-only replay scans at most30segments and exposes
truncation; a longer analysis must explicitly work from retained archives.

While EXP0013 runs, this sidecar tails its existing compressed raw WS captures;
there is no duplicate public market subscription or second full-depth archive.
It projects full books through the existing BookTracker. Only decisions/fills
retain necessary depth in the new ledger. If the existing EXP0013 owner exits,
the study may open ONE EPWA-only fallback socket, raw-first into the same bounded
segments. Unknown ownership blocks handover. If that owner resumes, this study
closes its own fallback. Fallback metadata refresh uses existing discovered IDs,
public Gamma only, every15minutes, and retains raw responses first. This is bounded
coverage of the existing universe, not an assertion that every listed EPWA contract
is monitored. No unrelated process is controlled.

The audit measured23.7GB free on D at22:16UTC28October. A supported SQLite weather
backup passed quick_check; the independent paper journal also passed. Full evidence
and backup SHA256: reports/research/exp0014_15_operations.json. No unsafe WAL file
copy, migration or write to production weather/trader databases occurred.

## Forecast/source semantics

Expanded EPWA fields require one justified extra request per30minutes to the public
Open-Meteo forecast API with explicit icon_global, Warsaw daily aggregation and
epoch-second hourly clocks. It adds clouds, humidity/dew point, wind, precipitation,
radiation and daily temperature_2m_max, which the older temperature-only capture
does not contain. Actual requests returned HTTP200; all11 requested hourly variables
and daily variable are retained raw before parsing. Temperature is an instantaneous
hourly point, precipitation preceding-hour sum, shortwave radiation preceding-hour
mean, daily API maximum provider daily aggregation. None is silently an hourly
maximum or final market settlement temperature. Missing values remain null.
Original publication/run association is unknown; first receipt is actual local
receipt, not generationtime_ms. Cloud fractions are model variables, not invented
METAR percentages. CAVOK/NSC/NCD never mean cloudless.

Primary documentation verified28October2026:

* [ICON variables/semantics](https://open-meteo.com/en/docs/dwd-api).
* [Open-Meteo terms](https://open-meteo.com/en/terms): public noncommercial research,
  CC BY attribution; this study does not authorize commercial API use.
* [Public market stream](https://docs.polymarket.com/market-data/realtime-data):
  full books, changes and anonymous last-trade side/size/optional clock. A market
  trade feed is not evidence of our own order, queue priority or decision time.
* [Post-only semantics](https://docs.polymarket.com/trading/place-orders): rejects
  immediately marketable post-only orders. Simulated taker entry uses FAK-style
  partial execution and cancels remainder, never an unbounded market order.
* [Fees](https://docs.polymarket.com/trading/fees): market-specific match-time fees.
  V1 deliberately supports only captured explicit current zero schedule; unknown
  or nonzero unsupported schedules block execution. No historical fee substitution,
  rebates, fabricated gas or unverified redemption cost assumption.

No new live-weather feed, paid API, Weathercloud scraping or clock changes.
Existing clock verification remains UNKNOWN; no millisecond accuracy claim.

## Research interpretation

Rules: EXP0014_RULES.md and EXP0015_PROTOCOL.md; exact frozen numerical config is
copied/hash-recorded at RUN with implementation hashes. Initial90second bounded
smoke and subsequent continuous capture are real prospective records. Original
prototype/STOP/restart-gap events remain immutable. Realization v1.1 fixes the
remaining-warming display to consider FUTURE same-day forecast points, rather
than presenting a past daily peak as remaining warming. V1 events remain; no paper
orders/fills existed when this semantic correction was made. Thresholds were not
optimized against outcomes. HYBRID also requires an assessment no older than90s.

WEATHER remains SIGNAL-ONLY. SIMPLE ignores meteorology; HYBRID alone applies the
frozen gate. Primary and0.98 control are separate families, not merged curves.
Anonymous trade-clock/side and queue assumptions make evidence-supported maker
execution conditional. PESSIMISTIC no-assured-fill is NOT a lower profitability
bound: a resting real order might instead fill adversely. Maker net profitability
has no identified lower bound from these public data; optimism is never observed
execution. Direct and theoretical complementary paths are separate.

The first real strict-range opportunity was a maker bid, not an executable taker
ask. Its15 latency/scenario replicas of ONE opportunity lacked arrival-book evidence.
Original prototype rejection events remain append-only. ACCOUNTING_EXCLUSION
events identify them as unknown execution, reserve their possible BUY debit and
exclude the affected zero-PnL metrics from valid economics. Historical plots apply
an exclusion only when that audit event was already available by the cursor.
No unknown quantity is silently turned into confirmed zero inventory or free cash.
Tick-change messages block new execution until matching fresh metadata verifies
the new constraint. Queue invalidation is scoped to the affected instrument.

Current tables include unfilled orders and open holdings. Unknown liquidation
means unknown equity, plus explicit stress/per-winner risk. Closed-only metrics
are labeled; no win rate for unresolved holdings. Capital-time accrues at actual
inventory changes. Portfolio numbers are cumulative as of the latest recorded
metric before the cursor; event timelines use the selected local day. Observed
calendar days include partial days; completed portfolio days are separate.
Random/window controls and follow-up quote horizons are analytical observations,
not invented alternate fills. No day-cluster inference or weather attribution
is justified by the initial window.

Risk uses a conservative full-cost exposure bound, including unknown BUY debit;
it never assumes diversification across temperature contracts. The exported
single-winning-condition loss vector is explicitly conditional: an exhaustive,
disjoint partition has not been independently certified by this implementation.
It is not presented as a guaranteed worst-case bound. No resolved position or
maker strategy profitability is inferred from the initial unsuccessful entries.

Machine-readable schemas:

* exp0014_metar_alignment.csv: one METAR/forecast identity pair, original nominal
  and first-receipt clocks, raw TAC conditions, aligned model temperature,
  interpolation label, quantized interval residual and initial evaluation time.
  Bootstrap references are separate from prospective receipt evaluations.
* exp0015_events.csv: global event id, at(UTC ISO), kind and JSON payload. Includes
  submissions, unsupported/rejected/unknown attempts, fills, cancellations,
  controls, accounting exclusions and source-version records; raw HTTP/WS bodies
  remain in the journal, rather than being duplicated into CSV.
* exp0015_portfolios.csv: separate family/mode/scenario/latency portfolios, USD
  cash/PnL, exact-string holding-time ledger, unknown execution/inventory, reserves,
  open risk and explicit conditional/unidentified metrics. Never sum variant
  capital as if it were one portfolio. No zero is substituted for unknown PnL.

The current temperature trajectory and daily Tmax diagnostics are separate. A
forecast can match the latest9C METAR while its11.8C sampled daily peak remains
above the maximum10C received routine report. That1.8C gap is not an exact
continuous-temperature error, a verified final settlement failure or a probability.
