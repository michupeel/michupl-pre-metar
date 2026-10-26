"""Read-only, as-of inputs for EXP-0010; no collector or schema mutations."""

import json
import math
import sqlite3
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from premetar.pws.daily import metars
from premetar.pws.geometry import haversine_km
from premetar.pws.models import QCConfig
from premetar.pws.quality import eligible
from premetar.pws.repository import rows
from premetar.pws.timestamps import assess_time, parse_utc
from premetar.sources import STATIONS

AIRPORTS = ("EDDM", "EHAM", "EPWA", "EGLL")
QC = QCConfig(stale_seconds=300)
EPS = timedelta(microseconds=1)


def clock(value: Any) -> datetime:
    result = parse_utc(value)
    if result is None:
        raise ValueError("Missing timestamp")
    return result


def metadata_at(sensor: dict[str, Any], at: datetime) -> dict[str, Any] | None:
    index = bisect_right(sensor["metadata_times"], at) - 1
    return sensor["metadata"][index] if index >= 0 else None


def selection_at(sensor: dict[str, Any], at: datetime) -> dict[str, Any] | None:
    index = bisect_right(sensor["selection_times"], at) - 1
    return sensor["selections"][index] if index >= 0 else None


def asof_eligible(sensor: dict[str, Any], row: dict[str, Any], at: datetime) -> bool:
    if row["_received"] > at or row["_event"] > at or at - row["_event"] > timedelta(seconds=300):
        return False
    if row.get("startup_censored") or row.get("coverage_gap"):
        return False
    conflict = sensor["conflicts"].get(row["_event"])
    if conflict is not None and conflict <= at:
        return False
    metadata = metadata_at(sensor, at)
    if metadata is None:
        return False
    airport = sensor["airport_metadata"]
    distance = haversine_km(
        metadata["latitude"], metadata["longitude"], airport["latitude"], airport["longitude"]
    )
    return distance <= 20 and eligible(
        {**row, "exposure": metadata.get("exposure"), "mobile": metadata.get("mobile")}, at, QC
    )


def latest(
    sensor: dict[str, Any],
    at: datetime,
    phase: str | None = None,
    nominal: datetime | None = None,
    around: datetime | None = None,
) -> dict[str, Any] | None:
    end = bisect_right(sensor["event_times"], at)
    for row in reversed(sensor["readings"][:end]):
        if at - row["_event"] > timedelta(seconds=300):
            break
        if phase == "EXP_B" and nominal is not None and row["_received"] < nominal:
            continue
        if around is not None and abs((row["_event"] - around).total_seconds()) > 300:
            continue
        if asof_eligible(sensor, row, at):
            return dict(row)
    return None


def reference_series(reports: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    groups: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    for row in reports:
        if row["report_type"] == "METAR":
            groups[clock(row["observation_time_utc"])].append(row)
    result = []
    excluded: Counter[str] = Counter()
    for event, group in sorted(groups.items()):
        initial_rows = [r for r in group if not r["correction"] and r["temperature_c"] is not None]
        if not initial_rows:
            excluded["NO_INITIAL_TEMPERATURE"] += 1
            continue
        initial = [
            r
            for r in initial_rows
            if isinstance(r["temperature_c"], (int, float))
            and not isinstance(r["temperature_c"], bool)
            and math.isfinite(r["temperature_c"])
            and float(r["temperature_c"]).is_integer()
        ]
        if len(initial) != len(initial_rows):
            excluded["INVALID_INITIAL_TEMPERATURE"] += 1
        if not initial:
            continue
        chosen = min(initial, key=lambda r: clock(r["first_received_utc"]))
        closure = min(clock(r["first_received_utc"]) for r in group)
        disagreements = [
            clock(r["first_received_utc"])
            for r in initial
            if r["temperature_c"] != chosen["temperature_c"]
        ]
        ambiguous_from = min(disagreements) if disagreements else None
        if ambiguous_from is not None:
            # Exclude this target from evaluation, but do not erase information
            # from earlier decisions made before the contradiction was received.
            excluded["AMBIGUOUS_INITIAL_TEMPERATURE"] += 1
        result.append(
            {
                **chosen,
                "_event": event,
                "_received": clock(chosen["first_received_utc"]),
                "_closure": closure,
                "_closure_censored": any(
                    r.get("startup_censored") or r.get("coverage_gap")
                    for r in group
                    if clock(r["first_received_utc"]) == closure
                ),
                "_ambiguous_from": ambiguous_from,
            }
        )
    return result, dict(excluded)


def previous_reference(
    references: list[dict[str, Any]], target: datetime, at: datetime
) -> dict[str, Any] | None:
    return max(
        (
            r
            for r in references
            if r["_event"] < target
            and r["_event"] <= at
            and r["_received"] <= at
            and (r.get("_ambiguous_from") is None or r["_ambiguous_from"] > at)
        ),
        key=lambda r: r["_event"],
        default=None,
    )


def calibration(
    sensor: dict[str, Any], method: str, target: datetime, at: datetime
) -> dict[str, Any] | None:
    if method == "CAL-0":
        return dict(
            offset_c=0.0,
            offset_lower_c=0.0,
            offset_upper_c=0.0,
            calibration_n=0,
            history_available_by=None,
            calibration_reference_ids=[],
        )
    if method not in ("CAL-1", "CAL-2"):
        raise ValueError("Unknown calibration method")
    pairs = [
        p
        for p in sensor["pairs"]
        if p["_event"] < target
        and p["_event"] <= at
        and p["_received"] < at
        and (p.get("_ambiguous_from") is None or p["_ambiguous_from"] > at)
        and (p.get("_pws_conflict_from") is None or p["_pws_conflict_from"] > at)
        and (method == "CAL-1" or p["_event"] >= at - timedelta(hours=12))
    ]
    if len(pairs) < 12:
        return None
    offset = median(p["offset_midpoint_c"] for p in pairs)
    return dict(
        offset_c=offset,
        offset_lower_c=offset - 0.5,
        offset_upper_c=offset + 0.5,
        calibration_n=len(pairs),
        history_available_by=max(p["_received"] for p in pairs).isoformat(),
        calibration_reference_ids=[p["report_identity"] for p in pairs],
        calibration_kind="QUANTIZED_REFERENCE_MIDPOINT_ESTIMATE",
    )


def load_dataset(conn: sqlite3.Connection, cutoff: datetime) -> dict[str, Any]:
    result: dict[str, Any] = {}
    arrivals: dict[str, dict[str, Any]] = {}
    for r in rows(
        conn,
        "SELECT a.observation_id,a.received_at,a.startup_censored,r.run_id FROM pws_arrivals a JOIN raw_payloads r ON r.id=a.raw_id ORDER BY a.received_at,a.raw_id",
    ):
        arrivals.setdefault(r["observation_id"], r)
    for airport in AIRPORTS:
        airport_metadata = json.loads(
            conn.execute("SELECT data_json FROM pws_airports WHERE icao=?", (airport,)).fetchone()[
                0
            ]
        )
        first = conn.execute(
            "SELECT min(event_time) FROM observations WHERE station_icao=?", (airport,)
        ).fetchone()[0]
        if first is None:
            result[airport] = dict(
                references=[], reports=[], sensors={}, reference_exclusions={"NO_REFERENCE": 1}
            )
            continue
        reports = metars(
            conn,
            airport,
            clock(first) - timedelta(days=1),
            cutoff + timedelta(days=1),
            ZoneInfo(STATIONS[airport].timezone),
        )
        for r in reports:
            source = rows(
                conn,
                "SELECT startup_censored,coverage_gap FROM observations o JOIN report_receipts rr ON rr.observation_id=o.id WHERE o.identity=? ORDER BY rr.collector_receive_time LIMIT 1",
                (r["report_identity"],),
            )
            r["startup_censored"] = bool(source[0]["startup_censored"]) if source else True
            r["coverage_gap"] = bool(source[0]["coverage_gap"]) if source else True
        references, reference_exclusions = reference_series(reports)
        receipt_groups: dict[tuple[datetime, str, str], dict[str, Any]] = {}
        for receipt in rows(
            conn,
            "SELECT o.event_time,o.source,o.identity,r.collector_receive_time received FROM observations o JOIN report_receipts r ON r.observation_id=o.id WHERE o.station_icao=? AND o.product_type='METAR'",
            (airport,),
        ):
            nominal, received = clock(receipt["event_time"]), clock(receipt["received"])
            key = (nominal, receipt["source"], receipt["identity"])
            if key not in receipt_groups or received < clock(receipt_groups[key]["first_received"]):
                receipt_groups[key] = dict(
                    airport=airport,
                    target_time=nominal.isoformat(),
                    provider=receipt["source"],
                    report_identity=receipt["identity"],
                    first_received=received.isoformat(),
                )
        for reference in references:
            records = [
                r for (event, _, _), r in receipt_groups.items() if event == reference["_event"]
            ]
            assert min(clock(r["first_received"]) for r in records) == reference["_closure"]
            reference["_closure_providers"] = sorted(
                {
                    r["provider"]
                    for r in records
                    if clock(r["first_received"]) == reference["_closure"]
                }
            )
        sensors = {}
        for info in rows(
            conn,
            "SELECT s.*,st.provider,st.provider_station_id,st.data_json station_json,a.distance_km FROM pws_sensors s JOIN pws_stations st USING(station_id) JOIN pws_airport_stations a USING(station_id) WHERE a.airport_icao=? AND EXISTS(SELECT 1 FROM pws_observations o WHERE o.sensor_id=s.sensor_id) ORDER BY s.sensor_id",
            (airport,),
        ):
            metadata = json.loads(info["data_json"])
            if metadata.get("phenomenon") != "temperature":
                continue
            sid = info["station_id"]
            discoveries = rows(
                conn,
                "SELECT at,data_json FROM pws_discoveries WHERE station_id=? AND airport_icao=? ORDER BY at,id",
                (sid, airport),
            )
            selections = rows(
                conn,
                "SELECT * FROM pws_selections WHERE station_id=? AND airport_icao=? ORDER BY created_at,id",
                (sid, airport),
            )
            sensor: dict[str, Any] = {
                **info,
                "airport": airport,
                "airport_metadata": airport_metadata,
                "sensor_type": metadata.get("sensor_type"),
                "metadata": [json.loads(r["data_json"]) for r in discoveries],
                "metadata_times": [clock(r["at"]) for r in discoveries],
                "selections": selections,
                "selection_times": [clock(r["created_at"]) for r in selections],
                "readings": [],
                "conflicts": {},
                "rejections": Counter(),
                "stored_count": 0,
                "pairs": [],
            }
            allrows: list[dict[str, Any]] = []
            conflict_evidence: list[dict[str, Any]] = []
            for raw in rows(
                conn, "SELECT * FROM pws_observations WHERE sensor_id=?", (info["sensor_id"],)
            ):
                sensor["stored_count"] += 1
                r = {
                    **json.loads(raw["data_json"]),
                    **raw,
                    "provider": info["provider"],
                    "station_id": sid,
                    "provider_sensor_id": info["provider_sensor_id"],
                }
                check = assess_time(r)
                # A conflicting second record is normally quarantined. It still
                # supplies the time at which a formerly usable first value
                # became contradicted, if all OTHER strict requirements pass.
                evidence_check = assess_time(
                    {
                        **r,
                        "quality_flags": [
                            flag
                            for flag in r.get("quality_flags", [])
                            if flag != "CONFLICTING_DUPLICATE"
                        ],
                    }
                )
                if (
                    evidence_check.eligible
                    and evidence_check.measurement_time is not None
                    and evidence_check.collector_receive_time is not None
                ):
                    conflict_evidence.append(
                        {
                            **r,
                            "_event": evidence_check.measurement_time,
                            "_received": evidence_check.collector_receive_time,
                        }
                    )
                if (
                    not check.eligible
                    or check.measurement_time is None
                    or check.collector_receive_time is None
                ):
                    sensor["rejections"].update(check.reasons)
                    continue
                r.update(
                    _event=check.measurement_time,
                    _received=check.collector_receive_time,
                    age_seconds=check.age_at_receipt_seconds,
                    timestamp_provenance=check.timestamp_provenance,
                    qc_status=check.status,
                    startup_censored=bool(arrivals.get(r["id"], {}).get("startup_censored", True)),
                    capture_run_id=arrivals.get(r["id"], {}).get("run_id"),
                )
                allrows.append(r)
            evidence_by_event: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
            for r in conflict_evidence:
                evidence_by_event[r["_event"]].append(r)
            for event, group in evidence_by_event.items():
                seen: set[float] = set()
                for r in sorted(group, key=lambda x: x["_received"]):
                    if seen and r["temperature_c"] not in seen:
                        sensor["conflicts"].setdefault(event, r["_received"])
                    seen.add(float(r["temperature_c"]))
            byevent: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
            for r in allrows:
                byevent[r["_event"]].append(r)
            for group in byevent.values():
                # Same event/value retains only first receipt; conflicting values retain evidence.
                unique: dict[float, dict[str, Any]] = {}
                for r in sorted(group, key=lambda x: x["_received"]):
                    unique.setdefault(float(r["temperature_c"]), r)
                sensor["readings"].extend(unique.values())
            sensor["readings"].sort(key=lambda r: (r["_event"], r["_received"], r["id"]))
            sensor["event_times"] = [r["_event"] for r in sensor["readings"]]
            for reference in references:
                if (
                    reference["startup_censored"]
                    or reference["coverage_gap"]
                    or reference["_closure_censored"]
                ):
                    continue
                paired_reading = latest(sensor, reference["_received"], around=reference["_event"])
                if paired_reading is not None:
                    sensor["pairs"].append(
                        dict(
                            _event=reference["_event"],
                            _received=reference["_received"],
                            report_identity=reference["report_identity"],
                            observation_id=paired_reading["id"],
                            offset_midpoint_c=paired_reading["temperature_c"]
                            - reference["temperature_c"],
                            _ambiguous_from=reference.get("_ambiguous_from"),
                            _pws_conflict_from=sensor["conflicts"].get(paired_reading["_event"]),
                        )
                    )
            sensors[info["sensor_id"]] = sensor
        result[airport] = dict(
            references=references,
            reports=reports,
            sensors=sensors,
            reference_exclusions=reference_exclusions,
            receipt_audit=list(receipt_groups.values()),
        )
    return result
