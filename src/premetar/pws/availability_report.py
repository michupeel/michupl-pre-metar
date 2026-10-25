"""Read-only availability snapshots; provider stations do not prove physical independence."""

import csv
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from premetar.model import utc_now
from premetar.pws.repository import rows
from premetar.pws.timestamps import assess_time, parse_utc, policy


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        is not None
    )


def availability_snapshot(
    conn: sqlite3.Connection,
    airports: set[str] | None = None,
    now: datetime | None = None,
    provider: str | None = "opensensemap",
) -> dict[str, Any]:
    at = now or utc_now()
    checks_ready = table_exists(conn, "pws_sensor_checks")
    versions_ready = table_exists(conn, "pws_selection_versions")
    checks: dict[tuple[str, str], dict[str, Any]] = {}
    if checks_ready:
        for stored_check in rows(
            conn,
            "SELECT * FROM pws_sensor_checks WHERE id IN (SELECT max(id) FROM pws_sensor_checks GROUP BY airport_icao,sensor_id) ORDER BY id",
        ):
            checks[(stored_check["airport_icao"], stored_check["sensor_id"])] = stored_check
    versions: dict[tuple[str, str], dict[str, Any]] = {}
    if versions_ready:
        for stored_version in rows(
            conn,
            "SELECT * FROM pws_selection_versions WHERE id IN (SELECT max(id) FROM pws_selection_versions GROUP BY airport_icao,provider) ORDER BY id",
        ):
            versions[(stored_version["airport_icao"], stored_version["provider"])] = stored_version
    stations = rows(
        conn,
        "SELECT a.*,st.provider,st.data_json station_json FROM pws_airport_stations a JOIN pws_stations st USING(station_id) ORDER BY a.airport_icao,a.distance_km,a.station_id",
    )
    stations = [s for s in stations if provider is None or s["provider"] == provider]
    output = []
    for station in stations:
        airport = station["airport_icao"]
        if airports is not None and airport not in airports:
            continue
        version = versions.get((airport, station["provider"]))
        selection = json.loads(version["data_json"]) if version else {}
        for sensor in rows(
            conn,
            "SELECT * FROM pws_sensors WHERE station_id=? ORDER BY sensor_id",
            (station["station_id"],),
        ):
            metadata = json.loads(sensor["data_json"])
            if metadata.get("phenomenon", "temperature") != "temperature":
                continue
            check = checks.get((airport, sensor["sensor_id"]))
            data = json.loads(check["data_json"]) if check else {}
            status = check["status"] if check else "UNVERIFIED"
            reasons = list(data.get("reasons", []))
            measurement = data.get("measurement_time") or data.get("observation_time")
            measurement_age = check_age = None
            try:
                event = parse_utc(measurement)
                checked = parse_utc(check["checked_at"]) if check else None
                measurement_age = (at - event).total_seconds() if event else None
                check_age = (at - checked).total_seconds() if checked else None
                if status == "ACTIVE":
                    if event is None or checked is None:
                        status = "UNVERIFIED"
                        reasons.append("MISSING_VERIFIABLE_CHECK_CLOCK")
                    elif measurement_age is not None and measurement_age < 0:
                        status = "INVALID"
                        reasons.append("FUTURE_MEASUREMENT_AT_DISPLAY")
                    elif max(measurement_age or 0, check_age or 0) > policy().maximum_age(
                        station["provider"]
                    ):
                        status = "STALE"
                        reasons.append("AVAILABILITY_CHECK_OR_MEASUREMENT_EXPIRED")
            except (ValueError, TypeError, OverflowError):
                status = "INVALID"
                reasons.append("INVALID_CHECK_TIMESTAMP")
            if status == "ACTIVE":
                if "evidence_class" not in data:
                    status = "UNVERIFIED"
                    reasons.append("MISSING_STRICT_ELIGIBILITY_EVIDENCE")
                else:
                    strict = assess_time(
                        {
                            **data,
                            "station_id": station["station_id"],
                            "provider": station["provider"],
                            "sensor_id": sensor["sensor_id"],
                            "observation_time": measurement,
                        },
                        at=at,
                    )
                    if not strict.eligible:
                        status = {
                            "STALE": "STALE",
                            "UNKNOWN_TIMESTAMP_PROVENANCE": "UNVERIFIED",
                        }.get(strict.status, "INVALID")
                        reasons.extend(strict.reasons)
            rationale = selection.get("rationale", {})
            selected = sensor["sensor_id"] in selection.get("selected_sensor_ids", [])
            output.append(
                dict(
                    airport=airport,
                    station_id=station["station_id"],
                    sensor_id=sensor["sensor_id"],
                    provider=station["provider"],
                    distance_km=station["distance_km"],
                    sensor_type=metadata.get("sensor_type"),
                    checked_at=check["checked_at"] if check else None,
                    measurement_time=measurement,
                    temperature_c=data.get("temperature_c"),
                    age_at_receipt_seconds=data.get("age_seconds"),
                    measurement_age_now_seconds=measurement_age,
                    check_age_seconds=check_age,
                    status=status,
                    stored_status=check["status"] if check else "UNVERIFIED",
                    monitoring_eligible=status == "ACTIVE" and data.get("mode") == "ACTIVE",
                    mode=data.get("mode", "UNVERIFIED"),
                    outcome=check["outcome"] if check else None,
                    selected=selected,
                    selection_version=version["id"] if version else None,
                    selection_rationale=rationale.get(
                        sensor["sensor_id"],
                        rationale.get(
                            station["station_id"],
                            version["reason"] if version and selected else "Not selected",
                        ),
                    ),
                    reasons=reasons,
                    context=data.get("context"),
                )
            )
    preflights: dict[str, dict[str, Any]] = {}
    if table_exists(conn, "pws_preflight_runs"):
        for preflight in rows(
            conn,
            "SELECT * FROM pws_preflight_runs WHERE id IN (SELECT max(id) FROM pws_preflight_runs GROUP BY airport_icao)",
        ):
            preflights[preflight["airport_icao"]] = {
                **preflight,
                "result": json.loads(preflight["data_json"]),
            }
    current_run = None
    if table_exists(conn, "runs"):
        latest_run = conn.execute(
            "SELECT id FROM runs ORDER BY started_at DESC,id DESC LIMIT 1"
        ).fetchone()
        current_run = latest_run[0] if latest_run else None
    check_columns = (
        {r[1] for r in conn.execute("PRAGMA table_info(pws_sensor_checks)")}
        if checks_ready
        else set()
    )
    if current_run is None and "run_id" in check_columns:
        latest_check_run = conn.execute(
            "SELECT run_id FROM pws_sensor_checks ORDER BY id DESC LIMIT 1"
        ).fetchone()
        current_run = latest_check_run[0] if latest_check_run else None
    run_outcomes = []
    if current_run and {"run_id", "station_id", "observation_id"}.issubset(check_columns):
        run_outcomes = rows(
            conn,
            "SELECT c.airport_icao,c.outcome,count(*) sensor_poll_attempts,count(DISTINCT c.raw_id) raw_responses,count(DISTINCT c.observation_id) unique_source_measurement_ids FROM pws_sensor_checks c JOIN pws_stations st USING(station_id) WHERE c.run_id=? AND (? IS NULL OR st.provider=?) GROUP BY c.airport_icao,c.outcome ORDER BY c.airport_icao,c.outcome",
            (current_run, provider, provider),
        )
    summaries = []
    airport_names = airports if airports is not None else {s["airport_icao"] for s in stations}
    for airport in sorted(airport_names):
        items = [r for r in output if r["airport"] == airport]
        counts = Counter(r["status"] for r in items)
        latest_preflight = preflights.get(airport) if provider in (None, "opensensemap") else None
        discovered = latest_preflight["result"] if latest_preflight else {}
        outcomes = [r for r in run_outcomes if r["airport_icao"] == airport]
        unique_ids = None
        raw_responses = None
        if current_run and {"run_id", "station_id", "observation_id"}.issubset(check_columns):
            run_counts = conn.execute(
                "SELECT count(DISTINCT c.observation_id),count(DISTINCT c.raw_id) FROM pws_sensor_checks c JOIN pws_stations st USING(station_id) WHERE c.run_id=? AND c.airport_icao=? AND (? IS NULL OR st.provider=?)",
                (current_run, airport, provider, provider),
            ).fetchone()
            unique_ids, raw_responses = run_counts
        summaries.append(
            dict(
                airport=airport,
                latest_preflight=latest_preflight,
                preflight_provider="opensensemap" if latest_preflight else None,
                fresh_discovered_stations=discovered.get("discovered_stations"),
                fresh_temperature_sensors=discovered.get("temperature_sensors"),
                fresh_checked_stations=discovered.get("checked_stations"),
                preflight_capped=discovered.get("preflight_capped"),
                preflight_completed_at=latest_preflight["completed_at"]
                if latest_preflight
                else None,
                retained_inventory_stations=len(
                    {s["station_id"] for s in stations if s["airport_icao"] == airport}
                ),
                retained_inventory_temperature_sensors=len(items),
                active_at_last_check=sum(r["stored_status"] == "ACTIVE" for r in items),
                current_run_id=current_run,
                current_run_sensor_poll_outcomes=outcomes,
                current_run_sensor_poll_attempts=sum(r["sensor_poll_attempts"] for r in outcomes)
                if current_run and "run_id" in check_columns
                else None,
                current_run_unique_source_measurement_ids=unique_ids,
                current_run_raw_responses=raw_responses,
                discovered_stations=len(
                    {s["station_id"] for s in stations if s["airport_icao"] == airport}
                ),
                temperature_sensors=len(items),
                returning_temperature=sum(r["temperature_c"] is not None for r in items),
                no_measurement=counts["NO_MEASUREMENT"],
                stale=counts["STALE"],
                invalid=counts["INVALID"],
                unverified=counts["UNVERIFIED"],
                active_temperature_sensors=counts["ACTIVE"],
                eligible_active=sum(r["monitoring_eligible"] for r in items),
                invalid_timestamps=sum(
                    any(
                        str(reason).startswith(
                            (
                                "INVALID_MEASUREMENT_TIMESTAMP",
                                "INVALID_RECEIVE_TIMESTAMP",
                                "INVALID_TIMESTAMP",
                                "FUTURE_",
                                "MISSING_MEASUREMENT_TIME",
                                "UNKNOWN_TIMEZONE",
                            )
                        )
                        for reason in r["reasons"]
                    )
                    for r in items
                ),
                active_provider_stations=len(
                    {r["station_id"] for r in items if r["status"] == "ACTIVE"}
                ),
                selected_sensors=sum(r["selected"] for r in items),
                selected_provider_stations=len({r["station_id"] for r in items if r["selected"]}),
            )
        )
    return dict(
        as_of=at.isoformat(),
        initialization="INITIALIZED" if checks_ready else "NOT_INITIALIZED",
        provider_scope=provider or "ALL_PROVIDERS",
        physical_independence="UNVERIFIED; counts represent provider stations",
        airports=summaries,
        sensors=output,
        current_run_id=current_run,
        current_run_sensor_poll_outcomes=run_outcomes,
        accounting_note="Fresh discovery counts come from latest completed preflight, not retained historical inventory. ACTIVE-at-last-check may now be stale. Poll outcomes count sensor attempts; one station HTTP response can cover several sensors. Unique source IDs refer to normalized measurements, not necessarily strict-eligible observations; per-outcome unique/raw response counts must not be summed. Current-run raw response totals count distinct captured responses, excluding transport failures without a response.",
    )


def write_availability(result: dict[str, Any], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "availability.json").write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8"
    )
    for name in ("sensors", "airports"):
        data = result[name]
        with (output / f"availability_{name}.csv").open(
            "w", newline="", encoding="utf-8"
        ) as handle:
            fields = list(data[0]) if data else ["status"]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(
                {k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in row.items()}
                for row in data
            )
    summary = "\n".join(
        f"| {r['airport']} | {r['discovered_stations']} | {r['temperature_sensors']} | {r['eligible_active']} | {r['no_measurement']} | {r['stale']} | {r['invalid']} | {r['unverified']} | {r['selected_sensors']} |"
        for r in result["airports"]
    )
    fresh_summary = "\n".join(
        f"| {r['airport']} | {r['fresh_discovered_stations']} | {r['fresh_temperature_sensors']} | {r['fresh_checked_stations']} | {r['preflight_completed_at']} | {r['active_at_last_check']} | {r['eligible_active']} | {r['current_run_sensor_poll_attempts']} | {r['current_run_unique_source_measurement_ids']} |"
        for r in result["airports"]
    )
    details = "\n".join(
        f"| {r['airport']} | {r['sensor_id']} | {r['distance_km']:.3f} | {r['status']} | {r['measurement_time']} | {r['selected']} | {str(r['selection_rationale']).replace('|', '/')} |"
        for r in result["sensors"]
    )
    (output / "availability.md").write_text(
        f"# Sensor availability\n\nOBSERVED as of {result['as_of']}; {result['initialization']}. Provider scope: {result['provider_scope']}.\n\nProvider stations are not verified independent physical stations. ACTIVE is expired dynamically after the strict freshness limit. Selection rationale is operational, not demonstrated predictive skill.\n\n| Airport | Stations | Sensors | Active | Empty | Stale | Invalid | Unverified | Selected |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|\n{summary}\n\nThe first table counts retained inventory. Fresh discovery and current-run evidence:\n\n| Airport | Fresh stations | Fresh sensors | Checked stations | Preflight completed UTC | Active at last check | Eligible now | Sensor polls this run | Unique source IDs this run |\n|---|---:|---:|---:|---|---:|---:|---:|---:|\n{fresh_summary}\n\n{result['accounting_note']}\n\n| Airport | Sensor | Distance km | Status | Measurement UTC | Selected | Rationale |\n|---|---|---:|---|---|---|---|\n{details}\n",
        encoding="utf-8",
    )
