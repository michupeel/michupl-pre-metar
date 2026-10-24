# Milestone 1.6.1 — verified hotfix and actual EPWA evidence

Daily snapshot: 2026-10-24T17:33:26.944301+00:00. Integrity snapshot: 2026-10-24T17:33:27.747261+00:00.
Live operational evidence: 2026-10-24T17:34:05.580500+00:00. These are partial-day snapshots; collection continues.

## Deployment and preservation

- Branch: fix/strict-observation-timestamps; main was not merged.
- Old collector ended2026-10-24T17:26:47.853799Z; new run started2026-10-24T17:26:55.579161Z.
- Run: 20261024T172654624697Z-01316762; collector PID39904; original task MichuplPreMetar-Continuous-v1 remains Running.
- The two pythonw processes form the venv launcher→base-Python child chain, not two collectors. The one worker PID owns the existing database lock.
- Existing task ownership/configuration was verified before restarting; no task was reinstalled, removed or weakened.
- SQLite-supported online backups were made before deployment; an additional exact stopped-state backup is data\backups\stopped-strict-20261024T172649Z.sqlite3 (ignored local data).
- Rehearsal and live migration preserved row hashes for pws_observations, pws_arrivals, pws_predictions and continuous_settlements. Migration assessed3917 rows and appended exclusions for625 forecasts.
- Live integrity_check=ok; foreign_key_check=[]; frozen core source hashes match. Free disk at check: 76466929664bytes.
- No raw payload or original forecast/settlement was erased or rewritten. No backdating, new database, paid API or clock-setting change occurred.

## Timestamp audit

Valid means eligible at first receipt; eligible now additionally requires age<=300s at the audit snapshot. Stale counts refer to age at receipt. Totals include quarantined normalized records and empty/malformed temperatures; these are not all valid temperature samples.

|Provider|Total|Valid at receipt|Stale at receipt|Invalid/unknown|Eligible now|
|---|---:|---:|---:|---:|---:|
|sensor_community|2744|0|0|2744|0|
|opensensemap|1265|325|3|937|5|

Sensor.Community: all server-ingestion clocks are excluded from prediction, calibration, analytical QC samples and accuracy. openSenseMap uses API-documented createdAt measurement semantics; hardware-origin clock attestation remains unavailable. Two openSenseMap normalized records were future-dated at their first receipt. All evidence remains preserved. No collector-time substitution for missing Sensor.Community measurement time was found; the old effective-time server proxy is now removed. No genuinely future measurement tolerance is enabled.

The initial consistent backup at16:53:18Z had1138 EPWA normalized rows (404 openSenseMap,734 Sensor.Community). Applying the new policy to that frozen snapshot yielded114 valid readings from two instruments on one provider station;1024 rows were unusable. The final partial-day report has132 valid readings as collection continued. This change is elapsed coverage, not a controlled performance gain. Global exclusions rose from562/1105 in the earlier snapshot to625/1249 after more collection; original records remain intact.

## Windows clock

- Verification: FAILED against the explicit one-second research budget.
- Automatic synchronization/configured clock source/last successful sync: UNKNOWN; W32Time stopped, DemandStart with registered start triggers.
- Independent comparison sources: time.windows.com, time.cloudflare.com.
- Reported approximate offset: +1.0606910s; checked2026-10-24T17:28:30.073063+00:00.
- Windows timezone Central European Standard Time; Warsaw is CEST/UTC+02 on this date.
- Stopped W32Time does not itself prove an incorrect clock. Network stripcharts are approximate; no millisecond accuracy is claimed. No settings or service state were changed. Reviewing the existing synchronization/resync is the smallest recommended next action if the user authorizes correction.

## EPWA real measurements

Eight selected provider stations expose15 temperature sensors. Only one provider station (openSenseMap5dbdbe79a68df4001a7aca4c,13.902km from EPWA) supplies usable measurement-time records today: two instruments, not two independent weather stations. Physical independence across platforms remains unverified.

- Valid measurements: 132; range2026-10-24T14:12:00.995000+02:00–2026-10-24T19:30:12.867000+02:00.
- Temperature range: 8.55–12.78C. No morning PWS coverage is fabricated.
- Both instruments have66 readings, median measurement interval298.03s and median age at receipt105.63s. This age is not network propagation latency.
- Latest measurement19:30:12.867 CEST, received19:32:29.058456: BME2808.59C, HECA9.46C; age136.191s.
- Eleven aligned METAR cycles per instrument: BME280 interval-distance MAE0.105C, HECA0.917C. The integers represent rounding intervals, not exact continuous readings.
- BME280 is the more promising candidate for further validation by exploratory agreement. Both are operationally tied in cadence/freshness; ID breaks ranking ties. HECA shows an apparent positive offset in this short record. These differences could reflect exposure, instrumentation or microclimate. No unrealistic-spike suspicion was triggered in the valid day series; solar heating remains unverified. Neither instrument is TRUSTED.

## Genuine prospective cycle

EPWA target19:30 CEST /17:30Z: immutable forecasts were created at19:27,19:28 and19:29. Nearest, median and inverse-distance all predicted9C at each checkpoint. First actual AWC receipt was19:33:12.034412 CEST; original TAC:

`METAR EPWA 241730Z 17004KT CAVOK 09/06 Q1017 NOSIG`

All nine PWS forecasts settled automatically at9C and were created before both nominal observation and our first receipt. They represent **one meteorological cycle**, not nine independent successes. Approximate receipt leads were371.5s,311.8s and251.9s by checkpoint. Previous-METAR persistence also predicted9C, so no incremental improvement was observed. Lead is relative to our collector and uncertain local clock, not worldwide publication or market advantage. EXP-B remains disabled; exploratory reconstructions are labelled separately and never stored as live forecasts.

Daily actual METAR cycles: 14. Daily forecasts: 325 total, 169 eligible, 156 excluded, 169 valid matched, 0 pending. Valid PWS forecasts: nine on one target; other eligible forecasts are baselines. Across all airports: 1249 total, 624 eligible, 625 excluded, 0 pending, 44 distinct airport/target cycles. The four early-KNMI prototype exclusions remain preserved.

## Real post-hotfix smoke/short soak

Observed for about7minutes after restart, including repeated station polls and one complete EPWA target settlement. No multi-day reliability claim is made. New run generated18 forecasts and appended30 settlement records (including target forecasts created before restart). Ten new openSenseMap measurements were eligible at receipt;54 new Sensor.Community records were correctly quarantined. Post-restart captured errors: [].

|Source|Genuine raw responses|First receipt UTC|Latest receipt UTC|
|---|---:|---|---|
|awc|7|2026-10-24T17:26:57.230128+00:00|2026-10-24T17:33:12.034412+00:00|
|dwd_10min|8|2026-10-24T17:26:57.059809+00:00|2026-10-24T17:34:03.940671+00:00|
|knmi_metar|8|2026-10-24T17:26:56.938060+00:00|2026-10-24T17:34:03.783240+00:00|
|pws_opensensemap|32|2026-10-24T17:26:57.790032+00:00|2026-10-24T17:32:33.143567+00:00|
|pws_sensor_community|46|2026-10-24T17:26:58.040430+00:00|2026-10-24T17:32:26.379406+00:00|

All original collection jobs remain active. openSenseMap is HEALTHY; Sensor.Community is analytically STALE/unusable despite successful raw HTTP capture. EHAM has zero valid measurements in its daily smoke report. New requests/duplicate arrivals do not increase unique sample counts. The scheduler and automatic settlement were observed, not inferred merely from code.

## Verification and Qwen

- Baseline:142 tests passed before edits.
- Final `uv run pytest -q`:170 passed in12.94s.
- `uv sync --locked`:37 packages resolved/audited successfully.
- `uv run ruff check .`: all checks passed.
- `uv run ruff format --check .`:68 files already formatted.
- `uv run mypy`: success,37 source files; uses repository strict configuration.
- Actual read-only EPWA/EHAM daily CLI, status CLI, clock CLI, SQLite migration rehearsal and post-restart live API smoke passed.
- Genuine Windows smoke exposed console encoding failures in native clock/status diagnostics. Fixed and regression-tested; evidence remains in UTF-8 files, status uses portable escaped JSON. These CLI-only changes did not alter the running collector's frozen core.
- Local model unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF: three substantive tasks, one partially adapted, two rejected;25.339s and5849 server-reported tokens. Unsafe/incorrect Qwen suggestions were not applied. No savings claim or runtime LLM dependency.

## Artifacts and limitations

Full requested day exports: reports/daily/EPWA_2026-10-24.md, observations.csv, stations.csv and metar.csv; additional bucket/comparison/prediction/exploratory exports are local. The report is reusable for every configured airport/current local date. No automatic report task was added. Optional chart skipped because no plotting dependency is installed.

Provider quota/data-license verification limitations from PWS_DATA_SOURCES.md remain. Netatmo remains disabled without verified authentication. Hardware clocks/exposure, independent-station coverage and long-duration reliability are unverified. Clock offset exceeds our research budget. All experiments remain OPEN; one correct cycle does not establish predictive skill or information advantage.
