import json
import math
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

import polars as pl

from premetar.model import Observation, distance_to_boundary, icao_round_temperature
from premetar.sources import STATIONS
from premetar.store import report_identity


def read_observations(database: Path) -> list[Observation]:
    with sqlite3.connect(f"file:{database.resolve().as_posix()}?mode=ro", uri=True) as connection:
        return [
            Observation.model_validate_json(row[0])
            for row in connection.execute("SELECT data_json FROM observations ORDER BY id")
        ]


def eligible(obs: Observation) -> bool:
    return (
        obs.evidence_class == "REALTIME_CAPTURED"
        and obs.collector_receive_time is not None
        and obs.receive_monotonic_ns is not None
        and obs.request_start_monotonic_ns is not None
        and obs.run_id is not None
        and not obs.startup_censored
        and not obs.coverage_gap
    )


def lead_bucket(seconds: float) -> str:
    for boundary, label in (
        (30, "0-30s"),
        (60, "30-60s"),
        (120, "1-2min"),
        (180, "2-3min"),
        (300, "3-5min"),
        (600, "5-10min"),
    ):
        if seconds <= boundary:
            return label
    return ">10min"


def match_candidates(observations: list[Observation]) -> tuple[list[dict[str, Any]], Counter[str]]:
    reports: dict[tuple[str | None, str, str], list[Observation]] = defaultdict(list)
    for obs in observations:
        if obs.product_type == "METAR" and not obs.cor:
            reports[(obs.run_id, obs.station_icao, obs.event_time.isoformat())].append(obs)
    targets: dict[tuple[str | None, str], list[tuple[Observation, bool]]] = defaultdict(list)
    for (run, station, _), report_group in reports.items():
        # Different reports at the same nominal time are unresolved, never cherry-pick.
        ambiguous = len({report_identity(o) for o in report_group}) > 1
        first = min(
            report_group,
            key=lambda o: (
                o.receive_monotonic_ns if o.receive_monotonic_ns is not None else math.inf
            ),
        )
        targets[(run, station)].append((first, ambiguous))
    for group in targets.values():
        group.sort(key=lambda pair: pair[0].event_time)
    results: list[dict[str, Any]] = []
    exclusions: Counter[str] = Counter()
    for candidate in observations:
        if candidate.product_type not in ("DWD_10MIN", "KNMI_10MIN", "HF_OBS"):
            continue
        if not eligible(candidate):
            exclusions["candidate_censored_or_historical"] += 1
            continue
        group = targets.get((candidate.run_id, candidate.station_icao), [])
        next_targets = [pair for pair in group if pair[0].event_time >= candidate.event_time]
        if not next_targets:
            exclusions["next_report_not_yet_observed"] += 1
            continue
        target, ambiguous = next_targets[0]
        if ambiguous or not eligible(target):
            exclusions["target_ambiguous_or_censored"] += 1
            continue
        if target.event_time.minute not in STATIONS[target.station_icao].routine_minutes:
            exclusions["off_schedule_next_report"] += 1
            continue
        if (target.event_time - candidate.event_time).total_seconds() > 1800:
            exclusions["candidate_older_than_one_routine_interval"] += 1
            continue
        assert (
            target.receive_monotonic_ns is not None and candidate.receive_monotonic_ns is not None
        )
        assert target.request_start_monotonic_ns is not None
        lead = (target.receive_monotonic_ns - candidate.receive_monotonic_ns) / 1e9
        if lead <= 0:
            exclusions["candidate_not_received_before_target"] += 1
            continue
        if target.temperature_c is None or candidate.temperature_c is None:
            exclusions["missing_temperature"] += 1
            continue
        prediction = icao_round_temperature(candidate.temperature_c)
        actual = float(target.temperature_c)
        assert candidate.collector_receive_time is not None
        results.append(
            {
                "run_id": candidate.run_id,
                "station": candidate.station_icao,
                "source": candidate.source,
                "target_identity": report_identity(target),
                "report_time": target.event_time.isoformat(),
                "candidate_event_time": candidate.event_time.isoformat(),
                "candidate_receive_time": candidate.collector_receive_time.isoformat(),
                "candidate_receive_monotonic_ns": candidate.receive_monotonic_ns,
                "candidate_c": float(candidate.temperature_c),
                "predicted_metar_c": prediction,
                "actual_metar_c": actual,
                "distance_to_boundary_c": float(distance_to_boundary(candidate.temperature_c)),
                "exact": prediction == actual,
                "within_one": abs(prediction - actual) <= 1,
                "error_c": float(candidate.temperature_c) - actual,
                "actionable_lead_sec": lead,
                "target_request_start_lead_sec": (
                    target.request_start_monotonic_ns - candidate.receive_monotonic_ns
                )
                / 1e9,
                "candidate_delay_from_nominal_sec": (
                    candidate.collector_receive_time - target.event_time
                ).total_seconds(),
                "lead_bucket": lead_bucket(lead),
                "candidate_raw_sha256": candidate.raw_sha256,
                "target_raw_sha256": target.raw_sha256,
            }
        )
    # Latest input per target/source/bucket, independent of correctness.
    selected: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in results:
        key = (row["run_id"], row["target_identity"], row["source"], row["lead_bucket"])
        if (
            key not in selected
            or row["candidate_receive_monotonic_ns"]
            > selected[key]["candidate_receive_monotonic_ns"]
        ):
            selected[key] = row
    return list(selected.values()), exclusions


def quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = int(position)
    return ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * (
        position - lower
    )


def source_race(observations: list[Observation]) -> list[dict[str, Any]]:
    groups: dict[tuple[str | None, str], dict[str, Observation]] = defaultdict(dict)
    for obs in observations:
        if obs.product_type not in ("METAR", "SPECI") or not eligible(obs):
            continue
        key = (obs.run_id, report_identity(obs))
        previous = groups[key].get(obs.source)
        if previous is None or (obs.receive_monotonic_ns or 0) < (
            previous.receive_monotonic_ns or 0
        ):
            groups[key][obs.source] = obs
    rows = []
    for (_, ident), group in groups.items():
        if len(group) < 2:
            continue
        earliest = min(o.receive_monotonic_ns or 0 for o in group.values())
        for source, obs in group.items():
            rows.append(
                {
                    "station": obs.station_icao,
                    "product_type": obs.product_type,
                    "source": source,
                    "report_identity": ident,
                    "run_id": obs.run_id,
                    "win": obs.receive_monotonic_ns == earliest,
                    "delay_sec": ((obs.receive_monotonic_ns or 0) - earliest) / 1e9,
                }
            )
    return rows


def analyze(database: Path, output: Path) -> dict[str, Any]:
    observations = read_observations(database)
    pairs, exclusions = match_candidates(observations)
    race = source_race(observations)
    output.mkdir(parents=True, exist_ok=True)
    # Empty files still carry explicit schemas; they never contain synthetic examples.
    pair_frame = (
        pl.DataFrame(pairs, infer_schema_length=None)
        if pairs
        else pl.DataFrame(
            schema={
                "station": pl.String,
                "source": pl.String,
                "actionable_lead_sec": pl.Float64,
                "exact": pl.Boolean,
            }
        )
    )
    race_frame = (
        pl.DataFrame(race)
        if race
        else pl.DataFrame(
            schema={"station": pl.String, "source": pl.String, "delay_sec": pl.Float64}
        )
    )
    for name, frame in (("pairs", pair_frame), ("source-race", race_frame)):
        frame.write_csv(output / f"{name}.csv")
        frame.write_parquet(output / f"{name}.parquet")
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in pairs:
        groups[(row["station"], row["source"], row["lead_bucket"])].append(row)
    summary = []
    for (station, source, bucket), rows in sorted(groups.items()):
        leads = [r["actionable_lead_sec"] for r in rows]
        summary.append(
            {
                "station": station,
                "source": source,
                "lead_bucket": bucket,
                "N": len(rows),
                "exact_rate": mean(r["exact"] for r in rows),
                "within_one_rate": mean(r["within_one"] for r in rows),
                "MAE": mean(abs(r["error_c"]) for r in rows),
                "bias": mean(r["error_c"] for r in rows),
                "p10_lead": quantile(leads, 0.1),
                "median_lead": median(leads),
                "p90_lead": quantile(leads, 0.9),
                "nonoverlap_request_N": sum(r["target_request_start_lead_sec"] > 0 for r in rows),
            }
        )
    result: dict[str, Any] = {
        "conclusion": "INSUFFICIENT DATA — Milestone 1 baseline; validation design required before edge claims",
        "observations": len(observations),
        "paired_rows": len(pairs),
        "summary": summary,
        "exclusions": dict(exclusions),
        "source_race_paired_receipts": len(race),
        "evidence_classes": dict(Counter(o.evidence_class for o in observations)),
        "startup_censored_observations": sum(o.startup_censored for o in observations),
    }
    (output / "latest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    lines = [
        "# PRE-METAR EDGE REPORT",
        "",
        result["conclusion"],
        "",
        f"Normalized observations: {len(observations)}. Matched candidate/source/bucket rows: {len(pairs)}.",
        "",
        "| Station | Source | Lead | N | Exact | ±1 | MAE | Bias | p10 / p50 / p90 seconds | Nonoverlap request N |",
        "|---|---|---|---:|---:|---:|---:|---:|---|---:|",
    ]
    for item in summary:
        lines.append(
            f"| {item['station']} | {item['source']} | {item['lead_bucket']} | {item['N']} | {item['exact_rate']:.1%} | {item['within_one_rate']:.1%} | {item['MAE']:.3f} | {item['bias']:.3f} | {item['p10_lead']:.3f} / {item['median_lead']:.3f} / {item['p90_lead']:.3f} | {item['nonoverlap_request_N']} |"
        )
    lines += [
        "",
        "## Source race",
        "",
        "Only identical reports seen prospectively by at least two configured dissemination paths qualify. Providers can share upstream infrastructure; this is our receive race, not global publication order.",
        "",
        "| Station | Source | Races | Wins | Median delay seconds |",
        "|---|---|---:|---:|---:|",
    ]
    race_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in race:
        race_groups[(row["station"], row["source"])].append(row)
    for (station, source), rows in sorted(race_groups.items()):
        lines.append(
            f"| {station} | {source} | {len(rows)} | {sum(r['win'] for r in rows)} | {median(r['delay_sec'] for r in rows):.3f} |"
        )
    lines += [
        "",
        "## Exclusions",
        "",
        "```json",
        json.dumps(dict(exclusions), indent=2),
        "```",
        "",
        "Polling windows, startup censoring, outages and run boundaries limit latency interpretation. Unknown publication timestamps stay NULL. No probabilities, stable-prediction claims or market profits are inferred. SPECI receipts are retained; SPECI prediction and stability analysis are Milestone 2.",
        "",
    ]
    (output / "latest.md").write_text("\n".join(lines), encoding="utf-8")
    return result
