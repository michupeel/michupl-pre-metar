"""Bounded archived-run audit. Never writes collector DBs or changes live models.

Public historical availability is UNKNOWN: init+6h is a declared conservative
scenario, not a claimed publication timestamp. Replay can never promote a model.
"""

import argparse
import csv
import hashlib
import json
import ssl
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import truststore

from premetar.dashboard.calibration import evaluate
from premetar.pws.daily import metars
from premetar.research.forecast_monitor import WEATHER, backup_weather
from premetar.research.forecast_windows import parse_forecast
from premetar.research.trader_store import TraderStore, readonly_connection

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "data/research/epwa_calibration"
ENDPOINT = "https://single-runs-api.open-meteo.com/v1/forecast"
MODELS = ("icon_global", "icon_eu", "icon_d2")


def now() -> datetime:
    return datetime.now(UTC)


def collect(days: int = 7) -> dict[str, Any]:
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    store = TraderStore(DIRECTORY / "archive.sqlite3")
    existing = store.events("RAW", 1000)
    known = {json.dumps(e["payload"].get("params"), sort_keys=True): e for e in existing}
    runs = []
    support = {}
    errors = []
    anchor = now().replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        with httpx.Client(
            verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
            timeout=30,
            headers={"User-Agent": "michupl-pre-metar EPWA research archive audit"},
        ) as client:
            for model in MODELS:
                for offset in range(1, days + 1):
                    initialization = anchor - timedelta(days=offset)
                    params: dict[str, Any] = dict(
                        latitude=52.163,
                        longitude=20.961,
                        hourly="temperature_2m",
                        models=model,
                        run=initialization.strftime("%Y-%m-%dT%H:%M"),
                        timezone="UTC",
                        timeformat="unixtime",
                        temperature_unit="celsius",
                    )
                    key = json.dumps(params, sort_keys=True)
                    event = known.get(key)
                    if event is None:
                        started = now()
                        try:
                            response = client.get(ENDPOINT, params=params)
                        except httpx.HTTPError as exc:
                            errors.append(
                                dict(model=model, run=params["run"], error_class=type(exc).__name__)
                            )
                            break
                        received = now()
                        payload = dict(
                            url=ENDPOINT,
                            params=params,
                            start=started.isoformat(),
                            status=response.status_code,
                            body=response.text,
                            body_sha256=hashlib.sha256(response.content).hexdigest(),
                        )
                        store.append("RAW", payload, received, key)
                        event = dict(payload=payload, received_at=received.isoformat())
                        time.sleep(0.5)
                    raw = event["payload"]
                    if raw["status"] != 200:
                        reason = json.loads(raw["body"]).get("reason", "HTTP_ERROR")
                        support[model] = dict(
                            status="UNAVAILABLE_AT_REQUESTED_EPWA_COORDINATES"
                            if raw["status"] == 400 and "location" in reason.lower()
                            else "BLOCKED",
                            http_status=raw["status"],
                            reason=reason,
                        )
                        break
                    decoded = json.loads(raw["body"])
                    received = datetime.fromisoformat(event["received_at"].replace("Z", "+00:00"))
                    normalized = parse_forecast(decoded, "EPWA", received)
                    run_id = hashlib.sha256(key.encode()).hexdigest()
                    run = dict(
                        run_id=run_id,
                        model=model,
                        initialization_time=initialization.isoformat(),
                        first_received=received.isoformat(),
                        availability_time=None,
                        availability_class="APPROXIMATE_REPLAY",
                        decision_time=(initialization + timedelta(hours=6)).isoformat(),
                        decision_assumption="INIT_PLUS_6H_SCENARIO_NOT_VERIFIED_ORIGINAL_AVAILABILITY",
                        points=normalized["points"],
                        requested_coordinates=[52.163, 20.961],
                        returned_coordinates=[decoded.get("latitude"), decoded.get("longitude")],
                        raw_payload_hash=raw["body_sha256"],
                    )
                    store.append("ARCHIVED_RUN", run, received, run_id)
                    runs.append(run)
                    support[model] = dict(
                        status="ARCHIVED_RUNS_VERIFIED_COORDINATE_RESPONSE",
                        runs=len([r for r in runs if r["model"] == model]),
                        first_received=received.isoformat(),
                        returned_coordinates=run["returned_coordinates"],
                        publication_time=None,
                    )
        snapshot = DIRECTORY / f"weather_{now():%Y%m%dT%H%M%S}.sqlite3"
        provenance = backup_weather(WEATHER, snapshot)
        conn = readonly_connection(snapshot)
        try:
            references = metars(
                conn, "EPWA", anchor - timedelta(days=days + 2), now(), ZoneInfo("Europe/Warsaw")
            )
            # Exclude initial-cache/coverage-censored references using original
            # first-receipt evidence across configured providers.
            for ref in references:
                censor = conn.execute(
                    "SELECT o.startup_censored,o.coverage_gap FROM observations o JOIN report_receipts rr ON rr.observation_id=o.id WHERE o.identity=? ORDER BY julianday(rr.collector_receive_time) LIMIT 1",
                    (ref["report_identity"],),
                ).fetchone()
                ref["startup_censored"] = bool(censor[0]) if censor else True
                ref["coverage_gap"] = bool(censor[1]) if censor else True
                ref["quantized"] = True
            references = [
                r for r in references if not r["startup_censored"] and not r["coverage_gap"]
            ]
        finally:
            conn.close()
        # A partial routine-integer maximum is NEVER a final daily target.
        report = evaluate(runs, references, [])
        report.update(
            created_at=now().isoformat(),
            published_at=now().isoformat(),
            model_support=support,
            source_snapshot=provenance,
            source=ENDPOINT,
            scope="ARCHIVED_INITIALIZED_RUNS_APPROXIMATE_AVAILABILITY_ONLY",
            runs_requested=days,
            actual_runs=len(runs),
            errors=errors,
            final_settlement_targets=0,
            final_target_reason="NO_AUDITED_POST_DEADLINE_RESOLUTION_SOURCE_VIEW_OR_VERIFIED_FINAL_DAILY_REFERENCE",
            runtime_promotion=False,
        )
        path = DIRECTORY / "latest.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
        tmp.replace(path)
        output = ROOT / "reports/research"
        output.mkdir(exist_ok=True, parents=True)
        (output / "epwa_forecast_calibration.json").write_text(
            json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
        )
        (output / "epwa_forecast_calibration_summary.json").write_text(
            json.dumps({k: v for k, v in report.items() if k != "records"}, indent=2, default=str)
            + "\n",
            encoding="utf-8",
        )
        records = report.get("records", [])
        with (output / "epwa_forecast_calibration.csv").open(
            "w", newline="", encoding="utf-8"
        ) as stream:
            writer = csv.DictWriter(
                stream, fieldnames=sorted({k for r in records for k in r}) or ["status"]
            )
            writer.writeheader()
            for r in records:
                writer.writerow(
                    {
                        k: json.dumps(v, default=str) if isinstance(v, (list, dict)) else v
                        for k, v in r.items()
                    }
                )
        text = (
            "# EPWA — audited forward-only forecast calibration\n\n"
            + "No model promotion. Archive replay is APPROXIMATE: requested initialization is explicit, original API publication/availability is unknown. Decision scenario init+6h is not an observed public receipt. Prospective inputs remain separate.\n\n"
        )
        text += (
            "## Model support — actual requests\n\n"
            + "\n".join(f"- {model}: {json.dumps(value)}" for model, value in support.items())
            + "\n\n"
        )
        text += (
            "## Cross-model comparison on identical target/decision pairs\n\n"
            + "Model | Method | Matched pairs | Independent targets | Days | Interval MAE C\n"
            + "--- | --- | ---: | ---: | ---: | ---:\n"
        )
        for comparison in report.get("matched_models", []):
            for model, metrics in comparison.get("model_metrics", {}).items():
                text += f"{model} | {comparison['method']} | {metrics['N']} | {metrics['independent_targets']} | {metrics['days']} | {metrics['interval_mae']:.6f}\n"
        text += "\nThese hourly approximate-replay pairs are not independent daily Tmax outcomes. No final daily targets or validated Tmax error exist.\n\n"
        text += (
            "## Matched walk-forward hourly results\n\n```json\n"
            + json.dumps(report.get("summary"), indent=2, default=str)
            + "\n```\n\n"
        )
        text += (
            "## Daily Tmax — separate target\n\n```json\n"
            + json.dumps(report.get("daily"), indent=2, default=str)
            + "\n```\n\n"
        )
        text += "CALIBRATION PENDING: no verified final settlement targets. Current Warsaw contract rules prefer routine METAR precise T-group, else body integer; exclude SPECI and use the station local date and frozen corrections cutoff. This is not permission to substitute our incomplete routine-integer maximum as final truth. No sample/MAE/Tmax timing confidence is fabricated.\n\n"
        text += "Sources: [Single Runs](https://open-meteo.com/en/docs/single-runs-api), [model clocks](https://open-meteo.com/en/docs/model-updates). Raw responses precede normalization in ignored archive.sqlite3. Every run/receipt/hash is retained.\n"
        (output / "epwa_forecast_calibration.md").write_text(text, encoding="utf-8")
        return report
    finally:
        store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    if not 1 <= args.days <= 14:
        parser.error("Use1..14days bounded audit")
    result = collect(args.days)
    print(
        json.dumps(
            {k: result.get(k) for k in ("model_support", "actual_runs", "daily", "summary")},
            indent=2,
            default=str,
        )
    )
