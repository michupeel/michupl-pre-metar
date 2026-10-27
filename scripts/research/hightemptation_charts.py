"""Static report charts from exported EXP-0012 evidence; no database or network I/O.

The caller owns inventory matching, timezone verification and forecast provenance.
These charts never fit a Tmax window or turn an unknown value into an observation.
"""

from __future__ import annotations

import csv
import math
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BLUE = "#246A73"
ORANGE = "#C86B35"
GREY = "#59636E"


def _read(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _number(value: object) -> float | None:
    try:
        result = float(str(value))
    except (ValueError, TypeError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _true(value: object) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def holding_series(
    rows: list[dict[str, str]],
) -> tuple[list[float], list[float | None], int]:
    """One exported fully closed BUY is one count, not one count per partial SELL.

    Explicitly ambiguous or invalid rows are excluded. Conditional FIFO records
    remain conditional and are labeled as such in the rendered chart.
    """
    durations: list[float] = []
    weights: list[float | None] = []
    omitted = 0
    for row in rows:
        status = row.get("status", "").upper()
        value = _number(row.get("holding_seconds"))
        if (
            not _true(row.get("fully_closed"))
            or ("primary_eligible" in row and not _true(row["primary_eligible"]))
            or value is None
            or value < 0
            or any(flag in status for flag in ("AMBIGUOUS", "INVALID", "EXCLUDED"))
        ):
            omitted += 1
            continue
        weight = _number(row.get("matched_quantity"))
        if weight is None:
            weight = _number(row.get("buy_size"))
        durations.append(value)
        weights.append(weight if weight is not None and weight > 0 else None)
    return durations, weights, omitted


def local_hours(rows: list[dict[str, str]]) -> tuple[dict[str, list[float]], int]:
    """Use verified exported zones; retain both occurrences of repeated DST hours."""
    result: dict[str, list[float]] = {"TMAX": [], "TMIN": []}
    omitted = 0
    for row in rows:
        kind = row.get("market_kind", "").upper()
        zone = row.get("timezone", "").strip()
        status = row.get("temporal_identity_status", "").upper()
        if (
            kind not in result
            or not zone
            or any(
                flag in status
                for flag in ("UNKNOWN", "UNVERIFIED", "MISSING", "AMBIGUOUS", "INVALID")
            )
        ):
            omitted += 1
            continue
        try:
            target_zone = ZoneInfo(zone)
            clock = row.get("local_time", "").strip()
            if clock:
                instant = datetime.fromisoformat(clock.replace("Z", "+00:00"))
                if instant.tzinfo is None or instant.utcoffset() is None:
                    raise ValueError("Naive local clock")
                local = instant.astimezone(target_zone)
                hour = local.hour + local.minute / 60 + local.second / 3600
            else:
                numeric_hour = _number(row.get("local_hour"))
                if numeric_hour is None:
                    raise ValueError("Unknown local hour")
                hour = numeric_hour
            if not 0 <= hour < 24:
                raise ValueError("Invalid local hour")
        except (ValueError, TypeError, ZoneInfoNotFoundError):
            omitted += 1
            continue
        result[kind].append(hour)
    return result, omitted


def _empty(axis: Any, explanation: str) -> None:
    axis.text(
        0.5,
        0.53,
        "INSUFFICIENT DATA",
        ha="center",
        va="center",
        transform=axis.transAxes,
        fontsize=15,
        color=GREY,
    )
    axis.text(
        0.5,
        0.43,
        explanation,
        ha="center",
        va="center",
        transform=axis.transAxes,
        fontsize=9,
        color=GREY,
        wrap=True,
    )


def _save(figure: Any, output: Path) -> None:
    # Matplotlib's dynamic Figure boundary stays local to presentation code.
    figure.savefig(output, dpi=160, facecolor="white", bbox_inches="tight")


def render(output: Path) -> list[Path]:
    """Render three PNGs from the required CSV files in ``output``.

    Price columns: price_bucket, buy_count, shares. Holding columns:
    fully_closed, holding_seconds, matched_quantity (or buy_size), status.
    Timing columns: market_kind, timezone, local_time or local_hour,
    temporal_identity_status. No live collector module is imported.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output.mkdir(parents=True, exist_ok=True)
    prices = _read(output / "hightemptation_price_distribution.csv")
    holdings = _read(output / "hightemptation_holding_times.csv")
    timing = _read(output / "hightemptation_tmax_timing.csv")
    paths: list[Path] = []
    with plt.rc_context(
        {
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titleweight": "semibold",
            "axes.labelcolor": GREY,
            "xtick.color": GREY,
            "ytick.color": GREY,
        }
    ):
        figure, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
        selected: list[tuple[str, float, float]] = []
        for row in prices:
            count, shares = _number(row.get("buy_count")), _number(row.get("shares"))
            if count is not None and shares is not None and count >= 0 and shares >= 0:
                selected.append((row.get("price_bucket", "UNKNOWN"), count, shares))
        if selected and any(row[1] for row in selected):
            labels = [row[0] for row in selected]
            positions = list(range(len(labels)))
            axes[0].barh(positions, [row[1] for row in selected], color=BLUE)
            axes[1].barh(positions, [row[2] for row in selected], color=ORANGE)
            axes[0].set_yticks(positions, labels)
            axes[0].invert_yaxis()
            axes[0].set_xlabel("NO BUY records")
            axes[1].set_xlabel("Purchased shares")
            for axis in axes:
                axis.grid(axis="x", alpha=0.18)
                axis.set_axisbelow(True)
        else:
            for axis in axes:
                _empty(axis, "No exported NO purchase distribution")
        axes[0].set_title("Record-weighted")
        axes[1].set_title("Share-volume-weighted")
        figure.suptitle("HighTempTation — observed NO entry prices", fontsize=15)
        figure.text(
            0.5,
            0.015,
            "Buckets preserve the report definitions. Entry frequency is not profitability; fees are not inferred.",
            ha="center",
            fontsize=9,
            color=GREY,
        )
        figure.tight_layout(rect=(0, 0.05, 1, 0.94))
        path = output / "hightemptation_price_distribution.png"
        _save(figure, path)
        plt.close(figure)
        paths.append(path)

        durations, weights, omitted = holding_series(holdings)
        figure, axes = plt.subplots(1, 2, figsize=(12, 5))
        if durations:
            upper = max(durations)
            bins = [0.0] + [
                float(value)
                for value in (1, 3, 5, 10, 15, 30, 60, 180, 600, 1800, 3600, 10800, 86400)
                if value < upper
            ]
            bins.append(max(upper * 1.01, 1))
            axes[0].hist(durations, bins=bins, color=BLUE, edgecolor="white")
            axes[0].set_xscale("symlog", linthresh=1)
            axes[0].set_ylabel("Fully quantity-matched BUY records")
            ordered = sorted(zip(durations, weights, strict=True), key=lambda pair: pair[0])
            clocks = [row[0] for row in ordered]
            axes[1].step(
                clocks,
                [(index + 1) / len(ordered) for index in range(len(ordered))],
                where="post",
                color=BLUE,
                label=f"BUY records (N={len(ordered)})",
            )
            weighted = [(clock, weight) for clock, weight in ordered if weight is not None]
            total_weight = sum(weight for _, weight in weighted)
            if total_weight > 0:
                cumulative = 0.0
                cumulative_weights = []
                for _, weight in weighted:
                    cumulative += weight
                    cumulative_weights.append(cumulative / total_weight)
                axes[1].step(
                    [clock for clock, _ in weighted],
                    cumulative_weights,
                    where="post",
                    color=ORANGE,
                    label=f"Matched shares (weighted records N={len(weighted)})",
                )
            axes[1].set_xscale("symlog", linthresh=1)
            axes[1].set_ylim(0, 1.02)
            axes[1].set_ylabel("Cumulative fraction")
            axes[1].legend(loc="lower right", fontsize=8)
            for axis in axes:
                axis.set_xlabel("Source-clock holding duration (seconds; logarithmic above 1s)")
                axis.grid(alpha=0.18)
        else:
            for axis in axes:
                _empty(axis, "No unambiguous fully quantity-matched closures")
        axes[0].set_title("Matched closure durations")
        axes[1].set_title("Record and matched-share ECDF")
        figure.suptitle("HighTempTation — quantity-matched FIFO closure times", fontsize=15)
        figure.text(
            0.5,
            0.015,
            f"N={len(durations)} eligible fully closed BUY records; {omitted} omitted. FIFO is an accounting convention; opening inventory can be conditional.",
            ha="center",
            fontsize=8.5,
            color=GREY,
        )
        figure.tight_layout(rect=(0, 0.06, 1, 0.94))
        path = output / "hightemptation_holding_times.png"
        _save(figure, path)
        plt.close(figure)
        paths.append(path)

        hours, omitted = local_hours(timing)
        figure, axis = plt.subplots(figsize=(12, 5))
        available = [(kind, values) for kind, values in hours.items() if values]
        if available:
            colors = {"TMAX": BLUE, "TMIN": ORANGE}
            axis.hist(
                [values for _, values in available],
                bins=list(range(25)),
                stacked=True,
                color=[colors[kind] for kind, _ in available],
                edgecolor="white",
                label=[f"{kind} (N={len(values)})" for kind, values in available],
            )
        else:
            _empty(axis, "No timezone-verified local trade times")
        axis.axvspan(14, 16, color="#9AA3AA", alpha=0.22, label="14:00–16:00 clock-time probe")
        axis.set_xlim(0, 24)
        axis.set_xticks(list(range(0, 25, 2)))
        axis.set_xlabel("City-reference local hour (identity status retained in CSV)")
        axis.set_ylabel("BUY records")
        axis.set_title("HighTempTation — local entry times, Tmax and Tmin markets", pad=13)
        axis.grid(axis="y", alpha=0.18)
        axis.set_axisbelow(True)
        axis.legend(loc="upper left", fontsize=9)
        figure.text(
            0.5,
            0.015,
            f"{omitted} rows omitted for unknown/invalid identity or time. City identity can be retrospective; shaded hours are a probe, not forecast Tmax.",
            ha="center",
            fontsize=8.5,
            color=GREY,
        )
        figure.tight_layout(rect=(0, 0.06, 1, 1))
        path = output / "hightemptation_local_trade_timing.png"
        _save(figure, path)
        plt.close(figure)
        paths.append(path)
    return paths
