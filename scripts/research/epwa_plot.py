"""Report-only plots of captured PWS measurements and quantized METAR reports."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


def measurement_segments(
    observations: list[dict[str, Any]], max_gap_seconds: float = 900
) -> list[list[tuple[datetime, float]]]:
    """Sort a single instrument's points and split gaps using unambiguous UTC."""
    points: list[tuple[datetime, float]] = []
    for row in observations:
        instant = datetime.fromisoformat(str(row["measurement_time_utc"]).replace("Z", "+00:00"))
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("Measurement timestamps must be timezone aware")
        points.append((instant.astimezone(UTC), float(row["temperature_c"])))
    points.sort(key=lambda point: point[0])
    segments: list[list[tuple[datetime, float]]] = []
    for point in points:
        if not segments or (point[0] - segments[-1][-1][0]).total_seconds() > max_gap_seconds:
            segments.append([])
        segments[-1].append(point)
    return segments


def plot_comparison(
    observations: list[dict[str, Any]],
    metars: list[dict[str, Any]],
    stations: list[dict[str, Any]],
    output: Path,
) -> None:
    """Plot each instrument separately; METAR integers are unconnected reference points.

    Only validated, deduplicated observations should be supplied by the caller.
    This function never accesses the database or collector.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    # Matplotlib's date helpers have no typed signatures. Keep that boundary
    # local while passing numeric date coordinates to its typed plotting API.
    dates: Any = mdates
    warsaw = ZoneInfo("Europe/Warsaw")
    inventory = {str(station["station_id"]): station for station in stations}
    instruments: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in observations:
        key = str(row["station_id"]), str(row["sensor_id"])
        instruments.setdefault(key, []).append(row)
    fig, axis = plt.subplots(figsize=(14, 7))
    palette = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9"]
    all_times: list[datetime] = []
    for index, ((station_id, sensor_id), rows) in enumerate(sorted(instruments.items())):
        station = inventory.get(station_id, {})
        name = str(station.get("station_name") or station_id)
        distance = station.get("distance_km")
        distance_label = f", {float(distance):.3f} km" if distance is not None else ""
        label = f"{name}{distance_label} — sensor {sensor_id}"
        for segment_index, segment in enumerate(measurement_segments(rows)):
            times, temperatures = zip(*segment, strict=True)
            all_times.extend(times)
            axis.plot(
                times,
                temperatures,
                color=palette[index % len(palette)],
                marker="o",
                markersize=3,
                linewidth=1.1,
                alpha=0.85,
                label=label if segment_index == 0 else "_nolegend_",
            )
    report_times: list[datetime] = []
    report_temperatures: list[float] = []
    seen_reports: set[tuple[datetime, float]] = set()
    for report in metars:
        if str(report.get("report_type", "")).upper() != "METAR" or report.get("correction"):
            continue
        if report.get("temperature_c") is None:
            continue
        instant = datetime.fromisoformat(str(report["observation_time_utc"]).replace("Z", "+00:00"))
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("METAR timestamps must be timezone aware")
        instant = instant.astimezone(UTC)
        temperature = float(report["temperature_c"])
        identity = instant, temperature
        if identity in seen_reports:
            continue
        seen_reports.add(identity)
        report_times.append(instant)
        report_temperatures.append(temperature)
    if report_times:
        all_times.extend(report_times)
        axis.scatter(
            [float(dates.date2num(instant)) for instant in report_times],
            report_temperatures,
            color="#222222",
            marker="D",
            s=32,
            zorder=5,
            label="EPWA routine METAR (integer °C; not a precise continuous reference)",
        )
    if all_times:
        first_date = min(all_times).astimezone(warsaw).date()
        last_date = max(all_times).astimezone(warsaw).date()
        start = datetime.combine(first_date, datetime.min.time(), warsaw)
        end = datetime.combine(last_date + timedelta(days=1), datetime.min.time(), warsaw)
        axis.set_xlim(float(dates.date2num(start)), float(dates.date2num(end)))
    else:
        axis.text(0.5, 0.5, "No valid captured measurements", transform=axis.transAxes, ha="center")
    axis.xaxis.set_major_locator(dates.AutoDateLocator(tz=warsaw, minticks=6, maxticks=11))
    axis.xaxis.set_major_formatter(dates.DateFormatter("%d %b\n%H:%M %Z\n%z", tz=warsaw))
    axis.set_title("EPWA nearby temperature instruments versus official routine METAR", pad=15)
    axis.set_xlabel("Warsaw local time — timezone offsets distinguish the repeated DST hour")
    axis.set_ylabel("Temperature (°C)")
    axis.grid(True, color="#dddddd", linewidth=0.6, alpha=0.8)
    axis.spines[["top", "right"]].set_visible(False)
    if instruments or report_times:
        axis.legend(loc="upper center", bbox_to_anchor=(0.5, -0.24), frameon=False, fontsize=8)
    fig.text(
        0.01,
        0.01,
        "Captured measurements only. Lines stop at gaps >15 min; missing periods are not interpolated.",
        fontsize=8,
        color="#555555",
    )
    fig.subplots_adjust(bottom=0.35, left=0.07, right=0.98, top=0.91)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        fig.savefig(output, dpi=170, facecolor="white")
    finally:
        plt.close(fig)
