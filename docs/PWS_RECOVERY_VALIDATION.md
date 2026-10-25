# Milestone1.6.2 — actual operational validation

Snapshot UTC: **2026-10-25T12:42:26.355575+00:00**. Actual public API responses and local database evidence; no synthetic live measurements.

## Recovery and accounting

Root cause: empty latest results previously received observation identities based on raw packet ID. New ingestion retains the raw capture and appends a NO_MEASUREMENT sensor poll, without a temperature row. Timestamp validation was not weakened.

Before deployment:5464 OSM normalized rows,1428 timestamped numeric records,4036 empty records. The earlier4956/3661 diagnostic snapshot was older; the unattended collector continued until deployment. All old rows remain unchanged. Numeric records do not all satisfy strict prediction eligibility.

Since restart: **109** new timestamped numeric source records; **72** new fresh outdoor measurements accepted by availability checks. 74 records pass timestamp/physical checks alone, including two indoor records that availability rejects. **103 empty sensor polls produced0 normalized observations**. Stale/invalid timestamped numeric evidence remains quarantined. All200 empty responses remain non-errors.

Sensor poll outcomes: {"INVALID_MEASUREMENT": 8, "NO_MEASUREMENT": 103, "STALE_MEASUREMENT": 33, "SUCCESS_NEW_MEASUREMENT": 72}. 216 sensor attempts share 213 OSM HTTP responses, including4 metadata discovery responses. One response can carry several instruments. Source event identity, first receipt and subsequent raw arrivals stay separate.

## Four-airport preflight

| Airport | Discovered boxes | Temperature sensors | Numeric result | ACTIVE at latest own check | Empty | Stale | Invalid | Eligible now | Selected stations/sensors |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| EDDM | 35 | 31 | 15 | 9 | 16 | 6 | 0 | 4 | 4/4 |
| EGLL | 9 | 9 | 3 | 3 | 6 | 0 | 0 | 3 | 3/3 |
| EHAM | 53 | 39 | 13 | 3 | 26 | 9 | 1 | 3 | 3/3 |
| EPWA | 124 | 107 | 51 | 27 | 55 | 18 | 7 | 4 | 4/4 |

These are sensor/provider records. ACTIVE at a prior check is not a claim that an unpolled sensor remains fresh now. Eligible-now revalidates the300s clock limit and recovery mode. Selection retains membership through bounded failure hysteresis, while each prediction independently requires fresh inputs. All four scans completed without hitting the200-box cap. There were no invalid measurement timestamps in the completed latest-check cohort; other invalid results include impossible temperatures around−145C, two indoor instruments and one unknown-unit result. Missing clocks on empty polls are not counted as invalid timestamped measurements.

EPWA:104 boxes with temperature sensors exposed107 instruments among124 discovered boxes.27 passed an actual latest check, across distinct provider records rather than guaranteed independent physical installations. At this snapshot only4 still met current freshness/recovery conditions; all4 were selected from4 different provider stations. Other active-at-check candidates are revisited conservatively. The entire old four-station EPWA cohort was replaced. This improves operational availability, not demonstrated predictive skill.

## Exact selected instruments

| Airport | Provider station ID | Sensor ID | Distance km | Measurement UTC | Temperature C | Age at receipt s |
|---|---|---|---:|---|---:|---:|
| EDDM | 5c755e5d7dea1400190366e8 | 5c755e5d7dea1400190366ea | 9.530 | 2026-10-25T12:37:49.754000Z | 13.1 | 94.793 |
| EDDM | 5beb063756a15500193139f0 | 5beb063756a15500193139f7 | 16.398 | 2026-10-25T12:38:45.894000Z | 12.32 | 36.638 |
| EDDM | 5bce161fbb15b700196e256d | 5bce161fbb15b700196e256f | 19.279 | 2026-10-25T12:38:46.082000Z | 10.7 | 34.544 |
| EDDM | 65c13f99e9153000077c4d83 | 65c13f99e9153000077c4d86 | 19.428 | 2026-10-25T12:39:18.989000Z | 12.24 | 7.580 |
| EGLL | 623f6e24c4de74001c66f4cb | 623f6e24c4de74001c66f4ce | 11.920 | 2026-10-25T12:37:39.316000Z | 14.09 | 255.116 |
| EGLL | 626030a418aca4001ca27240 | 626030a418aca4001ca27243 | 19.692 | 2026-10-25T12:40:24.306000Z | 13.85 | 86.205 |
| EGLL | 5e61c1cc6cc61f001c6e4086 | 5e61c1cc6cc61f001c6e4089 | 19.958 | 2026-10-25T12:40:19.224000Z | 16.13 | 81.214 |
| EHAM | 640b68626b84850007762702 | 640b68626b84850007762705 | 8.838 | 2026-10-25T12:38:38.717000Z | 13.02 | 53.979 |
| EHAM | 5fa3fc2867d8a1001b5f9d6d | 5fa3fc2867d8a1001b5f9d70 | 11.996 | 2026-10-25T12:38:32.940000Z | 13.25 | 55.633 |
| EHAM | 6137877084c610001cae82e1 | 6137877084c610001cae82e5 | 17.597 | 2026-10-25T12:38:10.133000Z | 19.06 | 80.528 |
| EPWA | 61c1f4ff80a739001cda08bb | 61c1f4ff80a739001cda08bd | 2.665 | 2026-10-25T12:37:34.155000Z | 14.1 | 158.809 |
| EPWA | 5c6e9151154515001982e4da | 5c6e9151154515001982e4dc | 7.853 | 2026-10-25T12:38:34.240000Z | 16.6 | 160.954 |
| EPWA | 6941429cfdfe0700083492f4 | 6941429cfdfe0700083492f7 | 9.762 | 2026-10-25T12:40:39.912000Z | 14.78 | 0.776 |
| EPWA | 5d6145ec953683001a6b7fdb | 5d6145ec953683001a6b7fde | 10.445 | 2026-10-25T12:41:07.245000Z | 16.33 | 11.175 |

Cohort change:14 of16 old station records deselected;12 new stations added and2 retained, leaving14 selected provider stations/instruments. Deselection does not label every old sensor broken: emptiness, staleness and operational ranking differ. Full selection versions1–4 retain exact check IDs/rationale. Future changes append versions. Minimum200m station separation is a conservative voting guard, not proof of physical independence.

## Live operation and scientific safeguards

Old run stopped2026-10-25T12:25:41.513111Z; new run `20261025T122608622365Z-3dec2c3c` started12:26:09.588745Z. Approximate16-minute bounded validation at this snapshot. Existing task ownership/configuration verified; no reinstall, parallel collector or clock modification. Single worker PID51776. Database integrity=ok; foreign-key violations=0. SQL EXCEPT checks against the stopped-state backup found0 changed/deleted historical observations, arrivals, raw records, selections, forecasts or settlements. All loaded algorithm-source hashes match the reviewed working source.

Scheduler generated18 actual forecasts since restart;18 settlements appended (including earlier forecasts). Live12:40Z T−10 PWS forecasts for EDDM/EGLL record new selection versions1/4. All new forecasts pass the existing first-receipt/input-eligibility audit; no backdated forecast was created. New cohort forecasts remain pending at this snapshot; no improved accuracy or information edge is claimed.

Repeated old stale numeric readings reused3 existing source observation IDs and preserved their original24Oct first receipts. Tests also cover identical fresh readings in different HTTP packets and changed raw numeric formatting. No SUCCESS_UNCHANGED_MEASUREMENT occurred during this short live window; that outcome is verified by deterministic tests, not claimed as observed live.

All4 selected EPWA stations and all3 selected EGLL stations received regular MONITOR polls after preflight. EDDM and EHAM also completed repeated monitoring rounds. Their HTTP capture/measurement clocks remain distinct. API response counts include successful collection that adds no new report identity.

Observed limitations: the pre-existing hourly QC/calibration routine occupied the single database worker for about164s (12:31:35–12:34:19Z), delaying queued writes, scheduler ticks and preflight. It completed and collection resumed. This scaling issue is documented for focused follow-up rather than hidden. Existing receipt barriers remain active and missed checkpoints are not backdated. One AWC ReadTimeout occurred12:41:42Z; independent KNMI/DWD/OSM continued and AWC retained its bounded retry policy.

OSM request spacing target2s, measured minimum1.976104s from same-run monotonic starts; Windows timer granularity permits slight early wakes. No numeric provider quota is asserted as verified. There were no OSM429/auth/provider errors. Origin of uploaded OSM clocks is not independently attested; Sensor.Community remains excluded by strict timestamp policy. Prior workstation clock-offset uncertainty remains unchanged.

## Verification

`uv sync --locked`:37 packages resolved/audited. `uv run pytest -q`:199 passed in20.23s. Ruff check passed; format check76 files unchanged; strict mypy41 source files passed. Existing METAR tests remain included. New regressions cover null/missing measurements, raw preservation, dedup/first receipt, stale/future/provenance, actual-sensor selection, station diversity, replacement, recovery hysteresis, restart deadlines, schema repeatability, versioned as-of selection including sub-millisecond boundary, provider429/timeouts/auth/malformed JSON and read-only reporting.

Raw response shapes follow the audited stored OSM box/sensors/lastMeasurement schema. Test values/clocks are explicitly synthetic; live results above use actual captured responses. Immutable forecast/settlement tests from earlier milestones remain green.

Qwen:2 bounded proposals; recovery-counter structure partially adapted after correction; test proposal rejected. Actual model unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF;16.249s substantive inference,2630 server-reported tokens. No automatic patch applied, no repair loop or claimed token savings. Weather runtime does not use Qwen.

Reports: `reports/integrity/recovery-1.6.2/live_validation.json`, `availability/availability.md`, `availability/availability_sensors.csv`, `continuous/`, and `reports/daily/EPWA_2026-10-25.md`. All data counts are time-stamped snapshots and will change as collection continues.

Final follow-up12:45Z: the same task/run remained active with a fresh heartbeat; every selected cohort had completed MONITOR polling. AWC recovered automatically with200 responses at12:43:44.051065Z and12:44:44.657349Z. Automatic forecasts continued, reaching36 generated checkpoint records. The7 missed method/checkpoint records correspond to the startup catch-up policy; no prediction was backdated. Frozen tables above retain their12:42:26Z counts.
