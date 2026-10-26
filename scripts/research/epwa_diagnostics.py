"""Read-only reconstruction of checkpoint availability and EPWA station inventory.

This never invokes prediction creation, migrations, settlement or ingestion. The
original scheduler discarded ValueError details; reconstructed blockers are not
claimed to be the original exception. In-memory reference-gate state is unknown.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from premetar.pws.analysis import latest_station_reading, station_at
from premetar.pws.availability import selection_at
from premetar.pws.integrity import first_target_receive
from premetar.pws.models import QCConfig, Station
from premetar.pws.repository import parameter_available, readings, rows, selected
from premetar.pws.timestamps import assess_time, parse_utc, policy

STATIONS = (
    "61c1f4ff80a739001cda08bb",
    "5c6e9151154515001982e4da",
    "6941429cfdfe0700083492f4",
    "5d6145ec953683001a6b7fdb",
)
START = "2026-10-25T20:37:21.968739+00:00"
END = "2026-10-25T20:47:22+00:00"


def readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


def visible_parameters(
    conn: sqlite3.Connection, table: str, station_id: str, airport: str, at: datetime
) -> list[dict[str, Any]]:
    if table not in {"pws_quality_results", "pws_calibrations"}:
        raise ValueError("Unsupported parameter table")
    found = rows(
        conn,
        f"SELECT * FROM {table} WHERE station_id=? AND airport_icao=? AND created_at<=? ORDER BY created_at DESC,id DESC",
        (station_id, airport, at.isoformat()),
    )
    return [
        {**item, "parameters": json.loads(item["data_json"])}
        for item in found
        if json.loads(item["data_json"]).get("timestamp_policy_version") == policy().version
        and parameter_available(conn, json.loads(item["data_json"]), at)
        and (table != "pws_calibrations" or datetime.fromisoformat(item["trained_through"]) < at)
    ]


def station_evidence(
    conn: sqlite3.Connection, airport: str, station_id: str, at: datetime
) -> dict[str, Any]:
    snapshot = station_at(conn, station_id, airport, at)
    if not snapshot:
        return {"station_id": station_id, "discovery_missing_asof": True}
    station = Station.model_validate_json(snapshot["data_json"])
    cohort = selection_at(conn, airport, station.provider, at)
    allowed = (
        set(json.loads(cohort["data_json"])["selected_sensor_ids"])
        if cohort and station.provider == "opensensemap"
        else None
    )
    config = QCConfig()
    candidate = latest_station_reading(conn, station, at, config, airport)
    quality = visible_parameters(conn, "pws_quality_results", station_id, airport, at)
    calibration = visible_parameters(conn, "pws_calibrations", station_id, airport, at)
    q = quality[0]["parameters"] if quality else {}
    instruments = []
    data = readings(conn, station_id, at)
    for sensor in station.sensors:
        key = station_id + ":" + sensor.provider_sensor_id
        records = [r for r in data if r["provider_sensor_id"] == sensor.provider_sensor_id]
        latest = max(records, key=lambda r: (r["observation_time"] or "", r["id"]), default=None)
        instruments.append(
            {
                "sensor_id": key,
                "selected_sensor_asof": allowed is None or key in allowed,
                "latest_received_observation_id": latest["id"] if latest else None,
                "measurement_time": latest.get("observation_time") if latest else None,
                "first_receive_time": latest.get("first_receive_time") if latest else None,
                "assessment_asof": assess_time(latest, at).json_data() if latest else None,
            }
        )
    return {
        "station_id": station_id,
        "selected_station_asof": selected(conn, station_id, airport, at),
        "selection_version_id": cohort["id"] if cohort else None,
        "eligible_observation_id": candidate["id"] if candidate else None,
        "visible_quality_id": quality[0]["id"] if quality else None,
        "visible_quality_score": q.get("score"),
        "quality_flags": q.get("flags", []),
        "quality_status": q.get("status"),
        "predictive_sample_count": q.get("predictive", {}).get("sample_count"),
        "predictive_evaluation_days": q.get("predictive", {}).get("evaluation_days"),
        "quality_components": q.get("components"),
        "visible_calibration_id": calibration[0]["id"] if calibration else None,
        "instruments": instruments,
    }


def classify_evidence(
    model: str, first_received: datetime | None, at: datetime, stations: list[dict[str, Any]]
) -> str:
    if first_received is not None and first_received <= at:
        return "TARGET_ALREADY_RECEIVED_IN_STORED_EVIDENCE"
    eligible = [
        s
        for s in stations
        if s.get("selected_station_asof")
        and s.get("eligible_observation_id")
        and "STUCK_SENSOR" not in s.get("quality_flags", [])
    ]
    if not eligible:
        return "NO_ELIGIBLE_SELECTED_PWS_ASOF_RECONSTRUCTION"
    if model == "quality_weighted" and not any(
        s.get("visible_quality_score") is not None and s["visible_quality_score"] > 0
        for s in eligible
    ):
        return "NO_POSITIVE_VISIBLE_QUALITY_SCORE_ASOF_RECONSTRUCTION"
    return "NOT_EXPLAINED_BY_DURABLE_INPUTS_REFERENCE_GATE_OR_ORIGINAL_EXCEPTION_UNKNOWN"


def checkpoints(conn: sqlite3.Connection) -> dict[str, Any]:
    all_rows = rows(
        conn,
        "SELECT * FROM continuous_checkpoints WHERE julianday(attempted_at)>=julianday(?) AND julianday(attempted_at)<julianday(?) ORDER BY attempted_at",
        (START, END),
    )
    result = []
    cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for checkpoint in all_rows:
        if checkpoint["status"] != "UNAVAILABLE":
            continue
        at = datetime.fromisoformat(checkpoint["attempted_at"])
        airport = checkpoint["airport"]
        key = (airport, checkpoint["attempted_at"])
        if key not in cache:
            ids = [
                r[0]
                for r in conn.execute(
                    "SELECT station_id FROM pws_airport_stations WHERE airport_icao=?", (airport,)
                )
                if selected(conn, r[0], airport, at)
            ]
            cache[key] = [station_evidence(conn, airport, identity, at) for identity in ids]
        first = first_target_receive(conn, airport, datetime.fromisoformat(checkpoint["target"]))
        result.append(
            {
                **checkpoint,
                "target_first_receive": first.isoformat() if first else None,
                "reconstructed_blocker": classify_evidence(
                    checkpoint["model"], first, at, cache[key]
                ),
                "selected_stations": cache[key],
            }
        )
    return {
        "window_start": START,
        "window_end_exclusive": END,
        "stored_status_counts": dict(Counter(c["status"] for c in all_rows)),
        "reconstructed_blocker_counts": dict(Counter(c["reconstructed_blocker"] for c in result)),
        "unavailable_by_airport": dict(Counter(c["airport"] for c in result)),
        "unavailable_by_method": dict(Counter(c["model"] for c in result)),
        "unavailable_by_checkpoint_seconds": dict(Counter(c["checkpoint"] for c in result)),
        "unavailable": result,
    }


def inventory(conn: sqlite3.Connection, at: datetime) -> list[dict[str, Any]]:
    result = []
    for identity in STATIONS:
        station_id = "opensensemap:" + identity
        found = rows(conn, "SELECT * FROM pws_stations WHERE station_id=?", (station_id,))
        if not found:
            result.append({"station_id": station_id, "not_found": True})
            continue
        station = json.loads(found[0]["data_json"])
        data = readings(conn, station_id, at)
        status_counts = Counter(assess_time(r).status for r in data)
        reasons = Counter(reason for r in data for reason in assess_time(r).reasons)
        selections = rows(
            conn,
            "SELECT * FROM pws_selections WHERE station_id=? AND created_at<=? ORDER BY created_at,id",
            (station_id, at.isoformat()),
        )
        current = station_evidence(conn, "EPWA", station_id, at)
        latest_checks = rows(
            conn,
            "SELECT * FROM pws_sensor_checks WHERE station_id=? ORDER BY id DESC LIMIT 1",
            (station_id,),
        )
        quality_history = []
        for entry in rows(
            conn,
            "SELECT * FROM pws_quality_results WHERE station_id=? AND airport_icao='EPWA' AND created_at<=? ORDER BY created_at,id",
            (station_id, at.isoformat()),
        ):
            q = json.loads(entry["data_json"])
            quality_history.append(
                {
                    "id": entry["id"],
                    "created_at": entry["created_at"],
                    "algorithm_version": entry["algorithm_version"],
                    "score": q.get("score"),
                    "status": q.get("status"),
                    "flags": q.get("flags", []),
                    "timestamp_policy_version": q.get("timestamp_policy_version"),
                    "batch_visible_at_snapshot": parameter_available(conn, q, at),
                }
            )
        result.append(
            {
                "station_id": station_id,
                "station_name": station["station_name"],
                "latitude": station["latitude"],
                "longitude": station["longitude"],
                "exposure": station["exposure"],
                "sensors": station["sensors"],
                "distance_km": conn.execute(
                    "SELECT distance_km FROM pws_airport_stations WHERE station_id=? AND airport_icao='EPWA'",
                    (station_id,),
                ).fetchone()[0],
                "total_stored_records": len(data),
                "non_null_temperature_measurement_records": sum(
                    r.get("temperature_c") is not None and r.get("observation_time") is not None
                    for r in data
                ),
                "status_at_first_receipt_counts": dict(status_counts),
                "secondary_rejection_flags_counts": dict(reasons),
                "selection_history": selections,
                "quality_history": quality_history,
                "current_asof": current,
                "latest_poll": latest_checks[0] if latest_checks else None,
            }
        )
    return result


def render(data: dict[str, Any]) -> str:
    cp = data["checkpoints"]
    lines = [
        "# EPWA station and unavailable-checkpoint diagnostics",
        "",
        f"Read-only fixed snapshot: `{data['snapshot']}`. As of {data['snapshot_asof']}.",
        "",
        "## Historical checkpoint window",
        "",
        f"UTC window [{START}, {END}). Stored status counts: {cp['stored_status_counts']}.",
        "",
        "These are method/checkpoint rows, not ten independent meteorological cycles. No EPWA checkpoint falls in this window.",
        "The scheduler stored only NO_ELIGIBLE_INPUT_OR_TARGET_KNOWN and discarded the ValueError. The table reconstructs durable blockers at attempted_at (completion), not an observed original exception. Exact method-start times and transient in-memory ReferenceGate state were not stored.",
        "",
        "|Airport|Target UTC|Checkpoint s|Method|Attempt UTC|Reconstructed blocker|",
        "|---|---|---:|---|---|---|",
    ]
    for c in cp["unavailable"]:
        lines.append(
            f"|{c['airport']}|{c['target']}|{c['checkpoint']}|{c['model']}|{c['attempted_at']}|{c['reconstructed_blocker']}|"
        )
    lines.extend(
        [
            "",
            "Blocker counts: " + json.dumps(cp["reconstructed_blocker_counts"]),
            "",
            "Six rows (EDDM T-600/T-300/T-180, EGLL T-600/T-300, EHAM T-600) had eligible observations but no positive visible quality score. Four EGLL T-180 rows had no eligible selected reading: OSM measurement clocks 20:39:50.205, 20:41:44.350 and 20:40:27.276 UTC were already more than 300 seconds old. Selected Sensor.Community records lacked accepted measurement provenance. Quality-weighted also independently lacked scores at that time.",
            "",
            "Stored target first receipts were later than all ten attempts: EDDM20:53:49.796613, EGLL20:54:50.590570, EHAM20:52:32.270148 UTC. EHAM was received before nominal20:55, but after the T-600 attempt. Early-target receipt therefore does not explain these ten rows. None of the ten is a failed previous_metar, temperature_persistence or simple_recent_metar_trend baseline; those branches generated successfully at these checkpoint slots.",
            "",
            "Null score is not an unreliable-sensor classification. Existing score() requires complete component values, at least100 evaluation samples and7 evaluation days. An unfinished research history can therefore leave quality_weighted unavailable while other PWS methods remain available. No rule was relaxed.",
            "",
            "## Requested EPWA stations",
            "",
            "|Station|Name|Distance km|Stored rows|Valid at receipt|Selected now|",
            "|---|---|---:|---:|---:|---|",
        ]
    )
    for s in data["stations"]:
        if s.get("not_found"):
            lines.append(f"|{s['station_id']}|NOT FOUND|||||")
        else:
            lines.append(
                f"|{s['station_id']}|{s['station_name']}|{s['distance_km']:.3f}|{s['total_stored_records']}|{s['status_at_first_receipt_counts'].get('VALID', 0)}|{s['current_asof'].get('selected_station_asof')}|"
            )
    lines.extend(
        [
            "",
            "|Station|Sensor|Type|Current measurement UTC|Current assessment|Last known QC|",
            "|---|---|---|---|---|---|",
        ]
    )
    for s in data["stations"]:
        if s.get("not_found"):
            continue
        current = s["current_asof"]
        for instrument in current.get("instruments", []):
            sensor = next(
                x
                for x in s["sensors"]
                if instrument["sensor_id"].endswith(":" + x["provider_sensor_id"])
            )
            assessment = instrument["assessment_asof"]
            lines.append(
                f"|{s['station_name']}|{sensor['provider_sensor_id']}|{sensor['sensor_type']}|{instrument['measurement_time']}|{assessment['status'] if assessment else 'NO_RECORD'}|{current.get('quality_status')} / score {current.get('visible_quality_score')}|"
            )
    lines.extend(
        [
            "",
            "First-receipt VALID counts are historical ingestion eligibility, not current freshness. Old empty normalized rows remain counted as stored rows and separately fail timestamp/temperature checks. Full sensor types, selection reasons/history, per-station rejection flags, visible quality/calibration IDs and latest polling evidence are in the JSON companion.",
            "",
            "No production database writes, policy changes, prediction replay, collector restart or forecast creation was performed.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/research/m17/snapshot.sqlite3"))
    parser.add_argument("--asof", default="2026-10-26T12:26:35.238222+00:00")
    parser.add_argument(
        "--output", type=Path, default=Path("reports/research/epwa_checkpoint_diagnostics")
    )
    args = parser.parse_args()
    at = parse_utc(args.asof)
    if at is None:
        parser.error("Timezone-aware asof required")
    conn = readonly(args.database)
    try:
        data: dict[str, Any] = {
            "snapshot": str(args.database),
            "snapshot_asof": at.isoformat(),
            "checkpoints": checkpoints(conn),
            "stations": inventory(conn, at),
        }
    finally:
        conn.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    args.output.with_suffix(".md").write_text(render(data), encoding="utf-8")
    print(
        json.dumps(
            {
                "checkpoints": data["checkpoints"]["stored_status_counts"],
                "blockers": data["checkpoints"]["reconstructed_blocker_counts"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
