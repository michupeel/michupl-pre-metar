"""Read-only audits over immutable normalized observations and exclusion evidence."""

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from premetar.model import utc_now
from premetar.pws.integrity import prediction_issues
from premetar.pws.repository import rows
from premetar.pws.timestamps import assess_time, policy


def observation_rows(conn: sqlite3.Connection, airport: str | None = None) -> list[dict[str, Any]]:
    clause = (
        " JOIN pws_airport_stations a USING(station_id) WHERE a.airport_icao=?" if airport else ""
    )
    raw = rows(
        conn,
        """SELECT o.*,s.station_id,s.provider_sensor_id,st.provider,st.data_json station_json
        FROM pws_observations o JOIN pws_sensors s USING(sensor_id)
        JOIN pws_stations st USING(station_id)"""
        + clause,
        (airport,) if airport else (),
    )
    result = []
    for r in raw:
        data = json.loads(r["data_json"])
        metadata = json.loads(r["station_json"])
        result.append(
            {
                **r,
                **data,
                "provider": r["provider"],
                "station_id": r["station_id"],
                "exposure": metadata.get("exposure"),
                "mobile": metadata.get("mobile"),
            }
        )
    return result


def prediction_summary(conn: sqlite3.Connection, airport: str | None = None) -> dict[str, Any]:
    predictions = rows(
        conn,
        "SELECT * FROM pws_predictions" + (" WHERE airport_icao=?" if airport else ""),
        (airport,) if airport else (),
    )
    valid = excluded = matched = pending = 0
    cycles = set()
    excluded_reasons: Counter[str] = Counter()
    for item in predictions:
        data = json.loads(item["data_json"])
        issues = prediction_issues(conn, data)
        outcomes = rows(
            conn,
            "SELECT * FROM continuous_settlements WHERE prediction_id=? ORDER BY id",
            (item["id"],),
        )
        if not outcomes:
            pending += 1
        if issues:
            excluded += 1
            excluded_reasons.update(reason for reason, _ in issues)
        else:
            valid += 1
            if outcomes:
                matched += 1
        cycles.add((item["airport_icao"], item["target_time"]))
    return dict(
        total=len(predictions),
        valid=valid,
        excluded=excluded,
        pending_settlements=pending,
        valid_matched_outcomes=matched,
        distinct_target_cycles=len(cycles),
        exclusion_reasons=dict(excluded_reasons),
    )


def timestamp_audit(
    conn: sqlite3.Connection, output: Path, at: datetime | None = None
) -> dict[str, Any]:
    at = at or utc_now()
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    reasons: dict[str, Counter[str]] = defaultdict(Counter)
    for row in observation_rows(conn):
        c = counts[row["provider"]]
        intrinsic = assess_time(row)
        current = assess_time(row, at)
        c["total"] += 1
        c["valid_at_receipt"] += intrinsic.eligible
        c["valid_measurement_timestamps"] += bool(
            intrinsic.measurement_time
            and intrinsic.semantics_reference
            and intrinsic.timestamp_provenance == "SENSOR_MEASUREMENT_TIME"
            and "FUTURE_MEASUREMENT_AT_RECEIPT" not in intrinsic.reasons
        )
        c["stale_at_receipt"] += intrinsic.status == "STALE"
        c["invalid_or_unknown"] += intrinsic.status not in {"VALID", "STALE"}
        c["invalid_timestamps"] += intrinsic.status == "INVALID_TIMESTAMP"
        c["unknown_timestamp_provenance"] += intrinsic.status == "UNKNOWN_TIMESTAMP_PROVENANCE"
        c["quarantined"] += not intrinsic.eligible
        c["prediction_eligible_now"] += current.eligible
        c["currently_stale"] += current.status == "STALE"
        reasons[row["provider"]].update(intrinsic.reasons)
    result = dict(
        as_of=at.isoformat(),
        policy_version=policy().version,
        maximum_age_seconds=policy().maximum_age_seconds,
        providers={p: dict(c) for p, c in counts.items()},
        rejections={p: dict(c) for p, c in reasons.items()},
        predictions=prediction_summary(conn),
    )
    output.mkdir(parents=True, exist_ok=True)
    (output / "timestamp_audit.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    table = [
        "| Provider | Total | Valid at receipt | Valid measurement timestamps | Stale at receipt | Invalid/unknown | Quarantined | Eligible now |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for p, c in counts.items():
        table.append(
            f"|{p}|{c['total']}|{c['valid_at_receipt']}|{c['valid_measurement_timestamps']}|{c['stale_at_receipt']}|{c['invalid_or_unknown']}|{c['quarantined']}|{c['prediction_eligible_now']}|"
        )
    (output / "timestamp_audit.md").write_text(
        "# Strict timestamp audit\n\nAs of "
        + at.isoformat()
        + "\n\n"
        + "\n".join(table)
        + "\n\nValid at receipt describes historical captured observations, not freshness now. Stale means age exceeded the 300-second policy at first receipt; current age is checked separately. Unknown/server-ingest clocks never become measurement clocks. Raw and normalized evidence are retained; exclusions append without modifying predictions/settlements.\n\n"
        + json.dumps(result, indent=2)
        + "\n\nThe old code used provider ingestion/publication as an effective-time fallback; it did not fill missing Sensor.Community observation_time with collector time. Sensor.Community has no verified measurement-time field in the audited API and is quarantined for analytical use. openSenseMap createdAt is the documented measurement timestamp; semantics are API-verified, not independent device-clock certification.\n",
        encoding="utf-8",
    )
    return result
