"""Daily local-data inspection. All output is read-only and explicitly prospective/exploratory."""

import csv
import json
import math
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any
from zoneinfo import ZoneInfo

from premetar.model import icao_round_temperature, utc_now
from premetar.pws.analysis import interval_residual
from premetar.pws.daily_time import bucket_start, local_day_bounds
from premetar.pws.geometry import haversine_km
from premetar.pws.integrity import prediction_issues
from premetar.pws.repository import rows, selected
from premetar.pws.timestamps import assess_time, parse_utc, policy
from premetar.sources import STATIONS


def export(path: Path, data: list[dict[str, Any]], defaults: list[str]) -> None:
    fields = list(dict.fromkeys(defaults + [k for r in data for k in r]))
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(data)


def local(value: datetime | str | None, zone: ZoneInfo) -> str | None:
    clock = parse_utc(value)
    return clock.astimezone(zone).isoformat() if clock else None


def load_day(
    conn: sqlite3.Connection, airport: str, start: datetime, end: datetime
) -> list[dict[str, Any]]:
    raw = rows(
        conn,
        """SELECT o.*,s.station_id,s.provider_sensor_id,st.provider,
        st.data_json station_json,s.data_json sensor_json,a.distance_km
        FROM pws_observations o JOIN pws_sensors s USING(sensor_id)
        JOIN pws_stations st USING(station_id) JOIN pws_airport_stations a USING(station_id)
        WHERE a.airport_icao=? AND ((julianday(o.observation_time)>=julianday(?) AND julianday(o.observation_time)<julianday(?))
        OR (julianday(o.first_receive_time)>=julianday(?) AND julianday(o.first_receive_time)<julianday(?)))""",
        (airport, start.isoformat(), end.isoformat(), start.isoformat(), end.isoformat()),
    )
    result = []
    for r in raw:
        metadata = json.loads(r["station_json"])
        result.append(
            {
                **r,
                **json.loads(r["data_json"]),
                "provider": r["provider"],
                "station_id": r["station_id"],
                "exposure": metadata.get("exposure"),
                "mobile": metadata.get("mobile"),
            }
        )
    # Duplicate timestamps with conflicting values are not averaged into invented observations.
    conflicts: dict[tuple[str, datetime], set[float]] = defaultdict(set)
    for row in result:
        check = assess_time(row)
        if check.measurement_time and row["temperature_c"] is not None:
            conflicts[(row["sensor_id"], check.measurement_time)].add(row["temperature_c"])
    for row in result:
        clock = assess_time(row).measurement_time
        if clock and len(conflicts[(row["sensor_id"], clock)]) > 1:
            row["quality_flags"] = sorted(
                set(row.get("quality_flags", [])) | {"CONFLICTING_DUPLICATE"}
            )
    return result


def metars(
    conn: sqlite3.Connection, airport: str, start: datetime, end: datetime, zone: ZoneInfo
) -> list[dict[str, Any]]:
    raw = rows(
        conn,
        """SELECT o.*,rr.collector_receive_time received FROM observations o
        JOIN report_receipts rr ON rr.observation_id=o.id WHERE o.station_icao=?
        AND o.product_type IN ('METAR','SPECI') AND julianday(o.event_time)>=julianday(?)
        AND julianday(o.event_time)<julianday(?)""",
        (airport, start.isoformat(), end.isoformat()),
    )
    byidentity: dict[str, dict[str, Any]] = {}
    for r in raw:
        event = parse_utc(r["event_time"])
        received = parse_utc(r["received"])
        if event is None or received is None or not start <= event < end:
            continue
        old = byidentity.get(r["identity"])
        old_received = parse_utc(old["first_received_utc"]) if old else None
        if old is not None and old_received is not None and old_received <= received:
            old["providers"] = sorted(set(old["providers"]) | {r["source"]})
            continue
        data = json.loads(r["data_json"])
        byidentity[r["identity"]] = dict(
            report_identity=r["identity"],
            observation_time_utc=event.isoformat(),
            observation_time_local=local(event, zone),
            first_received_utc=received.isoformat(),
            first_received_local=local(received, zone),
            temperature_c=r["temperature_c"],
            report_type=r["product_type"],
            correction=bool(data.get("cor")),
            auto=bool(data.get("auto")),
            providers=sorted({r["source"]} | set(old["providers"] if old else [])),
            raw_text=r["raw_text"],
        )
    return sorted(
        byidentity.values(),
        key=lambda r: (r["observation_time_utc"], r["first_received_utc"], r["report_identity"]),
    )


def make_report(
    conn: sqlite3.Connection,
    airport: str,
    day: date | None,
    output: Path,
    bucket_minutes: int = 5,
    now: datetime | None = None,
) -> dict[str, Any]:
    airport = airport.upper()
    if airport not in STATIONS:
        raise ValueError("Unknown airport")
    at = now or utc_now()
    zone = ZoneInfo(STATIONS[airport].timezone)
    day = day or at.astimezone(zone).date()
    start, end = local_day_bounds(day, STATIONS[airport].timezone)
    bucket_start(start, bucket_minutes, STATIONS[airport].timezone)
    data = load_day(conn, airport, start, end)
    valid = []
    rejected = []
    unique: set[tuple[str, datetime, float]] = set()
    for r in data:
        check = assess_time(r)
        clock = check.measurement_time
        if check.eligible and clock and start <= clock < end:
            key = (r["sensor_id"], clock, float(r["temperature_c"]))
            if key in unique:
                continue
            unique.add(key)
            valid.append(
                {
                    **r,
                    "_measurement": clock,
                    "_received": check.collector_receive_time,
                    "_age": check.age_at_receipt_seconds,
                }
            )
        else:
            rejected.append(
                dict(
                    observation_id=r["id"],
                    station=r["station_id"],
                    provider=r["provider"],
                    status=check.status,
                    reasons=json.dumps(check.reasons),
                    measurement_time_utc=clock.isoformat() if clock else None,
                    received_time_utc=r["first_receive_time"],
                )
            )
    valid.sort(key=lambda r: (r["_measurement"], r["sensor_id"], r["_received"]))
    inventory = []
    metadata = rows(
        conn,
        """SELECT s.*,st.provider,st.data_json station_json,a.distance_km
       FROM pws_sensors s JOIN pws_stations st USING(station_id) JOIN pws_airport_stations a USING(station_id)
       WHERE a.airport_icao=? ORDER BY a.distance_km,s.sensor_id""",
        (airport,),
    )
    metrics = []
    for sensor in metadata:
        if not selected(conn, sensor["station_id"], airport, at):
            continue
        history = [r for r in valid if r["sensor_id"] == sensor["sensor_id"]]
        latest = rows(
            conn,
            "SELECT * FROM pws_observations WHERE sensor_id=? ORDER BY first_receive_time DESC LIMIT 1",
            (sensor["sensor_id"],),
        )
        row = (
            {
                **latest[0],
                **json.loads(latest[0]["data_json"]),
                "station_id": sensor["station_id"],
                "provider": sensor["provider"],
                "provider_sensor_id": sensor["provider_sensor_id"],
            }
            if latest
            else None
        )
        status = assess_time(row, at) if row else None
        all_history = rows(
            conn,
            "SELECT * FROM pws_observations WHERE sensor_id=? ORDER BY observation_time DESC",
            (sensor["sensor_id"],),
        )
        last_valid = None
        for previous in all_history:
            previous_row = {
                **previous,
                **json.loads(previous["data_json"]),
                "provider": sensor["provider"],
                "station_id": sensor["station_id"],
            }
            check_previous = assess_time(previous_row)
            if check_previous.eligible:
                last_valid = check_previous.measurement_time
                break
        sensor_meta = json.loads(sensor["data_json"])
        clock_times = sorted({r["_measurement"] for r in history})
        gaps = [(b - a).total_seconds() for a, b in zip(clock_times, clock_times[1:], strict=False)]
        ages = [r["_age"] for r in history]
        temperatures = [r["temperature_c"] for r in history]
        flags = []
        if any(
            abs(b["temperature_c"] - a["temperature_c"])
            / max((b["_measurement"] - a["_measurement"]).total_seconds() / 60, 0.001)
            > 2
            for a, b in zip(history, history[1:], strict=False)
            if a["_measurement"] < b["_measurement"]
        ):
            flags.append("TEMPERATURE_SPIKE_SUSPECT")
        item = dict(
            station=sensor["station_id"],
            sensor_id=sensor["sensor_id"],
            provider=sensor["provider"],
            distance_km=sensor["distance_km"],
            sensor_type=sensor_meta.get("sensor_type") or sensor_meta.get("sensor_model"),
            last_valid_measurement_local=local(last_valid, zone),
            last_received_local=local(row["first_receive_time"], zone) if row else None,
            observation_age_at_last_receipt=status.age_at_receipt_seconds if status else None,
            qc_status=status.status if status else "UNKNOWN_TIMESTAMP_PROVENANCE",
            eligible_now=status.eligible if status else False,
            timestamp_provenance=status.timestamp_provenance if status else "UNKNOWN_TIME",
            valid_day_observations=len(history),
            median_update_interval_seconds=median(gaps) if gaps else None,
            p90_update_interval_seconds=sorted(gaps)[math.ceil(0.9 * len(gaps)) - 1]
            if gaps
            else None,
            longest_gap_seconds=max(gaps) if gaps else None,
            median_age_at_receipt_seconds=median(ages) if ages else None,
            min_temperature_c=min(temperatures) if temperatures else None,
            max_temperature_c=max(temperatures) if temperatures else None,
            flags=json.dumps(flags),
            solar_bias="INSUFFICIENT_MULTI_DAY_EXPOSURE_EVIDENCE",
            quality_class="UNVERIFIED",
        )
        inventory.append(item)
        if history:
            metrics.append(item)
    references = metars(conn, airport, start, end, zone)
    initial: dict[str, dict[str, Any]] = {}
    for r in references:
        reference_event = parse_utc(r["observation_time_utc"])
        if (
            r["report_type"] == "METAR"
            and not r["correction"]
            and r["temperature_c"] is not None
            and reference_event is not None
            and reference_event.minute in STATIONS[airport].routine_minutes
        ):
            initial.setdefault(r["observation_time_utc"], r)
    pairs = []
    cycle_rows = []
    for target, reference in initial.items():
        target_time = parse_utc(target)
        first = parse_utc(reference["first_received_utc"])
        if not target_time or not first:
            continue
        for sensor_id in sorted({r["sensor_id"] for r in valid}):
            aligned = [
                r
                for r in valid
                if r["sensor_id"] == sensor_id
                and abs((r["_measurement"] - target_time).total_seconds()) <= 300
            ]
            if aligned:
                row = min(
                    aligned,
                    key=lambda r: (
                        abs((r["_measurement"] - target_time).total_seconds()),
                        r["_measurement"],
                        r["id"],
                    ),
                )
                residual = interval_residual(row["temperature_c"], int(reference["temperature_c"]))
                pairs.append(
                    dict(
                        station=row["station_id"],
                        sensor_id=sensor_id,
                        metar_time_local=local(target_time, zone),
                        measurement_time_local=local(row["_measurement"], zone),
                        pws_temperature_c=row["temperature_c"],
                        metar_integer=int(reference["temperature_c"]),
                        interval_residual_c=residual,
                        exact_integer_match=icao_round_temperature(row["temperature_c"])
                        == int(reference["temperature_c"]),
                        available_before_reference=row["_received"] < first,
                        analysis="EXPLORATORY_METEOROLOGICAL_ALIGNMENT_NOT_A_LIVE_FORECAST",
                    )
                )
        for phase, cutoff in (
            ("PRE_OBSERVATION", min(target_time, first) - timedelta(microseconds=1)),
            ("POST_OBSERVATION_PRE_RECEIPT", first - timedelta(microseconds=1)),
        ):
            if phase.startswith("POST") and first <= target_time:
                continue
            candidates = [r for r in valid if assess_time(r, cutoff).eligible]
            latest_by_station: dict[str, dict[str, Any]] = {}
            for row in candidates:
                old = latest_by_station.get(row["station_id"])
                if old is None or (row["_measurement"], row["sensor_id"]) > (
                    old["_measurement"],
                    old["sensor_id"],
                ):
                    latest_by_station[row["station_id"]] = row
            values = list(latest_by_station.values())
            exploratory = median(r["temperature_c"] for r in values) if values else None
            cycle_rows.append(
                dict(
                    metar_time_local=local(target_time, zone),
                    first_received_local=local(first, zone),
                    phase=phase,
                    pws_observation_ids=json.dumps([r["id"] for r in values]),
                    exploratory_pws_integer=icao_round_temperature(exploratory)
                    if exploratory is not None
                    else None,
                    actual_metar_integer=reference["temperature_c"],
                    analysis="EXPLORATORY_RECONSTRUCTION_NOT_PERSISTED_AS_FORECAST",
                )
            )
    predictions = []
    for item in rows(
        conn,
        "SELECT * FROM pws_predictions WHERE airport_icao=? AND julianday(target_time)>=julianday(?) AND julianday(target_time)<julianday(?)",
        (airport, start.isoformat(), end.isoformat()),
    ):
        f = json.loads(item["data_json"])
        issues = prediction_issues(conn, f)
        settlements = rows(
            conn,
            "SELECT * FROM continuous_settlements WHERE prediction_id=? ORDER BY id",
            (item["id"],),
        )
        first_reference = next(
            (r for r in references if r["observation_time_utc"] == item["target_time"]), None
        )
        prediction_created = parse_utc(item["created_at"])
        reference_received = (
            parse_utc(first_reference["first_received_utc"]) if first_reference else None
        )
        predictions.append(
            dict(
                prediction_id=item["id"],
                target_time_local=local(item["target_time"], zone),
                created_at_local=local(item["created_at"], zone),
                model=f["method"],
                predicted_integer=f["integer_temperature"],
                eligible=not issues,
                exclusions=json.dumps(issues),
                matched=bool(settlements),
                actual_integer=settlements[0]["official_integer"] if settlements else None,
                created_before_first_receipt=(prediction_created < reference_received)
                if prediction_created is not None and reference_received is not None
                else None,
                pws_based=bool(f.get("contributions")),
            )
        )
    buckets = defaultdict(list)
    for row in valid:
        begin = bucket_start(row["_measurement"], bucket_minutes, STATIONS[airport].timezone)
        # No carry-forward: measurement belongs here AND must be available by this bucket's end.
        if row["_received"] < begin + timedelta(minutes=bucket_minutes):
            buckets[begin].append(row)
    bucket_rows = []
    for begin, items in sorted(buckets.items()):
        latest_sensors = {}
        for row in sorted(items, key=lambda r: (r["_measurement"], r["sensor_id"])):
            latest_sensors[row["sensor_id"]] = row
        station_sensors: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in latest_sensors.values():
            station_sensors[row["station_id"]].append(row)
        bystation = {
            key: {**members[0], "temperature_c": median(r["temperature_c"] for r in members)}
            for key, members in station_sensors.items()
        }
        grouped: list[tuple[float, float, dict[str, Any]]] = []
        for row in sorted(bystation.values(), key=lambda r: (r["distance_km"], r["station_id"])):
            loc = json.loads(row["station_json"])
            if not any(
                haversine_km(loc["latitude"], loc["longitude"], p[0], p[1]) < 0.2 for p in grouped
            ):
                grouped.append((loc["latitude"], loc["longitude"], row))
        bucket_values = [r[2]["temperature_c"] for r in grouped]
        center = median(bucket_values)
        bucket_rows.append(
            dict(
                start_local=local(begin, zone),
                provider_stations=len(bystation),
                sensor_records=len(latest_sensors),
                conservative_spatial_groups=len(grouped),
                verified_independent_physical_stations=None,
                median_c=center,
                min_c=min(r["temperature_c"] for r in latest_sensors.values()),
                max_c=max(r["temperature_c"] for r in latest_sensors.values()),
                median_absolute_deviation_c=median(
                    abs(r["temperature_c"] - center) for r in latest_sensors.values()
                ),
                independence="UNVERIFIED; ONE_VOTE_PER_STATION_AND_200M_CLUSTER",
            )
        )
    for item in inventory:
        aligned = [p for p in pairs if p["sensor_id"] == item["sensor_id"]]
        item["aligned_metar_cycles"] = len(aligned)
        item["interval_aware_MAE"] = (
            mean(abs(p["interval_residual_c"]) for p in aligned) if aligned else None
        )
        item["median_interval_residual"] = (
            median(p["interval_residual_c"] for p in aligned) if aligned else None
        )
    ranked = sorted(
        metrics,
        key=lambda r: (
            r["median_age_at_receipt_seconds"],
            -r["valid_day_observations"],
            r["sensor_id"],
        ),
    )
    for index, r in enumerate(ranked, 1):
        r["operational_rank"] = index
    result = dict(
        airport=airport,
        date=day.isoformat(),
        timezone=str(zone),
        as_of=at.isoformat(),
        utc_start=start.isoformat(),
        utc_end=end.isoformat(),
        maximum_age_seconds=policy().maximum_age_seconds,
        usable_stations=len({r["station_id"] for r in valid}),
        usable_sensors=len({r["sensor_id"] for r in valid}),
        total_valid_observations=len(valid),
        excluded_provider_records=len(rejected),
        measurement_start_local=local(valid[0]["_measurement"], zone) if valid else None,
        measurement_end_local=local(valid[-1]["_measurement"], zone) if valid else None,
        temperature_min_c=min((r["temperature_c"] for r in valid), default=None),
        temperature_max_c=max((r["temperature_c"] for r in valid), default=None),
        distinct_metar_cycles=len(initial),
        total_predictions=len(predictions),
        valid_predictions=sum(p["eligible"] for p in predictions),
        valid_pws_predictions=sum(p["eligible"] and p["pws_based"] for p in predictions),
        matched_outcomes=sum(p["eligible"] and p["matched"] for p in predictions),
        excluded_predictions=sum(not p["eligible"] for p in predictions),
        pending_settlements=sum(not p["matched"] for p in predictions),
        stations=inventory,
        buckets=bucket_rows,
        comparisons=pairs,
        metar=references,
        predictions=predictions,
        exploratory_cycles=cycle_rows,
        ranking=[{k: v for k, v in r.items()} for r in ranked],
        observations=[
            dict(
                measurement_time_local=local(r["_measurement"], zone),
                measurement_time_utc=r["_measurement"].isoformat(),
                received_time_local=local(r["_received"], zone),
                received_time_utc=r["_received"].isoformat(),
                station=r["station_id"],
                sensor_id=r["sensor_id"],
                provider=r["provider"],
                temperature_c=r["temperature_c"],
                observation_age_seconds=r["_age"],
                qc="VALID",
                observation_id=r["id"],
                timestamp_provenance="SENSOR_MEASUREMENT_TIME",
            )
            for r in valid
        ],
    )
    output.mkdir(parents=True, exist_ok=True)
    prefix = f"{airport}_{day.isoformat()}"
    for suffix, entries, fields in (
        (
            "observations",
            result["observations"],
            [
                "measurement_time_local",
                "received_time_local",
                "station",
                "provider",
                "temperature_c",
                "observation_age_seconds",
                "qc",
            ],
        ),
        ("stations", inventory, ["station", "sensor_id", "provider", "distance_km", "qc_status"]),
        (
            "metar",
            references,
            [
                "observation_time_local",
                "first_received_local",
                "temperature_c",
                "report_type",
                "correction",
            ],
        ),
        (
            "buckets",
            bucket_rows,
            [
                "start_local",
                "provider_stations",
                "verified_independent_physical_stations",
                "median_c",
            ],
        ),
        (
            "comparison",
            pairs,
            [
                "station",
                "sensor_id",
                "metar_time_local",
                "pws_temperature_c",
                "metar_integer",
                "interval_residual_c",
            ],
        ),
        (
            "predictions",
            predictions,
            [
                "prediction_id",
                "target_time_local",
                "model",
                "predicted_integer",
                "eligible",
                "actual_integer",
            ],
        ),
        ("rejected", rejected, ["observation_id", "station", "provider", "status", "reasons"]),
        (
            "exploratory_cycles",
            cycle_rows,
            [
                "metar_time_local",
                "first_received_local",
                "phase",
                "exploratory_pws_integer",
                "actual_metar_integer",
                "analysis",
            ],
        ),
    ):
        export(output / f"{prefix}_{suffix}.csv", entries, fields)
    (output / f"{prefix}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    header = f"# {airport} daily real observations: {day} ({zone})\n\n"
    summary = {k: v for k, v in result.items() if not isinstance(v, list)}

    def markdown(entries: list[dict[str, Any]], columns: list[str]) -> str:
        if not entries:
            return "INSUFFICIENT DATA"
        lines = ["|" + "|".join(columns) + "|", "|" + "|".join(["---"] * len(columns)) + "|"]
        for entry in entries:
            cells = []
            for column in columns:
                value = entry.get(column)
                text = (
                    f"{value:.3f}"
                    if isinstance(value, float)
                    else str(value if value is not None else "UNKNOWN")
                )
                cells.append(text.replace("|", "/"))
            lines.append("|" + "|".join(cells) + "|")
        return "\n".join(lines)

    report_text = (
        header + "## Observed summary\n\n```json\n" + json.dumps(summary, indent=2) + "\n```\n"
    )
    sections = [
        (
            "Actual chronological readings (last 20; full day in CSV)",
            result["observations"][-20:],
            [
                "measurement_time_local",
                "received_time_local",
                "sensor_id",
                "temperature_c",
                "observation_age_seconds",
            ],
        ),
        (
            "Selected sensor inventory",
            inventory,
            [
                "sensor_id",
                "provider",
                "distance_km",
                "sensor_type",
                "last_valid_measurement_local",
                "last_received_local",
                "qc_status",
                "eligible_now",
            ],
        ),
        (
            "Operational ranking: UNVERIFIED, not predictive TRUSTED status",
            result["ranking"],
            [
                "operational_rank",
                "sensor_id",
                "valid_day_observations",
                "median_update_interval_seconds",
                "median_age_at_receipt_seconds",
                "aligned_metar_cycles",
                "interval_aware_MAE",
                "median_interval_residual",
                "flags",
            ],
        ),
        (
            "Measurement buckets (last 20; full day in CSV)",
            bucket_rows[-20:],
            [
                "start_local",
                "provider_stations",
                "conservative_spatial_groups",
                "median_c",
                "min_c",
                "max_c",
                "median_absolute_deviation_c",
            ],
        ),
        (
            "Actual METAR",
            references,
            [
                "observation_time_local",
                "first_received_local",
                "temperature_c",
                "report_type",
                "correction",
            ],
        ),
        (
            "Meteorological agreement (last 20; exploratory, not live predictions)",
            pairs[-20:],
            [
                "sensor_id",
                "metar_time_local",
                "pws_temperature_c",
                "metar_integer",
                "interval_residual_c",
                "exact_integer_match",
                "available_before_reference",
            ],
        ),
        (
            "Availability reconstruction (last 20; exploratory, never persisted as live forecasts)",
            cycle_rows[-20:],
            [
                "metar_time_local",
                "first_received_local",
                "phase",
                "exploratory_pws_integer",
                "actual_metar_integer",
            ],
        ),
        (
            "Genuine immutable predictions (last 20; full outcomes/exclusions in CSV)",
            predictions[-20:],
            [
                "prediction_id",
                "target_time_local",
                "created_at_local",
                "model",
                "predicted_integer",
                "actual_integer",
                "eligible",
                "created_before_first_receipt",
            ],
        ),
    ]
    for title, entries, columns in sections:
        report_text += "\n## " + title + "\n\n" + markdown(entries, columns) + "\n"
    report_text += "\n## Interpretation and limits\n\nTimestamp provenance is verified against the API contract, not independent hardware clock certification. Sensor.Community ingestion clocks are quarantined. Historical observations were fresh at receipt; this does not imply current freshness. A single day cannot establish persistent bias, solar heating or predictive value. Ranked candidates reflect operational availability/freshness; all remain UNVERIFIED. Signed interval residuals measure distance outside the METAR rounding interval, not precise continuous thermometer bias. Each sensor contributes at most once per METAR cycle; cycles, not checkpoints, are meteorological events. Spatial clusters are conservative voting groups, not proven physical independence. No forward-fill/interpolation is used; measurements received beyond their bucket end are not counted there. Exploratory pre/post-observation reconstructions were never persisted as live predictions and cannot establish an information edge. No improved prospective PWS skill is established by this report. Clock offset uncertainty limits latency interpretation. A chart is optional and was not generated: no plotting dependency is installed.\n"
    (output / f"{prefix}.md").write_text(report_text, encoding="utf-8")
    return result
