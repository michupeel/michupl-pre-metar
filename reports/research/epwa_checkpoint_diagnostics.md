# EPWA station and unavailable-checkpoint diagnostics

Read-only fixed snapshot: `data\research\m17\snapshot.sqlite3`. As of 2026-10-26T12:26:35.238222+00:00.

## Historical checkpoint window

UTC window [2026-10-25T20:37:21.968739+00:00, 2026-10-25T20:47:22+00:00). Stored status counts: {'GENERATED': 39, 'UNAVAILABLE': 10}.

These are method/checkpoint rows, not ten independent meteorological cycles. No EPWA checkpoint falls in this window.
The scheduler stored only NO_ELIGIBLE_INPUT_OR_TARGET_KNOWN and discarded the ValueError. The table reconstructs durable blockers at attempted_at (completion), not an observed original exception. Exact method-start times and transient in-memory ReferenceGate state were not stored.

|Airport|Target UTC|Checkpoint s|Method|Attempt UTC|Reconstructed blocker|
|---|---|---:|---|---|---|
|EDDM|2026-10-25T20:50:00+00:00|600|quality_weighted|2026-10-25T20:40:00.829485+00:00|NO_POSITIVE_VISIBLE_QUALITY_SCORE_ASOF_RECONSTRUCTION|
|EGLL|2026-10-25T20:50:00+00:00|600|quality_weighted|2026-10-25T20:40:01.202148+00:00|NO_POSITIVE_VISIBLE_QUALITY_SCORE_ASOF_RECONSTRUCTION|
|EDDM|2026-10-25T20:50:00+00:00|300|quality_weighted|2026-10-25T20:45:00.977232+00:00|NO_POSITIVE_VISIBLE_QUALITY_SCORE_ASOF_RECONSTRUCTION|
|EHAM|2026-10-25T20:55:00+00:00|600|quality_weighted|2026-10-25T20:45:01.360802+00:00|NO_POSITIVE_VISIBLE_QUALITY_SCORE_ASOF_RECONSTRUCTION|
|EGLL|2026-10-25T20:50:00+00:00|300|quality_weighted|2026-10-25T20:45:01.732119+00:00|NO_POSITIVE_VISIBLE_QUALITY_SCORE_ASOF_RECONSTRUCTION|
|EDDM|2026-10-25T20:50:00+00:00|180|quality_weighted|2026-10-25T20:47:01.179600+00:00|NO_POSITIVE_VISIBLE_QUALITY_SCORE_ASOF_RECONSTRUCTION|
|EGLL|2026-10-25T20:50:00+00:00|180|nearest|2026-10-25T20:47:01.269254+00:00|NO_ELIGIBLE_SELECTED_PWS_ASOF_RECONSTRUCTION|
|EGLL|2026-10-25T20:50:00+00:00|180|median|2026-10-25T20:47:01.350892+00:00|NO_ELIGIBLE_SELECTED_PWS_ASOF_RECONSTRUCTION|
|EGLL|2026-10-25T20:50:00+00:00|180|inverse_distance|2026-10-25T20:47:01.432010+00:00|NO_ELIGIBLE_SELECTED_PWS_ASOF_RECONSTRUCTION|
|EGLL|2026-10-25T20:50:00+00:00|180|quality_weighted|2026-10-25T20:47:01.509133+00:00|NO_ELIGIBLE_SELECTED_PWS_ASOF_RECONSTRUCTION|

Blocker counts: {"NO_POSITIVE_VISIBLE_QUALITY_SCORE_ASOF_RECONSTRUCTION": 6, "NO_ELIGIBLE_SELECTED_PWS_ASOF_RECONSTRUCTION": 4}

Six rows (EDDM T-600/T-300/T-180, EGLL T-600/T-300, EHAM T-600) had eligible observations but no positive visible quality score. Four EGLL T-180 rows had no eligible selected reading: OSM measurement clocks 20:39:50.205, 20:41:44.350 and 20:40:27.276 UTC were already more than 300 seconds old. Selected Sensor.Community records lacked accepted measurement provenance. Quality-weighted also independently lacked scores at that time.

Stored target first receipts were later than all ten attempts: EDDM20:53:49.796613, EGLL20:54:50.590570, EHAM20:52:32.270148 UTC. EHAM was received before nominal20:55, but after the T-600 attempt. Early-target receipt therefore does not explain these ten rows. None of the ten is a failed previous_metar, temperature_persistence or simple_recent_metar_trend baseline; those branches generated successfully at these checkpoint slots.

Null score is not an unreliable-sensor classification. Existing score() requires complete component values, at least100 evaluation samples and7 evaluation days. An unfinished research history can therefore leave quality_weighted unavailable while other PWS methods remain available. No rule was relaxed.

## Requested EPWA stations

|Station|Name|Distance km|Stored rows|Valid at receipt|Selected now|
|---|---|---:|---:|---:|---|
|opensensemap:61c1f4ff80a739001cda08bb|Cybernetyki 7|2.665|253|252|True|
|opensensemap:5c6e9151154515001982e4da|Czerniakowska|7.853|247|246|True|
|opensensemap:6941429cfdfe0700083492f4|SaveDnipro|9.762|253|253|True|
|opensensemap:5d6145ec953683001a6b7fdb|Przekorna|10.445|280|280|True|

|Station|Sensor|Type|Current measurement UTC|Current assessment|Last known QC|
|---|---|---|---|---|---|
|Cybernetyki 7|61c1f4ff80a739001cda08bd|BMP180|2026-10-26T12:21:01.814000Z|STALE|UNVERIFIED / score None|
|Czerniakowska|5c6e9151154515001982e4dc|DHT11|2026-10-26T12:23:10.196000Z|VALID|UNVERIFIED / score None|
|SaveDnipro|6941429cfdfe0700083492f7|BME280|2026-10-26T12:24:19.703000Z|VALID|UNVERIFIED / score None|
|Przekorna|5d6145ec953683001a6b7fde|BME280|2026-10-26T12:22:35.622000Z|VALID|UNVERIFIED / score None|

First-receipt VALID counts are historical ingestion eligibility, not current freshness. Old empty normalized rows remain counted as stored rows and separately fail timestamp/temperature checks. Full sensor types, selection reasons/history, per-station rejection flags, visible quality/calibration IDs and latest polling evidence are in the JSON companion.

No production database writes, policy changes, prediction replay, collector restart or forecast creation was performed.
