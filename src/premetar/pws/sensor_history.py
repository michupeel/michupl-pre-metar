"""Read-only instrument histories and explicitly exploratory METAR comparisons."""

import json
import sqlite3
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any
from zoneinfo import ZoneInfo

from astral import Observer
from astral.sun import elevation

from premetar.model import icao_round_temperature, utc_now
from premetar.performance import timed_operation
from premetar.pws.analysis import interval_residual
from premetar.pws.daily import export, load_day, local, metars
from premetar.pws.daily_time import local_day_bounds
from premetar.pws.geometry import haversine_km
from premetar.pws.integrity import prediction_issues
from premetar.pws.repository import rows
from premetar.pws.timestamps import assess_time
from premetar.sources import STATIONS


def split_series(
    observations: list[dict[str, Any]], maximum_gap_seconds: float = 900
) -> list[list[dict[str, Any]]]:
    """Never draw a continuous line across an unobserved long gap."""
    segments: list[list[dict[str, Any]]] = []
    for row in sorted(observations, key=lambda r: r["measurement_time_utc"]):
        event = datetime.fromisoformat(row["measurement_time_utc"])
        previous = (
            datetime.fromisoformat(segments[-1][-1]["measurement_time_utc"]) if segments else None
        )
        if previous is None or (event - previous).total_seconds() > maximum_gap_seconds:
            segments.append([])
        segments[-1].append(row)
    return segments


def compare(
    observations: list[dict[str, Any]],
    reports: list[dict[str, Any]],
    sensor_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Nearest +/-5min is agreement only; prospective candidates use receipt cutoffs."""
    output = []
    sensors = sorted({r["sensor_id"] for r in observations} | (sensor_ids or set()))
    for report in reports:
        if report["temperature_c"] is None:
            continue
        target = datetime.fromisoformat(report["observation_time_utc"])
        first = datetime.fromisoformat(report["first_received_utc"])
        for sensor in sensors:
            history = [r for r in observations if r["sensor_id"] == sensor]
            nearest: dict[str, Any] | None = min(
                history,
                key=lambda r: abs(
                    (datetime.fromisoformat(r["measurement_time_utc"]) - target).total_seconds()
                ),
                default=None,
            )
            delta = (
                (datetime.fromisoformat(nearest["measurement_time_utc"]) - target).total_seconds()
                if nearest
                else None
            )
            if delta is not None and abs(delta) > 300:
                nearest = None
            phases: dict[str, dict[str, Any] | None] = {}
            for phase, cutoff in (
                ("pre_observation", min(target, first)),
                ("before_first_receipt", first),
            ):
                eligible = [
                    r
                    for r in history
                    if datetime.fromisoformat(r["collector_first_receive_time"]) < cutoff
                    and assess_time(
                        {
                            **r,
                            "observation_time": r["measurement_time_utc"],
                            "first_receive_time": r["collector_first_receive_time"],
                        },
                        cutoff,
                    ).eligible
                ]
                phases[phase] = (
                    max(eligible, key=lambda r: r["measurement_time_utc"]) if eligible else None
                )
            output.append(
                dict(
                    sensor_id=sensor,
                    metar_nominal_time=target.isoformat(),
                    metar_first_received_at=first.isoformat(),
                    metar_temperature_integer=report["temperature_c"],
                    report_type=report["report_type"],
                    correction=report["correction"],
                    nearest_pws_measurement_time=nearest["measurement_time_utc"]
                    if nearest
                    else None,
                    nearest_pws_temperature=nearest["temperature_c"] if nearest else None,
                    pws_first_received_at=nearest["collector_first_receive_time"]
                    if nearest
                    else None,
                    time_difference_seconds=delta if nearest else None,
                    interval_aware_error=abs(
                        interval_residual(nearest["temperature_c"], report["temperature_c"])
                    )
                    if nearest
                    else None,
                    meteorological_analysis="RETROSPECTIVE_NEAREST_WITHIN_5_MINUTES",
                    pre_observation_input_id=phases["pre_observation"]["observation_id"]
                    if phases["pre_observation"]
                    else None,
                    pre_observation_temperature=phases["pre_observation"]["temperature_c"]
                    if phases["pre_observation"]
                    else None,
                    before_receipt_input_id=phases["before_first_receipt"]["observation_id"]
                    if phases["before_first_receipt"]
                    else None,
                    before_receipt_temperature=phases["before_first_receipt"]["temperature_c"]
                    if phases["before_first_receipt"]
                    else None,
                    availability_phase=(
                        "POST_OBSERVATION_PRE_RECEIPT"
                        if phases["before_first_receipt"]
                        and datetime.fromisoformat(
                            phases["before_first_receipt"]["collector_first_receive_time"]
                        )
                        >= target
                        else "PRE_OBSERVATION"
                        if phases["before_first_receipt"]
                        else "NO_ELIGIBLE_INPUT"
                    ),
                    prospective_prediction_claim=False,
                )
            )
    return output


def summarize(history: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(history, key=lambda r: r["measurement_time_utc"])
    values = [r["temperature_c"] for r in ordered]
    times = sorted({datetime.fromisoformat(r["measurement_time_utc"]) for r in ordered})
    gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:], strict=False)]
    return dict(
        count=len(ordered),
        first=ordered[0]["measurement_time_utc"] if ordered else None,
        last=ordered[-1]["measurement_time_utc"] if ordered else None,
        minimum_c=min(values) if values else None,
        maximum_c=max(values) if values else None,
        mean_c=mean(values) if values else None,
        median_c=median(values) if values else None,
        median_update_interval_seconds=median(gaps) if gaps else None,
        largest_gap_seconds=max(gaps) if gaps else None,
        median_age_seconds=median(r["observation_age_seconds"] for r in ordered)
        if ordered
        else None,
        spike_suspicions=sum(
            abs(b["temperature_c"] - a["temperature_c"])
            / max(
                (
                    datetime.fromisoformat(b["measurement_time_utc"])
                    - datetime.fromisoformat(a["measurement_time_utc"])
                ).total_seconds()
                / 60,
                0.001,
            )
            > 2
            for a, b in zip(ordered, ordered[1:], strict=False)
        ),
    )


def history_snapshot(
    conn: sqlite3.Connection,
    station_id: str,
    day: date,
    timezone: str = "Europe/Warsaw",
    sensor: str | None = None,
) -> dict[str, Any]:
    zone = ZoneInfo(timezone)
    start, end = local_day_bounds(day, timezone)
    found = rows(
        conn,
        "SELECT * FROM pws_stations WHERE station_id=? OR provider_station_id=?",
        (station_id, station_id),
    )
    if len(found) != 1:
        raise ValueError("Station not found or provider identity ambiguous; use full station ID")
    station = found[0]
    metadata = json.loads(station["data_json"])
    airports = rows(
        conn,
        "SELECT a.*,p.data_json airport_json FROM pws_airport_stations a JOIN pws_airports p ON p.icao=a.airport_icao WHERE a.station_id=? ORDER BY a.distance_km",
        (station["station_id"],),
    )
    if not airports:
        raise ValueError("Station has no airport association")
    airport = airports[0]["airport_icao"]
    airport_meta = json.loads(airports[0]["airport_json"])
    instruments = rows(
        conn,
        "SELECT * FROM pws_sensors WHERE station_id=? ORDER BY sensor_id",
        (station["station_id"],),
    )
    instruments = [
        {**r, "metadata": json.loads(r["data_json"])}
        for r in instruments
        if sensor is None or sensor in (r["sensor_id"], r["provider_sensor_id"])
    ]
    ids = {r["sensor_id"] for r in instruments if r["metadata"].get("phenomenon") == "temperature"}
    if sensor is not None and not ids:
        raise ValueError("Temperature sensor not found at this station")
    valid: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    seen = set()
    for row in load_day(conn, airport, start, end):
        if row["sensor_id"] not in ids:
            continue
        check = assess_time(row)
        event = check.measurement_time
        if not check.eligible or event is None or not start <= event < end:
            excluded.append(
                dict(
                    observation_id=row["id"],
                    sensor_id=row["sensor_id"],
                    status=check.status,
                    reasons=list(check.reasons),
                )
            )
            continue
        key = (row["sensor_id"], event, row["temperature_c"])
        if key in seen:
            continue
        seen.add(key)
        valid.append(
            dict(
                observation_id=row["id"],
                station_id=station["station_id"],
                provider=station["provider"],
                sensor_id=row["sensor_id"],
                provider_sensor_id=row["provider_sensor_id"],
                sensor_type=json.loads(row["sensor_json"]).get("sensor_type"),
                measurement_time_utc=event.isoformat(),
                measurement_time_local=local(event, zone),
                collector_first_receive_time=row["first_receive_time"],
                temperature_c=row["temperature_c"],
                raw_temperature=row.get("raw_temperature"),
                raw_unit=row.get("raw_unit"),
                source_precision=row.get("source_precision"),
                observation_age_seconds=check.age_at_receipt_seconds,
                timestamp_provenance=check.timestamp_provenance,
                # Existing audited provider contract; not upload-origin attestation.
                timestamp_semantics_verified=check.semantics_reference is not None,
                evidence_class=row.get("evidence_class"),
                qc_status=check.status,
                quality_flags=row.get("quality_flags", []),
            )
        )
    valid.sort(key=lambda r: (r["measurement_time_utc"], r["sensor_id"]))
    official = metars(conn, airport, start, end, zone)
    observer = Observer(metadata["latitude"], metadata["longitude"])
    for item in valid:
        item["solar_elevation_degrees"] = elevation(
            observer, datetime.fromisoformat(item["measurement_time_utc"])
        )
        item["solar_period"] = "DAY" if item["solar_elevation_degrees"] > 0 else "NIGHT"
    bysensor = {sid: summarize([r for r in valid if r["sensor_id"] == sid]) for sid in sorted(ids)}
    predictions = []
    observation_ids = {r["observation_id"] for r in valid}
    for row in rows(
        conn,
        "SELECT * FROM pws_predictions WHERE airport_icao=? AND julianday(target_time)>=julianday(?) AND julianday(target_time)<julianday(?)",
        (airport, start.isoformat(), end.isoformat()),
    ):
        data = json.loads(row["data_json"])
        if not observation_ids.intersection(data.get("input_observation_ids", [])):
            continue
        issues = prediction_issues(conn, data)
        settlements = (
            rows(
                conn,
                "SELECT official_integer,reference_first_seen,correction,settled_at,data_json FROM continuous_settlements WHERE prediction_id=? ORDER BY id",
                (row["id"],),
            )
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='continuous_settlements'"
            ).fetchone()
            else []
        )
        predictions.append(
            dict(
                id=row["id"],
                target_time=row["target_time"],
                created_at=row["created_at"],
                integer_temperature=data.get("integer_temperature"),
                method=data.get("method"),
                issues=issues,
                eligible=not issues,
                settlements=settlements,
            )
        )
    transitions = []
    # Initial uncorrected routine report only; corrections and SPECI stay in comparison export.
    routine: dict[str, dict[str, Any]] = {}
    for report in official:
        if (
            report["report_type"] == "METAR"
            and not report["correction"]
            and datetime.fromisoformat(report["observation_time_utc"]).minute
            in STATIONS[airport].routine_minutes
        ):
            routine.setdefault(report["observation_time_utc"], report)
    ordered = [routine[k] for k in sorted(routine)]
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if previous["temperature_c"] is None or current["temperature_c"] is None:
            continue
        begin = datetime.fromisoformat(previous["observation_time_utc"])
        cutoff = datetime.fromisoformat(current["first_received_utc"])
        for sid in sorted(ids):
            window = [
                r
                for r in valid
                if r["sensor_id"] == sid
                and begin
                < datetime.fromisoformat(r["measurement_time_utc"])
                <= datetime.fromisoformat(current["observation_time_utc"])
                and datetime.fromisoformat(r["collector_first_receive_time"]) < cutoff
                and assess_time(
                    {
                        **r,
                        "observation_time": r["measurement_time_utc"],
                        "first_receive_time": r["collector_first_receive_time"],
                    }
                ).eligible
            ]
            matches = [
                r
                for r in window
                if icao_round_temperature(r["temperature_c"]) == current["temperature_c"]
            ]
            # Earliest measurement is not necessarily the earliest available signal.
            matches.sort(
                key=lambda r: (
                    datetime.fromisoformat(r["collector_first_receive_time"]),
                    datetime.fromisoformat(r["measurement_time_utc"]),
                    r["observation_id"],
                )
            )
            wrong_changes = [
                r
                for r in window
                if icao_round_temperature(r["temperature_c"])
                not in (previous["temperature_c"], current["temperature_c"])
            ]
            transitions.append(
                dict(
                    sensor_id=sid,
                    target_time=current["observation_time_utc"],
                    previous_integer=previous["temperature_c"],
                    actual_integer=current["temperature_c"],
                    transition_at_least_1c=abs(current["temperature_c"] - previous["temperature_c"])
                    >= 1,
                    first_matching_measurement=matches[0]["measurement_time_utc"]
                    if matches
                    else None,
                    first_matching_receipt=matches[0]["collector_first_receive_time"]
                    if matches
                    else None,
                    matching_observation_id=matches[0]["observation_id"] if matches else None,
                    first_signal_phase=(
                        "PRE_OBSERVATION"
                        if datetime.fromisoformat(matches[0]["collector_first_receive_time"])
                        < datetime.fromisoformat(current["observation_time_utc"])
                        else "POST_OBSERVATION_PRE_RECEIPT"
                    )
                    if matches
                    else None,
                    pws_window_trend_c=(
                        max(window, key=lambda r: r["measurement_time_utc"])["temperature_c"]
                        - min(window, key=lambda r: r["measurement_time_utc"])["temperature_c"]
                    )
                    if len(window) >= 2
                    else None,
                    pws_trend_agrees=(
                        (
                            max(window, key=lambda r: r["measurement_time_utc"])["temperature_c"]
                            - min(window, key=lambda r: r["measurement_time_utc"])["temperature_c"]
                        )
                        * (current["temperature_c"] - previous["temperature_c"])
                        > 0
                    )
                    if len(window) >= 2 and current["temperature_c"] != previous["temperature_c"]
                    else None,
                    exploratory_wrong_change_records=len(wrong_changes),
                    persistence_correct=previous["temperature_c"] == current["temperature_c"],
                    immutable_predictions=[
                        p["id"]
                        for p in predictions
                        if p["target_time"] == current["observation_time_utc"] and p["eligible"]
                    ],
                    immutable_predictions_created_by_first_match_receipt=[
                        p["id"]
                        for p in predictions
                        if matches
                        and p["eligible"]
                        and p["target_time"] == current["observation_time_utc"]
                        and datetime.fromisoformat(p["created_at"])
                        <= datetime.fromisoformat(matches[0]["collector_first_receive_time"])
                    ],
                    analysis="RETROSPECTIVE_EXPLORATORY_NOT_LIVE_PREDICTION",
                )
            )
    return dict(
        station=station["station_id"],
        station_metadata=metadata,
        airport=airport,
        date=day.isoformat(),
        timezone=timezone,
        start_utc=start.isoformat(),
        end_utc_exclusive=end.isoformat(),
        as_of=utc_now().isoformat(),
        distance_km=haversine_km(
            metadata["latitude"],
            metadata["longitude"],
            airport_meta["latitude"],
            airport_meta["longitude"],
        ),
        instruments=instruments,
        observations=valid,
        excluded=excluded,
        summaries=bysensor,
        metars=official,
        comparisons=compare(valid, official, ids),
        transitions=transitions,
        linked_immutable_predictions=predictions,
        solar_period_summaries={
            period: summarize([r for r in valid if r["solar_period"] == period])
            for period in ("DAY", "NIGHT")
        },
        current_availability=(
            rows(
                conn,
                "SELECT checked_at,status,data_json FROM pws_sensor_checks WHERE station_id=? ORDER BY id DESC LIMIT ?",
                (station["station_id"], len(ids)),
            )
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='pws_sensor_checks'").fetchone()
            else []
        ),
    )


def write_chart(result: dict[str, Any], path: Path) -> bool:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    zone = ZoneInfo(result["timezone"])
    dates: Any = mdates  # Matplotlib DateFormatter has incomplete third-party typing.
    fig, ax = plt.subplots(figsize=(12, 5))
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in result["observations"]:
        grouped[row["sensor_id"]].append(row)
    for sid, history in grouped.items():
        for number, segment in enumerate(split_series(history)):
            ax.plot(
                dates.date2num(
                    [datetime.fromisoformat(r["measurement_time_utc"]) for r in segment]
                ),
                [r["temperature_c"] for r in segment],
                marker="o",
                markersize=3,
                linewidth=1,
                label=sid.split(":")[-1] if number == 0 else None,
            )
    official = [r for r in result["metars"] if r["temperature_c"] is not None]
    if official:
        ax.scatter(
            dates.date2num([datetime.fromisoformat(r["observation_time_utc"]) for r in official]),
            [r["temperature_c"] for r in official],
            marker="s",
            s=24,
            color="black",
            label="EPWA METAR (integer °C)",
            zorder=4,
        )
    ax.xaxis.set_major_formatter(dates.DateFormatter("%H:%M %Z\n%z", tz=zone))
    ax.xaxis.set_major_locator(dates.HourLocator(interval=3, tz=zone))
    ax.set(
        title=f"{result['airport']} nearest station {result['station'].split(':')[-1]} | {result['date']}",
        xlabel=f"Measurement time — {result['timezone']} (offset shown)",
        ylabel="Temperature °C",
    )
    ax.grid(alpha=0.2)
    if grouped or official:
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return True


def write_report(result: dict[str, Any], output: Path) -> dict[str, str]:
    with timed_operation("REPORT_GENERATION", rows=len(result["observations"])):
        return _write_report_impl(result, output)


def _write_report_impl(result: dict[str, Any], output: Path) -> dict[str, str]:
    output.mkdir(parents=True, exist_ok=True)
    stem = f"{result['airport']}_{result['date']}"
    paths = {
        key: str(output / name)
        for key, name in dict(
            markdown=f"{stem}_nearest_sensor.md",
            csv=f"{stem}_nearest_sensor.csv",
            png=f"{stem}_nearest_sensor.png",
            comparison=f"{stem}_metar_comparison.csv",
        ).items()
    }
    export(
        Path(paths["csv"]),
        result["observations"],
        [
            "measurement_time_utc",
            "measurement_time_local",
            "collector_first_receive_time",
            "sensor_id",
            "temperature_c",
        ],
    )
    export(
        Path(paths["comparison"]),
        result["comparisons"],
        ["metar_nominal_time", "metar_first_received_at", "metar_temperature_integer", "sensor_id"],
    )
    chart = write_chart(result, Path(paths["png"]))
    lines = [
        f"# {result['airport']} sensor history — {result['date']}",
        "",
        f"Station: `{result['station']}`. Recomputed horizontal distance: **{result['distance_km']:.3f} km**.",
        f"Coordinates: {result['station_metadata']['latitude']}, {result['station_metadata']['longitude']}.",
        f"Window: [{result['start_utc']}, {result['end_utc_exclusive']}); {result['timezone']}. Snapshot: {result['as_of']}.",
        "",
        "## Measurement coverage",
        f"Valid unique measurements: **{len(result['observations'])}**. Excluded records: **{len(result['excluded'])}**. No interpolation or forward fill.",
        "",
        "| Instrument | N | First UTC | Last UTC | Min | Max | Mean | Median | Median interval s | Largest gap s | Median age s |",
        "|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for sid, s in result["summaries"].items():
        lines.append(
            "| "
            + " | ".join(
                str(v)
                for v in [
                    sid,
                    s["count"],
                    s["first"],
                    s["last"],
                    s["minimum_c"],
                    s["maximum_c"],
                    s["mean_c"],
                    s["median_c"],
                    s["median_update_interval_seconds"],
                    s["largest_gap_seconds"],
                    s["median_age_seconds"],
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "Instrument metadata:",
            "```json",
            json.dumps(
                [{"sensor_id": r["sensor_id"], **r["metadata"]} for r in result["instruments"]],
                indent=2,
                ensure_ascii=False,
            ),
            "```",
            "",
            "## METAR agreement and availability",
            "Nearest measurements within ±5 minutes are retrospective meteorological agreement, potentially including later measurements. The CSV separately identifies inputs received before nominal observation and before our first METAR receipt. Continuous error is distance outside the quantization interval; it is not thermometer bias against an exact airport temperature.",
            "",
            "| METAR nominal UTC | Integer °C | Sensor | Nearby °C | Δtime s | Interval error °C | Availability phase |",
            "|---|---:|---|---:|---:|---:|---|",
        ]
    )
    # The CSV is complete; keep the report readable while still showing genuine readings.
    reading_lines = [
        "",
        "## Latest 30 actual readings",
        "",
        "| Measurement local (offset) | Measurement UTC | Instrument | Temperature °C | Age s |",
        "|---|---|---|---:|---:|",
    ]
    for r in result["observations"][-30:]:
        reading_lines.append(
            "| "
            + " | ".join(
                str(r[k])
                for k in (
                    "measurement_time_local",
                    "measurement_time_utc",
                    "provider_sensor_id",
                    "temperature_c",
                    "observation_age_seconds",
                )
            )
            + " |"
        )
    lines[
        lines.index("## METAR agreement and availability") : lines.index(
            "## METAR agreement and availability"
        )
    ] = reading_lines + [""]
    for c in result["comparisons"]:
        lines.append(
            "| "
            + " | ".join(
                str(c[k])
                for k in (
                    "metar_nominal_time",
                    "metar_temperature_integer",
                    "sensor_id",
                    "nearest_pws_temperature",
                    "time_difference_seconds",
                    "interval_aware_error",
                    "availability_phase",
                )
            )
            + " |"
        )
    linked = result["linked_immutable_predictions"]
    matched = [c for c in result["comparisons"] if c["interval_aware_error"] is not None]
    signed = [
        interval_residual(c["nearest_pws_temperature"], c["metar_temperature_integer"])
        for c in matched
    ]
    lines.extend(
        [
            "",
            f"Aligned provider-report comparisons: {len(matched)}; mean interval distance °C: {mean(abs(v) for v in signed) if signed else 'INSUFFICIENT DATA'}; mean signed interval residual °C: {mean(signed) if signed else 'INSUFFICIENT DATA'}. Report variants/corrections are retained and are not independent meteorological events.",
            "",
            "## Solar periods and current availability",
            "DAY means solar elevation above 0° at the station (Astral geometry); NIGHT otherwise. Temperature differences between periods also reflect actual weather, not an isolated heating diagnostic.",
            "```json",
            json.dumps(result["solar_period_summaries"], indent=2),
            "```",
            "Latest availability checks are point-in-time evidence; their full diagnostic JSON is retained below. They do not certify uninterrupted freshness.",
            "```json",
            json.dumps(result["current_availability"], indent=2),
            "```",
            "",
            "## Exploratory transitions",
            "Transitions compare initial routine, uncorrected METARs. SPECI and corrections remain in the comparison export. A false-alarm record means an in-window received sensor value rounded to neither the previous nor eventual target integer; counts are records, not independent events. Matching signals are selected retrospectively and are never called live predictions.",
            "```json",
            json.dumps(result["transitions"], indent=2),
            "```",
            "",
            "## Actual immutable predictions",
            f"Predictions with input IDs linked to this station's valid day records: {len(linked)}; integrity-eligible: {sum(p['eligible'] for p in linked)}.",
            "```json",
            json.dumps(linked, indent=2),
            "```",
            "",
            "## Preliminary interpretation",
            "Timestamp validity is assessed at first receipt using the unchanged strict policy. Present-day staleness does not invalidate a historically fresh receipt. Missing periods are unobserved. Continuity, update interval, freshness and quantization-aware agreement describe operational usefulness only. A single day cannot establish permanent bias, calibration, solar heating or an information edge; TRUSTED status is not assigned. Clock offset uncertainty limits latency interpretation.",
            f"Chart: {'generated' if chart else 'UNAVAILABLE: install the project development plotting dependency'}. Lines stop at gaps greater than 15 minutes.",
        ]
    )
    Path(paths["markdown"]).write_text("\n".join(lines) + "\n", encoding="utf-8")
    if not chart:
        paths.pop("png")
    return paths
