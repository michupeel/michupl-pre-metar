"""Read-only operational status and matched-target prospective evaluation."""

import csv
import json
import math
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

from premetar.continuous.polling import provider_state
from premetar.continuous.statistics import day_block_interval, lead_summary
from premetar.model import utc_now
from premetar.pws.integrity import prediction_issues
from premetar.pws.repository import rows, selected


def connect(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)


def snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    from premetar.pws.models import QCConfig
    from premetar.pws.quality import eligible
    from premetar.sources import STATIONS, next_report

    at = utc_now()
    run_rows = rows(conn, "SELECT * FROM runs ORDER BY started_at DESC LIMIT 1")
    health_rows = rows(conn, "SELECT * FROM continuous_health ORDER BY updated_at DESC LIMIT 1")
    run = run_rows[0] if run_rows else None
    manifest = json.loads(run["manifest_json"]) if run else {}
    clock = manifest.get("clock", {})
    from premetar.clock_audit import cached_clock

    clock["current_verification"] = cached_clock()
    qc = QCConfig.model_validate(manifest.get("continuous_config", {}).get("qc", {}))
    if run:
        run = {k: v for k, v in run.items() if k != "manifest_json"}
        run["heartbeat_age_seconds"] = (
            at - datetime.fromisoformat(run["heartbeat"])
        ).total_seconds()
        run["state"] = (
            "RUNNING"
            if run["ended_at"] is None and run["heartbeat_age_seconds"] < 30
            else "STOPPED_OR_STALE"
        )
    cohort = rows(conn, "SELECT * FROM continuous_cohort")
    active: set[str] = set()
    inventory = []
    for item in cohort:
        latest = rows(
            conn,
            """SELECT o.* FROM pws_observations o JOIN pws_sensors s USING(sensor_id)
            WHERE s.station_id=? ORDER BY o.first_receive_time DESC LIMIT 64""",
            (item["station_id"],),
        )
        candidates = [
            {
                **r,
                **json.loads(r["data_json"]),
                "station_id": item["station_id"],
                "provider": item["station_id"].split(":", 1)[0],
            }
            for r in latest
        ]
        good = [r for r in candidates if eligible(r, at, qc)]
        monitoring = selected(conn, item["station_id"], item["airport"], at)
        if good and monitoring:
            active.add(item["station_id"])
        event_times = [
            datetime.fromisoformat(r["observation_time"])
            for r in candidates
            if r["observation_time"]
        ]
        ages = [
            (
                datetime.fromisoformat(r["first_receive_time"])
                - datetime.fromisoformat(r["observation_time"])
            ).total_seconds()
            for r in candidates
            if r["observation_time"]
        ]
        proxy = [str(r["provider_timestamp"]) for r in candidates if r.get("provider_timestamp")]
        inventory.append(
            dict(
                airport=item["airport"],
                station_id=item["station_id"],
                tier="DISCOVERY_CANDIDATE",
                monitoring_selected=monitoring,
                usable_now=bool(good) and monitoring,
                latest_measurement_time=max(event_times).isoformat() if event_times else None,
                latest_provider_ingest_time=max(proxy) if proxy else None,
                latest_receive_time=candidates[0]["first_receive_time"] if candidates else None,
                median_observation_age=median(ages) if ages else None,
                event_time_semantics="SENSOR_MEASUREMENT"
                if event_times
                else "UNKNOWN_MEASUREMENT_SERVER_INGEST_PROXY"
                if proxy
                else "UNKNOWN",
                reason=item["reason"],
            )
        )
    airports = []
    for airport, station in STATIONS.items():
        items = [r for r in inventory if r["airport"] == airport]
        last = conn.execute(
            "SELECT max(event_time) FROM observations WHERE station_icao=? AND product_type='METAR'",
            (airport,),
        ).fetchone()[0]
        pending = conn.execute(
            "SELECT count(*) FROM pws_predictions p WHERE airport_icao=? AND NOT EXISTS(SELECT 1 FROM continuous_settlements s WHERE s.prediction_id=p.id)",
            (airport,),
        ).fetchone()[0]
        airports.append(
            dict(
                airport=airport,
                next_metar=next_report(station, at).isoformat(),
                countdown_seconds=(next_report(station, at) - at).total_seconds(),
                selected=sum(r["monitoring_selected"] for r in items),
                active=sum(r["usable_now"] for r in items),
                latest_measurement_time=max(
                    (r["latest_measurement_time"] for r in items if r["latest_measurement_time"]),
                    default=None,
                ),
                latest_provider_ingest_time=max(
                    (
                        r["latest_provider_ingest_time"]
                        for r in items
                        if r["latest_provider_ingest_time"]
                    ),
                    default=None,
                ),
                last_metar=last,
                pending_predictions=pending,
            )
        )
    providers = []
    for provider in ("opensensemap", "sensor_community"):
        aggregate = rows(
            conn,
            "SELECT count(*) polls,sum(error_class IS NOT NULL) failures FROM continuous_polls WHERE provider=?",
            (provider,),
        )[0]
        last = rows(
            conn,
            "SELECT * FROM continuous_polls WHERE provider=? ORDER BY id DESC LIMIT 1",
            (provider,),
        )
        new = conn.execute(
            "SELECT count(*) FROM pws_observations o JOIN pws_sensors s USING(sensor_id) JOIN pws_stations st USING(station_id) WHERE st.provider=?",
            (provider,),
        ).fetchone()[0]
        arrivals = conn.execute(
            "SELECT count(*) FROM pws_arrivals a JOIN pws_observations o ON o.id=a.observation_id JOIN pws_sensors s USING(sensor_id) JOIN pws_stations st USING(station_id) WHERE st.provider=?",
            (provider,),
        ).fetchone()[0]
        relevant = [r for r in inventory if r["station_id"].startswith(provider + ":")]
        fresh = any(r["usable_now"] for r in relevant)
        providers.append(
            dict(
                provider=provider,
                state=provider_state(
                    disabled=bool(last and last[0]["state"] == "DISABLED"),
                    auth_failed=bool(last and last[0]["state"] == "AUTH_FAILED"),
                    rate_limited=bool(last and last[0]["state"] == "RATE_LIMITED"),
                    last_data_age=0 if fresh else None,
                    failures=int(bool(last and last[0]["error_class"])),
                ),
                polls=aggregate["polls"],
                requests=conn.execute(
                    "SELECT count(*) FROM raw_payloads WHERE source=?", ("pws_" + provider,)
                ).fetchone()[0],
                new=new,
                duplicates=max(0, arrivals - new),
                failures=aggregate["failures"] or 0,
                median_observation_age=median(
                    [
                        r["median_observation_age"]
                        for r in relevant
                        if r["median_observation_age"] is not None
                    ]
                )
                if any(r["median_observation_age"] is not None for r in relevant)
                else None,
            )
        )
    eligibility = []
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='pws_observation_integrity'"
    ).fetchone():
        eligibility = rows(
            conn,
            """SELECT st.provider,i.status,count(*) records FROM pws_observation_integrity i
            JOIN pws_observations o ON o.id=i.observation_id JOIN pws_sensors s USING(sensor_id)
            JOIN pws_stations st USING(station_id) WHERE i.policy_version=? GROUP BY st.provider,i.status""",
            (manifest.get("timestamp_policy", {}).get("version", "strict-measurement-time-1.0"),),
        )
    official = rows(conn, "SELECT * FROM source_health ORDER BY source")
    if run:
        official = [r for r in official if r["run_id"] == run["id"]]
    return dict(
        utc=at.isoformat(),
        run=run,
        clock_synchronization="VERIFIED" if clock.get("synchronization_confirmed") else "UNKNOWN",
        clock_verification=clock["current_verification"],
        clock=clock,
        health={**health_rows[0], "data": json.loads(health_rows[0]["data_json"])}
        if health_rows
        else None,
        airports=airports,
        stations=inventory,
        providers=providers,
        official_providers=official,
        observation_count_definition="NORMALIZED_RECORDS_INCLUDING_QUARANTINED_NOT_VALID_MEASUREMENTS",
        measurement_eligibility_at_receipt=eligibility,
        observations=conn.execute("SELECT count(*) FROM pws_observations").fetchone()[0],
        predictions=conn.execute("SELECT count(*) FROM pws_predictions").fetchone()[0],
        settled=conn.execute(
            "SELECT count(DISTINCT prediction_id) FROM continuous_settlements"
        ).fetchone()[0],
        recent_errors=rows(
            conn, "SELECT source,at,error_class FROM errors ORDER BY id DESC LIMIT 10"
        ),
    )


def csv_write(path: Path, data: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        if not data:
            f.write("status\nINSUFFICIENT DATA\n")
            return
        fields = list(dict.fromkeys(k for r in data for k in r))
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(data)


def report(conn: sqlite3.Connection, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    state = snapshot(conn)
    # Initial and latest correction are separate views; original settlements retained.
    raw = rows(
        conn,
        "SELECT s.*,p.airport_icao,p.target_time,p.data_json forecast FROM continuous_settlements s JOIN pws_predictions p ON p.id=s.prediction_id ORDER BY s.reference_first_seen,s.id",
    )
    latest: dict[str, dict[str, Any]] = {}
    initial: dict[str, dict[str, Any]] = {}
    for r in raw:
        initial.setdefault(r["prediction_id"], r)
        latest[r["prediction_id"]] = r
    csv_write(
        output / "latest_valid_settlements.csv",
        [
            {k: v for k, v in r.items() if k not in ("data_json", "forecast")}
            for r in latest.values()
        ],
    )
    outcomes = []
    for r in initial.values():
        f = json.loads(r["forecast"])
        d = json.loads(r["data_json"])
        if not d["valid_prospective"] or prediction_issues(conn, f):
            continue
        outcomes.append(
            dict(
                airport=r["airport_icao"],
                target=r["target_time"],
                checkpoint=f.get("checkpoint") or "manual",
                model=f["method"],
                prediction_id=r["prediction_id"],
                error=d["integer_error"],
                interval_error=d["continuous_interval_error"],
                lead_seconds=d["lead_seconds"],
                reference_censored=d["startup_censored"] or d["coverage_gap"],
                experiment=d["experiment_class"],
                created=f["created_at"],
                integer=f["integer_temperature"],
                official=d["official_integer"],
            )
        )
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in outcomes:
        groups[(r["airport"], r["checkpoint"], r["model"], r["experiment"])].append(r)
    metrics = []
    for (airport, checkpoint, model, experiment), items in groups.items():
        errors = [r["error"] for r in items]
        day_values = [(datetime.fromisoformat(r["target"]).date().isoformat(), r) for r in items]
        enough = len(items) >= 100 and len({day for day, _ in day_values}) >= 7
        confidence = {
            "integer_MAE": day_block_interval(
                [(day, float(abs(row["error"]))) for day, row in day_values]
            ),
            "exact_integer_accuracy": day_block_interval(
                [(day, float(row["error"] == 0)) for day, row in day_values]
            ),
            "bias": day_block_interval([(day, float(row["error"])) for day, row in day_values]),
        }
        attempts = (
            conn.execute(
                "SELECT count(*) FROM continuous_checkpoints WHERE airport=? AND model=? AND checkpoint=? AND reason IS NOT 'STARTUP_ELAPSED' AND julianday(target)<=julianday('now')",
                (airport, model, int(checkpoint[2:-1])),
            ).fetchone()[0]
            if checkpoint.startswith("T-")
            else len(items)
        )
        metrics.append(
            dict(
                airport=airport,
                checkpoint=checkpoint,
                model=model,
                experiment=experiment,
                N=len(items),
                exact_integer_accuracy=mean(e == 0 for e in errors),
                within_1c_accuracy=mean(abs(e) <= 1 for e in errors),
                MAE=mean(abs(e) for e in errors),
                RMSE=math.sqrt(mean(e * e for e in errors)),
                bias=mean(errors),
                interval_aware_MAE=mean(r["interval_error"] for r in items),
                coverage=len(items) / attempts if attempts else None,
                missing_prediction_rate=conn.execute(
                    "SELECT count(*) FROM continuous_checkpoints WHERE airport=? AND model=? AND checkpoint=? AND status!='GENERATED' AND reason IS NOT 'STARTUP_ELAPSED' AND julianday(target)<=julianday('now')",
                    (airport, model, int(checkpoint[2:-1])),
                ).fetchone()[0]
                / attempts
                if attempts and checkpoint.startswith("T-")
                else None,
                status="DESCRIPTIVE — NOT CONFIRMATORY"
                if enough
                else "PRELIMINARY — INSUFFICIENT DATA",
                evaluation_days=len({day for day, _ in day_values}),
                uncertainty=json.dumps(confidence),
            )
        )
    matched = []
    # Pair each candidate with persistence on exactly identical target/checkpoint samples.
    lookup = {(r["airport"], r["target"], r["checkpoint"], r["model"]): r for r in outcomes}
    for r in outcomes:
        b = lookup.get((r["airport"], r["target"], r["checkpoint"], "previous_metar"))
        if b and r["model"] != "previous_metar":
            matched.append(
                dict(
                    airport=r["airport"],
                    target=r["target"],
                    checkpoint=r["checkpoint"],
                    model=r["model"],
                    model_abs_error=abs(r["error"]),
                    baseline_abs_error=abs(b["error"]),
                    improvement=abs(b["error"]) - abs(r["error"]),
                )
            )
    comparison_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in matched:
        comparison_groups[(r["airport"], r["checkpoint"], r["model"])].append(r)
    comparisons = []
    for (airport, checkpoint, model), items in comparison_groups.items():
        interval = day_block_interval(
            [
                (datetime.fromisoformat(r["target"]).date().isoformat(), r["improvement"])
                for r in items
            ]
        )
        comparisons.append(
            dict(
                airport=airport,
                checkpoint=checkpoint,
                model=model,
                matched_targets=len(items),
                mean_MAE_improvement=mean(r["improvement"] for r in items),
                **interval,
            )
        )
    csv_write(output / "matched_comparison_uncertainty.csv", comparisons)
    stability = []
    trajectories: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in outcomes:
        trajectories[(r["airport"], r["target"], r["model"])].append(r)
    for (airport, target, model), items in trajectories.items():
        items.sort(key=lambda r: datetime.fromisoformat(r["created"]))
        correct = [i for i, r in enumerate(items) if r["integer"] == r["official"]]
        stable = next(
            (i for i in correct if all(r["integer"] == r["official"] for r in items[i:])), None
        )
        stability.append(
            dict(
                airport=airport,
                target=target,
                model=model,
                observed_checkpoints=len(items),
                first_correct_checkpoint=items[correct[0]]["checkpoint"] if correct else None,
                last_incorrect_checkpoint=next(
                    (r["checkpoint"] for r in reversed(items) if r["integer"] != r["official"]),
                    None,
                ),
                first_stable_correct_checkpoint=items[stable]["checkpoint"]
                if stable is not None
                else None,
                revisions=sum(
                    a["integer"] != b["integer"] for a, b in zip(items, items[1:], strict=False)
                ),
                stability_seconds=(
                    datetime.fromisoformat(items[-1]["created"])
                    - datetime.fromisoformat(items[stable]["created"])
                ).total_seconds()
                if stable is not None
                else None,
                definition="Correct through all later observed checkpoints; missing checkpoints are not evidence of stability",
            )
        )
    csv_write(output / "prediction_metrics.csv", metrics)
    csv_write(output / "matched_baseline_comparison.csv", matched)
    csv_write(output / "prediction_stability.csv", stability)
    csv_write(output / "provider_freshness.csv", state["providers"])
    station_rows = []
    for station in state["stations"]:
        qc_rows = rows(
            conn,
            "SELECT created_at,data_json FROM pws_quality_results WHERE station_id=? AND airport_icao=? ORDER BY created_at DESC,id DESC LIMIT 1",
            (station["station_id"], station["airport"]),
        )
        qc = json.loads(qc_rows[0]["data_json"]) if qc_rows else {}
        sensors = list(qc.get("sensors", {}).values())
        metadata = rows(
            conn,
            "SELECT distance_km FROM pws_airport_stations WHERE station_id=? AND airport_icao=?",
            (station["station_id"], station["airport"]),
        )
        station_rows.append(
            {
                **station,
                "distance_km": metadata[0]["distance_km"] if metadata else None,
                "qc_created_at": qc_rows[0]["created_at"] if qc_rows else None,
                "median_update_interval": qc.get("median_update_interval"),
                "availability": qc.get("availability"),
                "p90_update_interval": max(
                    (
                        r["p90_update_interval"]
                        for r in sensors
                        if r.get("p90_update_interval") is not None
                    ),
                    default=None,
                ),
                "longest_gap": max(
                    (r["longest_gap"] for r in sensors if r.get("longest_gap") is not None),
                    default=None,
                ),
                "missing_intervals": sum(
                    r["missing_intervals"]
                    for r in sensors
                    if r.get("missing_intervals") is not None
                )
                if any(r.get("missing_intervals") is not None for r in sensors)
                else None,
                "quality_flags": json.dumps(qc.get("flags", [])),
                "score": qc.get("score"),
                "status": qc.get("status", "UNVERIFIED"),
            }
        )
    csv_write(output / "station_coverage.csv", station_rows)
    csv_write(output / "airport_coverage.csv", state["airports"])
    csv_write(
        output / "metar_latency.csv",
        rows(
            conn,
            "SELECT source,station_icao,event_time,collector_receive_time,startup_censored,coverage_gap FROM observations WHERE product_type IN ('METAR','SPECI') ORDER BY collector_receive_time",
        ),
    )
    csv_write(
        output / "initial_settlements.csv",
        [
            {k: v for k, v in r.items() if k not in ("data_json", "forecast")}
            for r in initial.values()
        ],
    )
    csv_write(output / "prediction_outcomes.csv", outcomes)
    summary_status = (
        "DESCRIPTIVE RESULTS — SEE PER-METHOD COVERAGE"
        if any(m["status"] == "DESCRIPTIVE — NOT CONFIRMATORY" for m in metrics)
        else "PRELIMINARY — INSUFFICIENT DATA"
    )
    body = (
        "# Continuous observation experiment\n\nOBSERVED\n\n"
        + json.dumps(state, indent=2)
        + "\n\n"
        + summary_status
        + "\n\nNo validated information edge. Lead is relative to our configured reference collectors, with unverified clock offset. Sensor.Community server-ingest clocks are not measurement clocks. Post-observation signals are disabled. Missing checkpoints are retained. Descriptive day-block intervals require 100 targets across 7 UTC days. Dependence across days remains unmodelled.\n"
    )
    for name in ("collection_health.md", "experiment_summary.md"):
        (output / name).write_text(body, encoding="utf-8")
    (output / "prediction_accuracy.md").write_text(
        "# Prediction accuracy\n\n"
        + summary_status
        + "\n\n"
        + json.dumps(metrics, indent=2)
        + "\n\nCompare only matched_baseline_comparison.csv; coverage includes unresolved targets and is provisional.\n",
        encoding="utf-8",
    )
    leads = [
        r["lead_seconds"]
        for r in outcomes
        if r["lead_seconds"] is not None and not r["reference_censored"]
    ]
    lead_metrics = []
    for (airport, checkpoint, model, experiment), items in groups.items():
        eligible = [
            r for r in items if r["lead_seconds"] is not None and not r["reference_censored"]
        ]
        correct_leads = [float(r["lead_seconds"]) for r in eligible if r["error"] == 0]
        lead_metrics.append(
            dict(
                airport=airport,
                checkpoint=checkpoint,
                model=model,
                experiment=experiment,
                distinct_targets=len({r["target"] for r in eligible}),
                correct_prediction_lead=json.dumps(lead_summary(correct_leads)),
                status="CLOCK_UNVERIFIED_RELATIVE_TO_CONFIGURED_COLLECTORS",
                **lead_summary([r["lead_seconds"] for r in eligible]),
            )
        )
    csv_write(output / "information_lead.csv", lead_metrics)
    (output / "information_lead.md").write_text(
        "# Information availability\n\nUNVERIFIED CLOCK — NOT A MEASURED GLOBAL INFORMATION EDGE\n\n"
        + f"Local-clock positive lead summary: {lead_summary(leads)}.\n\nPRE_OBSERVATION only. EXP-B post-observation signals are disabled. First receipt is our collector's first receipt, not proof of global publication.\n",
        encoding="utf-8",
    )
    return state
