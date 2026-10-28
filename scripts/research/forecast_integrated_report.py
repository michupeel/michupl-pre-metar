"""EXP0013 offline reports from immutable weather/research SQLite snapshots only."""

import argparse
import csv
import hashlib
import json
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo

from premetar.sources import STATIONS
from scripts.research.forecast_weather_context import (
    context_from_dataset,
    history_from_dataset,
    load_snapshot,
)


def clock(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Timezone-aware receipt required")
    return result.astimezone(UTC)


def read_research(snapshot: Path) -> list[dict[str, Any]]:
    """Deliberately skip potentially huge raw/delta history; summaries retain their IDs."""
    conn = sqlite3.connect(snapshot.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        return [
            dict(id=r[0], kind=r[1], received_at=r[2], payload=json.loads(r[3]))
            for r in conn.execute(
                "SELECT id,kind,received_at,payload FROM events WHERE kind IN "
                "('RUN','STOP','FORECAST','WINDOW','SIGNAL','BOOK_SAMPLE',"
                "'WEATHER_CONTEXT','HEALTH','COVERAGE','ERROR','OUTCOME','EXCLUSION') ORDER BY id"
            )
        ]
    finally:
        conn.close()


def export(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row}) or ["status"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            {
                key: json.dumps(value, sort_keys=True, default=str)
                if isinstance(value, (dict, list))
                else value
                for key, value in row.items()
            }
            for row in rows
        )


def analysis_signals(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prototype v1 notifications remain evidence, excluded from v1.1 analysis."""
    return [
        event
        for event in events
        if event["kind"] == "SIGNAL" and event["payload"].get("version") == "EXP0013-v1.1"
    ]


def live_calibrated_signals(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for event in analysis_signals(events):
        signal = event["payload"]
        if signal.get("kind") not in {
            "PWS_CONFIRMS_UPWARD_TRANSITION",
            "PWS_CONFIRMS_DOWNWARD_TRANSITION",
            "PWS_CONFIRMS_UNCHANGED",
        }:
            continue
        inputs = signal.get("inputs", {})
        params, reading = inputs.get("calibration", {}), inputs.get("reading", {})
        try:
            created = clock(signal["created_at"])
            calibrated = float(inputs["calibrated_temperature_c"])
            measured = clock(reading["observation_time"])
            received = clock(reading["first_receive_time"])
            history_available = clock(params["history_available_by"])
            if (
                params["calibration_n"] < 12
                or len(set(params["calibration_reference_ids"])) < 12
                or history_available >= created
                or not math.isfinite(calibrated)
                or measured > received
                or received > created
                or not 0 <= (created - measured).total_seconds() <= 300
            ):
                continue
            result.append(event)
        except (ValueError, TypeError, KeyError):
            continue
    return result


def signal_identity(event: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive identity only from a watchlist captured before this signal."""
    inputs = event["payload"].get("inputs", {})
    token = inputs.get("token_id")
    for coverage in reversed(events):
        if coverage["kind"] != "COVERAGE" or clock(coverage["received_at"]) > clock(
            event["received_at"]
        ):
            continue
        for identity in coverage["payload"].get("identities", []):
            if token and token in (identity.get("yes"), identity.get("no")):
                result: dict[str, Any] = identity
                return result
    return {"airport": inputs.get("airport", "UNKNOWN"), "station_match": False}


def reaction_timeline(
    events: list[dict[str, Any]], history: dict[str, Any]
) -> list[dict[str, Any]]:
    """Exploratory ±10m nominal/+5m receipt event window; never causal proof."""
    changes = [
        e
        for e in analysis_signals(events)
        if e["payload"].get("kind") == "ORDERBOOK_REPRICING_DETECTED"
    ]
    result = []
    for airport, day in history.items():
        for report in day["reports"]:
            nominal, receipt = (
                clock(report["observation_time_utc"]),
                clock(report["first_received_utc"]),
            )
            for event in changes:
                identity = signal_identity(event, events)
                created = clock(event["payload"]["created_at"])
                if (
                    identity["airport"] != airport
                    or identity.get("station_match") is not True
                    or identity.get("local_date")
                    != nominal.astimezone(ZoneInfo(STATIONS[airport].timezone)).date().isoformat()
                    or not nominal - timedelta(minutes=10)
                    <= created
                    <= receipt + timedelta(minutes=5)
                ):
                    continue
                inputs = event["payload"]["inputs"]
                result.append(
                    dict(
                        airport=airport,
                        report_identity=report["report_identity"],
                        report_type=report["report_type"],
                        correction=report["correction"],
                        metar_nominal=nominal.isoformat(),
                        metar_first_received=receipt.isoformat(),
                        repricing_signal_created=created.isoformat(),
                        token_id=inputs.get("token_id"),
                        condition_id=identity["condition_id"],
                        before_midpoint=inputs["before"]["midpoint"],
                        after_midpoint=inputs["after"]["midpoint"],
                        seconds_relative_to_metar_receipt=(created - receipt).total_seconds(),
                        direction="BEFORE_OUR_RECEIPT"
                        if created < receipt
                        else "AFTER_OUR_RECEIPT",
                        interpretation="EXPLORATORY_OBSERVED_MOVEMENT_NOT_CAUSAL_FIRST_MARKET_REACTION_OR_FILL",
                    )
                )
    return result


def outcome_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Count canonical confirmation signals; retain corrections separately in export."""
    signals = live_calibrated_signals(events)
    outcomes: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if event["kind"] == "OUTCOME":
            outcomes[event["payload"]["signal_id"]].append(event["payload"])
    counts: Counter[str] = Counter()
    cycles = set()
    matched_cycles = set()
    examples = []
    for event in signals:
        signal = event["payload"]
        inputs = signal["inputs"]
        cycles.add((inputs["airport"], inputs["target"]))
        candidates = [r for r in outcomes.get(event["id"], []) if not r.get("correction")]
        if not candidates:
            counts["pending_signals"] += 1
            continue
        initial = min(candidates, key=lambda row: clock(row["report_first_received"]))
        if initial.get("prospective_valid") is not True or clock(signal["created_at"]) >= clock(
            initial["target_first_received"]
        ):
            counts["excluded_after_first_receipt"] += 1
            continue
        counts["matched_initial_outcomes"] += 1
        matched_cycles.add((inputs["airport"], inputs["target"]))
        counts["correct"] += bool(initial["exact_match"])
        counts["persistence_correct"] += bool(initial["persistence_match"])
        counts["incremental_correct"] += bool(
            initial["exact_match"] and not initial["persistence_match"]
        )
        counts["incremental_harm"] += bool(
            initial["persistence_match"] and not initial["exact_match"]
        )
        counts[initial["experiment"] + "_matched"] += 1
        examples.append(dict(signal=signal, outcome=initial))
    return dict(
        validated_cal2_signals=len(signals),
        independent_target_cycles=len(cycles),
        matched_independent_target_cycles=len(matched_cycles),
        counts=dict(counts),
        examples=examples,
        interpretation="PRELIMINARY_CORRELATED_SIGNALS_NOT_INDEPENDENT_CYCLES",
    )


def valid_pair(sample: dict[str, Any]) -> bool:
    identity, books = sample.get("identity", {}), sample.get("books", {})
    if identity.get("station_match") is not True or identity.get("yes") == identity.get("no"):
        return False
    try:
        at = clock(sample["captured_at"])
        if identity["station"] != identity["airport"] or (
            at.astimezone(ZoneInfo(STATIONS[identity["airport"]].timezone)).date().isoformat()
            != identity["local_date"]
        ):
            return False
        connections = set()
        for side in ("yes", "no"):
            view = books[side]
            midpoint = float(view["midpoint"])
            if (
                view["status"] != "VALID"
                or not math.isfinite(midpoint)
                or not 0 < midpoint < 1
                or view["token_id"] != identity[side]
                or view["market"] != identity["condition_id"]
                or not 0 <= (at - clock(view["received_at"])).total_seconds() <= 10
                or not view["connection_id"]
            ):
                return False
            connections.add(view["connection_id"])
        return len(connections) == 1
    except (ValueError, TypeError, KeyError):
        return False


def window_bins(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Fixed five-minute bins; fresh endpoints AND observed continuity are required."""
    windows = []
    for event in events:
        if event["kind"] != "WINDOW":
            continue
        w = event["payload"]
        start = clock(w["start"])
        created = clock(w.get("created_at", event["received_at"]))
        forecast_received = clock(w.get("forecast_received", event["received_at"]))
        if max(created, forecast_received, clock(event["received_at"])) < start:
            windows.append(w)
    groups: dict[tuple[str, str, datetime], list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if event["kind"] != "BOOK_SAMPLE":
            continue
        sample = event["payload"]
        ident = sample["identity"]
        at = clock(sample["captured_at"])
        start = at.replace(minute=at.minute // 5 * 5, second=0, microsecond=0)
        groups[(ident["condition_id"], ident["local_date"], start)].append(sample)
    bins: list[dict[str, Any]] = []
    excluded: Counter[str] = Counter()
    for (condition, day, start), samples in sorted(groups.items()):
        samples.sort(key=lambda row: clock(row["captured_at"]))
        end = start + timedelta(minutes=5)
        if any(not valid_pair(row) for row in samples):
            excluded["MISSING_INVALID_STALE_OR_STATION_MISMATCH"] += 1
            continue
        times = [clock(row["captured_at"]) for row in samples]
        if (times[0] - start).total_seconds() > 10 or (end - times[-1]).total_seconds() > 10:
            excluded["INCOMPLETE_BIN_ENDPOINTS"] += 1
            continue
        connections = {row["books"]["yes"]["connection_id"] for row in samples}
        if len(connections) != 1 or any(
            (after - before).total_seconds() > 20
            for before, after in zip(times, times[1:], strict=False)
        ):
            excluded["DISCONTINUOUS_CAPTURE"] += 1
            continue
        ident = samples[0]["identity"]
        overlapping = [
            w
            for w in windows
            if w["airport"] == ident["airport"]
            and clock(w["start"]) < end
            and clock(w["end"]) > start
        ]
        forecast_overlap = any(
            w["kind"] in {"FORECAST_TRANSITION", "FORECAST_TMAX"} for w in overlapping
        )
        period = "WINDOW" if forecast_overlap else "OTHER_WINDOW" if overlapping else "CONTROL"
        for side in ("yes", "no"):
            before = float(samples[0]["books"][side]["midpoint"])
            after = float(samples[-1]["books"][side]["midpoint"])
            bins.append(
                dict(
                    airport=ident["airport"],
                    condition_id=condition,
                    token_id=ident[side],
                    side=side,
                    local_date=day,
                    start=start.isoformat(),
                    end=end.isoformat(),
                    period=period,
                    absolute_midpoint_change=abs(after - before),
                    material_change=abs(after - before) >= 0.02,
                    samples=len(samples),
                )
            )
    matched = []
    controls = [row for row in bins if row["period"] == "CONTROL"]
    used: set[tuple[str, str]] = set()
    for row in (item for item in bins if item["period"] == "WINDOW"):
        candidates = [
            c
            for c in controls
            if c["token_id"] == row["token_id"]
            and c["local_date"] == row["local_date"]
            and (c["token_id"], c["start"]) not in used
        ]
        if not candidates:
            continue
        control = min(
            candidates,
            key=lambda c: (
                abs((clock(c["start"]) - clock(row["start"])).total_seconds()),
                c["start"],
            ),
        )
        used.add((control["token_id"], control["start"]))
        matched.append(
            dict(
                **row,
                control_start=control["start"],
                control_change=control["absolute_midpoint_change"],
                matched_difference=row["absolute_midpoint_change"]
                - control["absolute_midpoint_change"],
            )
        )
    market_days = {(r["condition_id"], r["local_date"]) for r in matched}
    by_market: dict[str, set[str]] = defaultdict(set)
    for row in matched:
        by_market[row["condition_id"]].add(row["start"])
    sufficient = len(market_days) >= 20 and all(len(values) >= 10 for values in by_market.values())
    return dict(
        bins=bins,
        excluded_bins=dict(excluded),
        matched=matched,
        matched_market_days=len(market_days),
        matched_token_bin_pairs=len(matched),
        matched_condition_bin_pairs=len({(r["condition_id"], r["start"]) for r in matched}),
        status="DESCRIPTIVE_MATCHED_COMPARISON" if sufficient else "INSUFFICIENT_DATA",
        mean_matched_difference=mean(r["matched_difference"] for r in matched) if matched else None,
        caveat="YES/NO ticks are not independent events; no significance claimed",
    )


def causal_forecast(
    forecasts: list[dict[str, Any]], airport: str, event: datetime, decision: datetime
) -> dict[str, Any] | None:
    """Latest prior available forecast, previous hourly point; no interpolation."""
    candidates = []
    for forecast in forecasts:
        received = clock(forecast["first_received"])
        if forecast["airport"] != airport or received > decision:
            continue
        for point in forecast["points"]:
            valid = clock(point["valid_time"])
            if received < valid <= event and event - valid < timedelta(hours=1):
                candidates.append(dict(**point, forecast_received=forecast["first_received"]))
    return max(candidates, key=lambda p: clock(p["forecast_received"]), default=None)


def plot_report(
    output: Path, events: list[dict[str, Any]], history: dict[str, Any], airport: str
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    zone = ZoneInfo(STATIONS[airport].timezone)
    day = history[airport]
    fig, axes = plt.subplots(4, 1, figsize=(13, 12), sharex=True, constrained_layout=True)
    forecasts = [e["payload"] for e in events if e["kind"] == "FORECAST"]
    for forecast in [f for f in forecasts if f["airport"] == airport][-5:]:
        received = clock(forecast["first_received"])
        points = [
            p
            for p in forecast["points"]
            if received < clock(p["valid_time"])
            and clock(day["day_start"]) <= clock(p["valid_time"]) < clock(day["day_end_exclusive"])
        ]
        if points:
            axes[0].plot(
                [clock(p["valid_time"]) for p in points],
                [p["temperature_c"] for p in points],
                ".-",
                label="received " + received.astimezone(zone).strftime("%H:%M:%S%z"),
            )
    reports = [r for r in day["reports"] if r["temperature_c"] is not None]
    axes[1].plot(
        [clock(r["observation_time_utc"]) for r in reports],
        [r["temperature_c"] for r in reports],
        "o",
        color="black",
        label="stored METAR/SPECI (integer reference)",
    )
    sensor_ids = sorted({row["sensor_id"] for row in day["matched_examples"]})[:6]
    for sensor_id in sensor_ids:
        rows = [r for r in day["matched_examples"] if r["sensor_id"] == sensor_id]
        axes[2].plot(
            [clock(r["decision"]) for r in rows],
            [r["calibrated_temperature_c"] for r in rows],
            ".",
            label=sensor_id[-12:] + " retrospective CAL2",
        )
    live = [
        e for e in live_calibrated_signals(events) if e["payload"]["inputs"]["airport"] == airport
    ]
    live_sensor_ids = sorted({e["payload"]["inputs"]["sensor_id"] for e in live})[:6]
    for sensor_id in live_sensor_ids:
        group = [e["payload"] for e in live if e["payload"]["inputs"]["sensor_id"] == sensor_id]
        axes[2].plot(
            [clock(s["created_at"]) for s in group],
            [s["inputs"]["calibrated_temperature_c"] for s in group],
            "x",
            markersize=5,
            label=sensor_id[-12:] + " live CAL2 (min12)",
        )
    samples = [
        e["payload"]
        for e in events
        if e["kind"] == "BOOK_SAMPLE"
        and e["payload"]["identity"]["airport"] == airport
        and valid_pair(e["payload"])
    ]
    conditions = list(dict.fromkeys(s["identity"]["condition_id"] for s in samples))[:2]
    for condition in conditions:
        group = [s for s in samples if s["identity"]["condition_id"] == condition]
        for side in ("yes", "no"):
            axes[3].plot(
                [clock(s["captured_at"]) for s in group],
                [float(s["books"][side]["midpoint"]) for s in group],
                ".",
                markersize=2,
                label=group[0]["identity"]["slug"][-20:] + " " + side.upper(),
            )
    for ax, title in zip(
        axes,
        (
            "Hourly forecast snapshots — only valid times AFTER first receipt",
            "Actual official reports — nominal observation timestamps; COR/SPECI retained",
            "CAL2: dots retrospective T-1m; crosses actual live v1.1 signals (min12)",
            "Prospectively recorded valid YES/NO midpoint samples — NOT fills",
        ),
        strict=True,
    ):
        ax.set_title(title, fontsize=10, loc="left")
        ax.grid(alpha=0.2)
        handles, _ = ax.get_legend_handles_labels()
        if handles:
            ax.legend(fontsize=7, loc="best")
        else:
            ax.text(0.5, 0.5, "INSUFFICIENT DATA", transform=ax.transAxes, ha="center")
    for ax in axes[:3]:
        ax.set_ylabel("Temperature °C")
    axes[3].set_ylabel("Midpoint")
    axes[3].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M %z", tz=zone))  # type: ignore[no-untyped-call]
    axes[3].set_xlabel(f"{zone.key}; day {day['local_date']}; actual stored timestamps")
    axes[3].set_xlim(clock(day["day_start"]), clock(day["day_end_exclusive"]))
    fig.suptitle(f"{airport} — EXP-0013 observation-first evidence")
    fig.savefig(output, dpi=150)
    plt.close(fig)


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(weather_snapshot: Path, research_db: Path, output: Path) -> dict[str, Any]:
    events = read_research(research_db)
    if not events:
        raise ValueError("No research evidence; do not fabricate a report")
    cutoff = max(clock(e["received_at"]) for e in events)
    dataset = load_snapshot(weather_snapshot, cutoff)
    current = context_from_dataset(dataset, cutoff)
    history = history_from_dataset(dataset, cutoff)
    forecasts = [e["payload"] for e in events if e["kind"] == "FORECAST"]
    forecast_by_metar, forecast_comparisons = [], []
    for airport, day in history.items():
        for report in day["reports"]:
            point = causal_forecast(
                forecasts,
                airport,
                clock(report["observation_time_utc"]),
                clock(report["first_received_utc"]),
            )
            forecast_by_metar.append(
                dict(
                    airport=airport,
                    **report,
                    prior_forecast=point,
                    observed_minus_forecast_c=(
                        report["temperature_c"] - point["temperature_c"]
                        if point and report["temperature_c"] is not None
                        else None
                    ),
                )
            )
        for example in day["matched_examples"]:
            point = causal_forecast(
                forecasts, airport, clock(example["target_time"]), clock(example["decision"])
            )
            if point is not None:
                forecast_comparisons.append({**example, "prior_available_forecast": point})
    bins = window_bins(events)
    reactions = reaction_timeline(events, history)
    counts = dict(Counter(e["kind"] for e in events))
    signals = analysis_signals(events)
    excluded_signal_count = sum(e["kind"] == "SIGNAL" for e in events) - len(signals)
    outcomes = outcome_summary(events)
    samples = [e["payload"] for e in events if e["kind"] == "BOOK_SAMPLE"]
    valid_samples = [s for s in samples if valid_pair(s)]
    summary: dict[str, Any] = dict(
        cutoff=cutoff.isoformat(),
        sources={
            "weather": str(weather_snapshot.resolve()),
            "research": str(research_db.resolve()),
        },
        sha256={
            "weather": file_hash(weather_snapshot),
            "research": file_hash(research_db),
        },
        counts=counts,
        count_semantics="RAW_EVENT_INVENTORY_NOT_ANALYTICAL_SIGNAL_COUNT",
        analysis_signal_version="EXP0013-v1.1",
        excluded_prototype_signals=excluded_signal_count,
        analyzed_signal_count=len(signals),
        prospective_outcomes=outcomes,
        context=current,
        weather_history=history,
        bins=bins,
        forecast_vs_pws_matched_targets=forecast_comparisons,
        valid_book_pair_samples=len(valid_samples),
        all_book_samples=len(samples),
        actual_economic_fills=0,
        economic_status="NO_EXECUTION_RULE_FROZEN_NO_FILLS_INFERRED",
        weather_market_reactions=reactions,
    )
    output.mkdir(parents=True, exist_ok=True)
    export(output / "forecast_weather_metar_timeline.csv", forecast_by_metar)
    export(output / "forecast_window_bins.csv", bins["bins"])
    export(output / "forecast_matched_controls.csv", bins["matched"])
    export(output / "forecast_shadow_signals.csv", signals)
    export(output / "forecast_weather_market_leads.csv", reactions)
    export(output / "forecast_shadow_outcomes.csv", [e for e in events if e["kind"] == "OUTCOME"])
    export(output / "forecast_exclusion_audit.csv", [e for e in events if e["kind"] == "EXCLUSION"])
    export(
        output / "forecast_sensor_reconstruction.csv",
        [r for d in history.values() for r in d["matched_examples"]],
    )
    export(output / "forecast_observed_book_opportunities.csv", valid_samples)
    (output / "forecast_integrated_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    lines = [
        "# EXP-0013 — EPWA forecast / PWS / METAR / order-book evidence",
        "",
        "Prospective forecast/book capture is distinct from retrospective as-of weather reconstruction. No real orders or changes to either original monitor.",
        "",
        f"Research snapshot cutoff: **{cutoff.isoformat()}**. SHA256 weather `{summary['sha256']['weather']}`, research `{summary['sha256']['research']}`. Separate source snapshots are not assumed simultaneous.",
        "",
        "## Actual coverage",
        "",
        f"Signal analysis uses **EXP0013-v1.1 only**: {len(signals)} notifications; {excluded_signal_count} prototype/unsupported-version notifications excluded. Original v1 records remain immutable; separate EXCLUSION evidence is exported. Valid raw v1 forecast/book captures remain usable subject to exact station/time/depth filters. Startup METAR_CONTEXT_DISCOVERED is a context notification, not a new official arrival or prior-forecast success.",
        "",
        "|Airport|Today's METAR/SPECI/COR identities|Independent routine cycles|Fresh eligible PWS at cutoff|Forecast snapshots|",
        "|---|---:|---:|---:|---:|",
    ]
    for airport, day in history.items():
        lines.append(
            f"|{airport}|{len(day['reports'])}|{day['independent_routine_cycles']}|{current[airport]['diagnostics']['fresh_eligible_sensors']}|{sum(f['airport'] == airport for f in forecasts)}|"
        )
    lines += [
        "",
        f"Stored book samples: **{len(samples)}**, valid station-matched fresh binary pairs: **{len(valid_samples)}**. Frozen-window bin analysis: **{bins['status']}**, {len(bins['bins'])} valid token bins, {bins['matched_token_bin_pairs']} matched token-bin pairs / {bins['matched_condition_bin_pairs']} condition-bin pairs, {bins['matched_market_days']} market-days. Both outcomes are correlated; ticks are not independent trials.",
        "",
        f"Excluded bins: `{json.dumps(bins['excluded_bins'], sort_keys=True)}`. Conservative continuity additionally requires valid intervening samples, max20s sample gap, same connection, <=10s freshness and endpoint distance. Controls have no declared-window overlap; paired without reuse to nearest control in the same token/local day. Threshold:20market-days and10condition-bin pairs per market.",
        "",
        "## EPWA current sensor context",
        "",
        "|Sensor|Measurement UTC|First receipt UTC|Raw °C|CAL2 offset °C|Calibrated °C|Next integer|Status|",
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    for reading in current["EPWA"]["pws"]:
        lines.append(
            "|"
            + "|".join(
                str(reading[k])
                for k in (
                    "sensor_id",
                    "measurement_time",
                    "first_receive",
                    "raw_temperature_c",
                    "offset_c",
                    "calibrated_temperature_c",
                    "predicted_metar_integer",
                    "status",
                )
            )
            + "|"
        )
    if not current["EPWA"]["pws"]:
        lines.append("|INSUFFICIENT DATA||||||||")
    lines += [
        "",
        "## Latest actual EPWA reports",
        "",
        "|Nominal UTC|First received UTC|Temperature °C|Type|COR|",
        "|---|---|---:|---|---|",
    ]
    for report in history["EPWA"]["reports"][-12:]:
        lines.append(
            f"|{report['observation_time_utc']}|{report['first_received_utc']}|{report['temperature_c']}|{report['report_type']}|{report['correction']}|"
        )
    lines += [
        "",
        "## Preliminary sensor comparisons — retrospective only",
        "",
        "Fixed CAL2 rolling12hours/min12 independently received earlier routine cycles, T-1minute. Raw, calibrated and persistence accuracy share identical target samples. Quantized-reference midpoint offsets retain approximately±0.5C reference ambiguity. No retrospective ranking is activated.",
        "",
        "|Airport|Sensor|Cycles|CAL2 correct|Raw correct|Persistence correct|Incremental correct|Incremental harm|Net|",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for airport, day in history.items():
        for sensor in day["sensor_ranking"]:
            c = sensor["counts"]
            if c.get("eligible_cycles", 0):
                lines.append(
                    f"|{airport}|{sensor['sensor_id']}|{c.get('eligible_cycles', 0)}|{c.get('calibrated_correct', 0)}|{c.get('raw_correct_same_cycles', 0)}|{c.get('persistence_correct_same_cycles', 0)}|{c.get('incremental_correct', 0)}|{c.get('incremental_harm', 0)}|{sensor['net_improvement']}|"
                )
    lines += [
        "",
        "## Prospective signal examples",
        "",
        "The signal is an immutable observation notification, not a trade. Original weather receipt can precede signal creation; startup discoveries cannot become backdated signals. Unmatched outcomes/false alarms remain PENDING rather than fabricated successes.",
        "",
        "|Signal created UTC|Kind|Airport|Available evidence|",
        "|---|---|---|---|",
    ]
    for event in signals[-15:]:
        payload = event["payload"]
        inputs = payload.get("inputs", {})
        lines.append(
            f"|{payload.get('created_at', event['received_at'])}|{payload.get('kind')}|{signal_identity(event, events)['airport']}|{json.dumps(inputs, sort_keys=True)[:250].replace('|', '/')}…|"
        )
    lines += [
        "",
        "## Recorded weather / market chronology",
        "",
        "Exploratory event window: nominal−10minutes through first receipt+5minutes. These are threshold movements we recorded, not proof of the first market reaction or its cause. Exact station/local contract date and prior watchlist identity are required; future metadata is never used.",
        "",
        "|Airport|METAR nominal UTC|First METAR receipt UTC|Recorded repricing UTC|Midpoint before→after|Seconds relative to receipt|",
        "|---|---|---|---|---|---:|",
    ]
    for reaction in reactions[:8]:
        lines.append(
            f"|{reaction['airport']}|{reaction['metar_nominal']}|{reaction['metar_first_received']}|{reaction['repricing_signal_created']}|{reaction['before_midpoint']}→{reaction['after_midpoint']}|{reaction['seconds_relative_to_metar_receipt']:.3f}|"
        )
    if not reactions:
        lines.append("|INSUFFICIENT DATA||||||")
    lines += [
        "",
        "## Actual prospective CAL2 outcomes",
        "",
        f"Validated v1.1 confirmation signals: **{outcomes['validated_cal2_signals']}**, across **{outcomes['independent_target_cycles']} distinct airport/target cycles**, of which **{outcomes['matched_independent_target_cycles']} have matched initial outcomes**. Counts: `{json.dumps(outcomes['counts'], sort_keys=True)}`. Multiple sensors/receipts/checkpoints for the same target are correlated. A PWS_DISAGREES duplicate notification does not create another prediction count. Unsettled signals are PENDING; corrections remain separate records.",
        "EXP_A/B outcome labels below describe SIGNAL CREATION before/after nominal observation. They do not imply a newly received post-nominal measurement: original PWS receipt is retained separately. A post-nominal signal using an earlier receipt is not evidence of new post-observation data.",
        "",
        "|Airport|Signal created UTC|Target UTC|Predicted|Actual|Persistence correct|PWS correct|Lead seconds|Experiment|",
        "|---|---|---|---:|---:|---|---|---:|---|",
    ]
    for example in outcomes["examples"][-15:]:
        signal, outcome = example["signal"], example["outcome"]
        inputs = signal["inputs"]
        lines.append(
            f"|{inputs['airport']}|{signal['created_at']}|{inputs['target']}|{inputs['predicted_metar_integer']}|{outcome['observed_temperature_c']}|{outcome['persistence_match']}|{outcome['exact_match']}|{outcome['lead_seconds']}|{outcome['experiment']}|"
        )
    lines += [
        "",
        "## Eight research answers",
        "",
        "1. Open-Meteo explicit ICON model snapshots are implemented with actual first receipt and hourly valid times. Model metadata supplies candidate initialization/availability clocks; association with a returned forecast is not certified. Forecast publication/run remain NULL. See EXP0013_SOURCES.md; one provider capture does not prove it is fastest or most accurate.",
        "2. Weathercloud coordinate candidates are not verified hardware identities or authorized machine-readable measurements. UNKNOWN until owner-supported access is established. No scraping/upload endpoint used as a read API.",
        "3. Per-sensor matched counts above document exploratory T-1m agreement and failures. Multiple sensor search, short coverage and no frozen selected prospective winner prevent a robust most-consistent-sensor claim.",
        f"4. Window versus control price movement: **{bins['status']}**; {bins['matched_condition_bin_pairs']} matched condition-bin pairs/{bins['matched_market_days']} market-days. Mean token-pair difference `{bins['mean_matched_difference']}` is descriptive only.",
        "5. Repricing relative to first METAR receipt remains INSUFFICIENT_DATA until matched same-contract complete weather/book events exist. Nominal report time is not publication time; notification creation is not original receipt.",
        f"6. PWS beyond prior hourly forecast: {len(forecast_comparisons)} reconstructed sensor-target rows have a genuinely previously received forecast point. Multiple rows are not independent cycles. No incremental prospective edge is established.",
        f"7. {len(valid_samples)} fresh station-matched binary book samples were recorded. Displayed direct asks and complementary1-bid quotes are exported separately; matching priority, costs, settlement identity and depth constraints block guaranteed fill claims. **No simulated or real economic fills are inferred.**",
        "8. Freeze v1 observation rule: future-only forecast integer transition±10m, complete-day predicted hourly Tmax±60m, scheduled METAR±3m; retain outside controls. A fresh<=300s verified individual sensor may produce a research confirmation only after CAL2rolling12h/min12 and previous-receipt checks; target already received blocks prospective classification. Preserve exact inputs and all false alarms. No trading activation.",
        "",
        "## Limits and artifacts",
        "",
        "Clock offset remains UNKNOWN. Integer METAR daily maxima do not certify official settlement daily Tmax. LondonCity/EGLC contracts are excluded from Heathrow/EGLL station-matched comparisons. Forecast curves include only points valid after receipt; no historical forecast has been manufactured from today's run. CAL2 diagram dots are retrospective reconstructions; crosses are actual recorded v1.1 confirmation signals. Stored production-calibration context is not certified as CAL2 and is not plotted as such. Missing book samples and gaps remain missing.",
        "",
        "CSV files: forecast_weather_metar_timeline.csv, forecast_sensor_reconstruction.csv, forecast_shadow_signals.csv, forecast_shadow_outcomes.csv, forecast_exclusion_audit.csv, forecast_window_bins.csv, forecast_matched_controls.csv, forecast_observed_book_opportunities.csv. Full four-airport counts, exclusions and inputs: forecast_integrated_summary.json.",
        "",
        "![EPWA evidence](epwa_forecast_pws_metar_orderbook.png)",
    ]
    (output / "epwa_forecast_pws_metar_orderbook.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    plot_report(output / "epwa_forecast_pws_metar_orderbook.png", events, history, "EPWA")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weather-snapshot", type=Path, required=True)
    parser.add_argument("--research-db", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("reports/research"))
    args = parser.parse_args()
    result = run(args.weather_snapshot, args.research_db, args.output)
    print(
        json.dumps(
            {
                key: result[key]
                for key in ("cutoff", "counts", "valid_book_pair_samples", "all_book_samples")
            },
            indent=2,
        )
    )
