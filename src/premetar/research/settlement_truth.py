"""Raw-first historical EPWA settlement audit; never a live prediction oracle."""

import argparse
import csv
import hashlib
import json
import math
import os
import re
import ssl
import time
from datetime import UTC, date, datetime, timedelta
from datetime import time as day_time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import httpx
import truststore

from premetar.research.battle_store import BattleStore
from premetar.research.d1_forecasts import MODEL_SPECS
from premetar.research.d1_monitor import MONTHS, ROOT, airport_coordinates
from premetar.research.settlement_calibration import evaluate, export, load_archived_runs
from premetar.research.settlement_rules import (
    local_day_bounds,
    parse_rules,
    parse_temperature,
    reconstruct_day,
    resolved_market,
)

DIRECTORY = ROOT / "data/research/epwa_settlement"
OUTPUT = ROOT / "reports/research/epwa_settlement"
STATIC = ROOT / "src/premetar/dashboard/static/settlement_history.json"


def now() -> datetime:
    return datetime.now(UTC)


def clock(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timezone required")
    return result.astimezone(UTC)


def canonical(url: str, params: dict[str, Any] | None = None) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.hostname
        not in {"gamma-api.polymarket.com", "aviationweather.gov", "single-runs-api.open-meteo.com"}
    ):
        raise ValueError("Only public Gamma/AWC HTTPS sources permitted")
    if parsed.hostname == "aviationweather.gov" and parsed.path != "/api/data/metar":
        raise ValueError("Only documented AWC METAR endpoint")
    if parsed.hostname == "single-runs-api.open-meteo.com" and parsed.path != "/v1/forecast":
        raise ValueError("Only documented individual-run endpoint")
    query = dict(parse_qsl(parsed.query))
    query.update(params or {})
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(sorted(query.items())), "")
    )


class Evidence:
    """Immutable content addressed bodies; idempotent normalized audit revisions."""

    def __init__(self, directory: Path = DIRECTORY) -> None:
        self.directory = directory
        self.raw = directory / "raw"
        self.raw.mkdir(parents=True, exist_ok=True)
        self.store = BattleStore(directory / "journal")
        self.state, _ = self.store.restore()
        self.state.setdefault("captures", {})
        self.state.setdefault("targets", {})
        self.last_request = 0.0

    def emit(self, kind: str, payload: dict[str, Any], key: str | None = None) -> None:
        if key and self.state["targets"].get(key):
            return
        if key:
            self.state["targets"][key] = True
        self.store.commit(
            [dict(kind=kind, at=now().isoformat(), payload=payload)], self.state, {}, now()
        )

    def capture(
        self, url: str, body: bytes, status: int, received: str, started: str | None = None
    ) -> dict[str, Any]:
        url = canonical(url)
        digest = hashlib.sha256(body).hexdigest()
        path = self.raw / f"{digest}.raw"
        if not path.exists():
            with path.open("xb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
        elif hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Raw content integrity failure")
        result = dict(
            url=url,
            status=status,
            received_at=received,
            request_start=started,
            sha256=digest,
            raw_file=path.name,
        )
        self.state["captures"][url] = result
        self.emit("HTTP_CAPTURE", result)
        return result

    def import_initial(self) -> None:
        manifest = self.directory / "initial_manifest.json"
        if not manifest.exists():
            return
        for item in json.loads(manifest.read_text(encoding="utf-8")):
            url = canonical(item["url"])
            if url in self.state["captures"]:
                continue
            source = (ROOT / item["path"]).resolve()
            if source.parent != self.directory.resolve():
                raise ValueError("Initial capture outside research directory")
            body = source.read_bytes()
            if hashlib.sha256(body).hexdigest() != item["sha256"]:
                raise ValueError("Initial capture hash mismatch")
            self.capture(url, body, item["status"], item["received_at"], item.get("request_start"))

    def get(
        self,
        client: httpx.Client,
        url: str,
        params: dict[str, Any] | None = None,
        refresh: bool = False,
    ) -> tuple[Any, dict[str, Any]]:
        url = canonical(url, params)
        result = self.state["captures"].get(url)
        if refresh or result is None:
            time.sleep(max(0, 0.7 - (time.monotonic() - self.last_request)))
            started = now()
            response = client.get(url)
            self.last_request = time.monotonic()
            result = self.capture(
                url, response.content, response.status_code, now().isoformat(), started.isoformat()
            )
        body = (self.raw / result["raw_file"]).read_bytes()
        if hashlib.sha256(body).hexdigest() != result["sha256"]:
            raise ValueError("Capture hash mismatch")
        if result["status"] == 204:
            return [], result
        if result["status"] != 200:
            raise ValueError(f"PUBLIC_SOURCE_HTTP_{result['status']}")
        return json.loads(body), result

    def close(self) -> None:
        self.store.close()


def source_request(event: dict[str, Any], day: date) -> tuple[str, dict[str, Any]]:
    source = str(event.get("resolutionSource") or "")
    canonical(source)
    parsed = urlsplit(source)
    params = dict(parse_qsl(parsed.query))
    if parsed.hostname != "aviationweather.gov" or params.get("ids") != "EPWA":
        raise ValueError("NO_SUPPORTED_OFFICIAL_SOURCE")
    # A wider documented query supplies the first following-day report as cutoff
    # evidence, even when the exact source URL ends at midnight.
    params.update(
        format="json", date=(day + timedelta(days=1)).isoformat() + "T04:00:00Z", hours="36"
    )
    return source, params


def source_evidence(
    day: date, rules: dict[str, Any], reports: list[dict[str, Any]], capture: dict[str, Any]
) -> tuple[datetime | None, dict[str, Any]]:
    start, end = local_day_bounds(day)
    deadline = datetime.combine(
        day + timedelta(days=1), day_time(23, 59, 59), ZoneInfo("America/New_York")
    ).astimezone(UTC)
    following = []
    covered = set()
    eligible_receipts = True
    late_corrections = False
    for row in reports:
        try:
            event = datetime.fromtimestamp(row["obsTime"], UTC)
            receipt = clock(row["receiptTime"])
        except (KeyError, ValueError, TypeError, OverflowError, OSError):
            eligible_receipts = False
            continue
        parsed = parse_temperature(str(row.get("rawOb", "")), rules)
        if (
            event >= end
            and event < end + timedelta(days=1)
            and not str(row.get("rawOb", "")).strip().startswith("SPECI")
        ):
            following.append(receipt)
        if start <= event < end and parsed.get("temperature_c") is not None:
            covered.add(event)
    cutoff = min(following + [deadline]) if following else None
    for row in reports:
        try:
            event = datetime.fromtimestamp(row["obsTime"], UTC)
            receipt = clock(row["receiptTime"])
            if start <= event < end and cutoff and receipt > cutoff:
                eligible_receipts = False
                if re.search(r"\bCOR\b", str(row.get("rawOb", ""))):
                    late_corrections = True
        except (KeyError, ValueError, TypeError, OverflowError, OSError):
            eligible_receipts = False
    expected = {
        start + timedelta(minutes=30 * i) for i in range(int((end - start).total_seconds() / 1800))
    }
    missing = sorted(expected - covered)
    evidence = dict(
        official_source=True,
        coverage_complete=not missing and len(reports) < 400,
        rule_eligibility_verified=bool(rules.get("verified")),
        provider_receipt_cutoff_verified=bool(cutoff and eligible_receipts),
        correction_versions_unambiguous=not late_corrections,
        source_reference=capture["url"],
        source_snapshot_sha256=capture["sha256"],
        certification_basis="CURRENT_OFFICIAL_ARCHIVE_REPRODUCTION_WITH_PROVIDER_RECEIPT_CUTOFF",
        source_snapshot_at_cutoff_certified=False,
        historical_source_state_at_resolution="NOT_ARCHIVED",
        declared_schedule="EPWA_UTC_HALF_HOURLY_00_30_WITH_ADDITIONAL_ROUTINE_INCLUDED",
        missing_nominal_times=[t.isoformat() for t in missing],
        expected_nominal_reports=len(expected),
        api_rows=len(reports),
        cutoff_derivation="FIRST_FOLLOWING_LOCAL_DAY_ROUTINE_AWC_PROVIDER_RECEIPT"
        if following
        else "NO_FOLLOWING_DAY_REPORT_CUTOFF_UNVERIFIED",
        fallback_not_assumed=True,
    )
    return cutoff, evidence


def audit_day(
    evidence: Evidence, client: httpx.Client, day: date, refresh: bool = False
) -> dict[str, Any]:
    slug = f"highest-temperature-in-warsaw-on-{MONTHS[day.month - 1]}-{day.day}-{day.year}"
    events, market_capture = evidence.get(
        client, "https://gamma-api.polymarket.com/events", dict(slug=slug), refresh
    )
    event = (
        next((e for e in events if e.get("slug") == slug), None)
        if isinstance(events, list)
        else None
    )
    if not event:
        return dict(
            settlement_date=day.isoformat(),
            classification="INSUFFICIENT_EVIDENCE",
            reason="NO_EVENT_FOUND",
            target_available_at=market_capture["received_at"],
        )
    market = resolved_market(event)
    rules = parse_rules(event)
    target = dict(
        settlement_date=day.isoformat(),
        market_event_id=str(event["id"]),
        event_slug=slug,
        source_url=event.get("resolutionSource"),
        market_url=f"https://polymarket.com/event/{slug}",
        market_result=market,
        rules=rules,
        raw_market_sha256=market_capture["sha256"],
        market_evidence_received_at=market_capture["received_at"],
        market_reported_closed_time=event.get("closedTime"),
        target_available_at=market_capture["received_at"],
    )
    try:
        source, params = source_request(event, day)
        # Capture exact documented resolution-source view as well as structured data.
        raw_source, raw_capture = (
            evidence.get(client, source, refresh=refresh)
            if dict(parse_qsl(urlsplit(source).query)).get("format") == "json"
            else (None, None)
        )
        # RAW endpoints are text, captured by the separate raw method below.
        raw_url = canonical(source)
        raw_capture = evidence.state["captures"].get(raw_url)
        if refresh or not raw_capture:
            time.sleep(max(0, 0.7 - (time.monotonic() - evidence.last_request)))
            began = now()
            response = client.get(raw_url)
            evidence.last_request = time.monotonic()
            raw_capture = evidence.capture(
                raw_url,
                response.content,
                response.status_code,
                now().isoformat(),
                began.isoformat(),
            )
        reports, source_capture = evidence.get(
            client, "https://aviationweather.gov/api/data/metar", params, refresh
        )
        if not isinstance(reports, list) or any(
            not isinstance(r, dict) or r.get("icaoId") != "EPWA" for r in reports
        ):
            raise ValueError("INVALID_OFFICIAL_RESPONSE")
        cutoff, certificate = source_evidence(day, rules, reports, source_capture)
        # The exact source view must support every winning/qualifying archive
        # report in the requested day; otherwise keep a lower evidence tier.
        exact_body = (evidence.raw / raw_capture["raw_file"]).read_text(encoding="utf-8")
        start, end = local_day_bounds(day)
        exact_times = {
            r["rawOb"] for r in reports if start <= datetime.fromtimestamp(r["obsTime"], UTC) < end
        }
        exact_match = raw_capture["status"] == 200 and all(
            text in exact_body for text in exact_times
        )
        certificate["exact_resolution_source_includes_all_day_reports"] = exact_match
        certificate["coverage_complete"] = certificate["coverage_complete"] and exact_match
        annotated = [
            dict(
                r,
                raw_payload_hash=source_capture["sha256"],
                source_reference=source_capture["url"],
                collector_receive_time=source_capture["received_at"],
                source_receipt_time=r.get("receiptTime"),
            )
            for r in reports
        ]
        rebuilt = reconstruct_day(
            day, rules, annotated, cutoff=cutoff, evidence=certificate, market_result=market
        )
        target.update(rebuilt)
        target.update(
            verification_evidence=certificate,
            raw_source_sha256=raw_capture["sha256"],
            structured_source_sha256=source_capture["sha256"],
            source_evidence_received_at=source_capture["received_at"],
            target_available_at=max(
                market_capture["received_at"],
                source_capture["received_at"],
                raw_capture["received_at"],
            ),
            source_provenance="AWC_CURRENT_OFFICIAL_ARCHIVE_BACKFILL_NOT_HISTORICAL_COLLECTOR_RECEIPT",
        )
    except (ValueError, KeyError, TypeError, httpx.HTTPError) as error:
        target.update(
            classification="VERIFIED_MARKET_ONLY"
            if market.get("confirmed")
            else "INSUFFICIENT_EVIDENCE",
            source_failure=type(error).__name__,
            source_reproduction_verified=False,
        )
    key = hashlib.sha256(json.dumps(target, sort_keys=True).encode()).hexdigest()
    created = evidence.state.setdefault("normalized_at", {}).setdefault(key, now().isoformat())
    target["label_created_at"] = created
    target["target_available_at"] = max(target["target_available_at"], created)
    evidence.emit("SETTLEMENT_TARGET", target, key)
    return target


def normalize_archived_hourly(raw: dict[str, Any], model: str, received: str) -> dict[str, Any]:
    hourly = raw["hourly"]
    units = raw["hourly_units"]
    key = f"temperature_2m_{model}"
    if units.get("time") != "unixtime" or units.get(key) != "°C":
        raise ValueError("Unknown archive units")
    times, values = hourly["time"], hourly[key]
    if len(times) != len(values):
        raise ValueError("Archive arrays mismatch")
    points = []
    for t, value in zip(times, values, strict=True):
        if value is None:
            continue
        if (
            isinstance(value, bool)
            or not math.isfinite(float(value))
            or not -90 <= float(value) <= 65
        ):
            raise ValueError("Invalid archive temperature")
        points.append(
            dict(valid_time=datetime.fromtimestamp(t, UTC).isoformat(), temperature_c=float(value))
        )
    if not points:
        raise ValueError("No archive points")
    return dict(
        model=model,
        family=MODEL_SPECS[model]["family"],
        first_received=received,
        points=points,
        days=[],
        daily_api_tmax_status="UNSUPPORTED_FOR_UTC00_RUN_AND_WARSAW_LOCAL_MIDNIGHT_ALIGNMENT",
        hourly_point_maximum_semantics="MAX_OF_POINT_FORECASTS_NOT_DAILY_API_MAXIMUM",
    )


def fetch_archive_runs(
    evidence: Evidence, client: httpx.Client, start: date, end: date, refresh: bool = False
) -> list[dict[str, Any]]:
    latitude, longitude = airport_coordinates()
    runs = []
    for n in range((end - start).days + 1):
        day = start + timedelta(days=n)
        init = datetime.combine(day, day_time.min, UTC)
        try:
            raw, capture = evidence.get(
                client,
                "https://single-runs-api.open-meteo.com/v1/forecast",
                dict(
                    latitude=latitude,
                    longitude=longitude,
                    run=init.strftime("%Y-%m-%dT%H:%M"),
                    models=",".join(MODEL_SPECS),
                    hourly="temperature_2m",
                    timezone="Europe/Warsaw",
                    timeformat="unixtime",
                ),
                refresh,
            )
            for model in MODEL_SPECS:
                try:
                    normalized = normalize_archived_hourly(raw, model, capture["received_at"])
                    normalized.update(
                        run_id=f"{model}:{init.isoformat()}",
                        initialization_time=init.isoformat(),
                        availability_class="APPROXIMATE_REPLAY",
                        availability_time=None,
                        publication_time=None,
                        decision_assumption="INIT_PLUS_6H_SCENARIO_NOT_VERIFIED_ORIGINAL_AVAILABILITY",
                        source_url=capture["url"],
                        raw_payload_hash=capture["sha256"],
                    )
                    runs.append(normalized)
                    evidence.emit(
                        "ARCHIVED_FORECAST_RUN",
                        normalized,
                        hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest(),
                    )
                except (ValueError, KeyError, TypeError):
                    evidence.emit(
                        "ARCHIVE_MODEL_UNAVAILABLE",
                        dict(
                            model=model,
                            initialization_time=init.isoformat(),
                            raw_payload_hash=capture["sha256"],
                        ),
                    )
            print("ARCHIVE", day, "models", len(runs), flush=True)
        except (ValueError, httpx.HTTPError):
            evidence.emit(
                "ARCHIVE_REQUEST_FAILED",
                dict(initialization_time=init.isoformat(), reason="PUBLIC_ARCHIVE_REQUEST_FAILED"),
            )
    return runs


def build(
    start: date,
    end: date,
    refresh: bool = False,
    directory: Path = DIRECTORY,
    output: Path = OUTPUT,
    static: Path | None = STATIC,
) -> dict[str, Any]:
    if not 0 <= (end - start).days < 31:
        raise ValueError("Bounded maximum31days")
    if end >= now().astimezone(ZoneInfo("Europe/Warsaw")).date():
        raise ValueError("Only completed historical days")
    evidence = Evidence(directory)
    targets = []
    try:
        evidence.import_initial()
        with httpx.Client(
            timeout=40,
            verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
            headers={"User-Agent": "michupl-pre-metar/EXP0016.1-public-settlement-audit"},
        ) as client:
            for n in range((end - start).days + 1):
                day = start + timedelta(days=n)
                try:
                    target = audit_day(evidence, client, day, refresh)
                except (ValueError, httpx.HTTPError) as error:
                    target = dict(
                        settlement_date=day.isoformat(),
                        classification="INSUFFICIENT_EVIDENCE",
                        error=type(error).__name__,
                        target_available_at=now().isoformat(),
                    )
                targets.append(target)
                print(
                    day,
                    target["classification"],
                    target.get("raw_maximum_c", target.get("qualifying_maximum_c")),
                    flush=True,
                )
            archived = fetch_archive_runs(
                evidence,
                client,
                max(start, date(2026, 10, 21)),
                min(end, date(2026, 10, 27)),
                refresh,
            )
        calibration = evaluate(
            load_archived_runs(ROOT / "data/research/epwa_calibration/archive.sqlite3") + archived,
            targets,
            at=now(),
        )
        output.mkdir(parents=True, exist_ok=True)
        export(calibration, output / "calibration")
        result = dict(
            version="EXP0016.1-v1",
            published_at=now().isoformat(),
            targets=targets,
            calibration=calibration,
            classification_counts={
                status: sum(t["classification"] == status for t in targets)
                for status in sorted({t["classification"] for t in targets})
            },
            required_training_days=30,
            required_holdout_days=20,
            scope="RETROSPECTIVE_BACKFILLED_LABELS_NOT_HISTORICALLY_AVAILABLE_SIGNALS",
        )
        export_truth(result, output, static)
        return result
    finally:
        evidence.close()


def export_truth(result: dict[str, Any], output: Path, static: Path | None = None) -> None:
    encoded = json.dumps(result, sort_keys=True, indent=2, ensure_ascii=True)
    (output / "settlement_truth.json").write_text(encoded, encoding="utf-8")
    rows = result["targets"]
    fields = sorted({k for row in rows for k in row})
    with (output / "settlement_targets.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            {
                k: json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v
                for k, v in row.items()
            }
            for row in rows
        )
    for kind in ("selected_reports", "excluded_reports"):
        observations = [
            dict(settlement_date=t["settlement_date"], **r) for t in rows for r in t.get(kind, [])
        ]
        columns = sorted({k for r in observations for k in r}) or ["status"]
        with (output / f"{kind}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(
                {
                    k: json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v
                    for k, v in r.items()
                }
                for r in observations
            )
    lines = [
        "# EXP0016.1 — EPWA settlement ground truth",
        f"\nEvidence audit published UTC:{result['published_at']}. {result['scope']}.",
        "\nDate | Raw qualifying maximum | Rounded integer | Market winner | Class | Source at historical cutoff",
        "---|---:|---:|---|---|---",
    ]
    lines += [
        f"{t['settlement_date']} | {t.get('raw_maximum_c', t.get('qualifying_maximum_c'))} | {t.get('settlement_integer', t.get('integer_outcome'))} | {t.get('winning_bracket', t.get('market_result', {}).get('winning_label'))} | {t['classification']} | {t.get('historical_source_state_at_resolution', 'NOT_ARCHIVED')}"
        for t in rows
    ]
    lines += [
        "\nCurrent official archive reproduction is a backfilled LABEL certificate, not proof of original collector availability or an archived resolution-time source view. Provider receiptTime is preserved separately from actual backfill receipt. Exact-source RAW plus structured archive and full half-hour schedule coverage required; off-hour routine reports included, SPECI excluded.",
        f"\nCounts:{result['classification_counts']}. Required independent training days30 plus20heldout; probabilities remain blocked.",
        "\nForecast errors and sample counts: calibration/ files; dailyAPI Tmax never silently replaced by maximum hourly points. Approximate init+6h replays are distinct from verified availability.",
        "\nFallback Wunderground/no-data lowest-bracket conditions are not assumed from missing API records. Missing corrected predecessor or incomplete cutoff/coverage lowers verification. No production or frozen strategy changes.",
    ]
    (output / "epwa_settlement_ground_truth.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    if static:
        # Public thin catalog; full raw reports remain in the separate audit store.
        thin = dict(
            result,
            targets=[
                {
                    k: v
                    for k, v in t.items()
                    if k
                    not in {
                        "observations",
                        "reports",
                        "excluded",
                        "selected_reports",
                        "excluded_reports",
                        "report_versions",
                    }
                }
                for t in rows
            ],
        )
        temporary = static.with_suffix(".tmp")
        temporary.write_text(json.dumps(thin, sort_keys=True, ensure_ascii=True), encoding="utf-8")
        temporary.replace(static)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2026-10-15")
    parser.add_argument("--end", default="2026-10-28")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    if args.report_only:
        result = json.loads((OUTPUT / "settlement_truth.json").read_text(encoding="utf-8"))
        export_truth(result, OUTPUT, STATIC)
        export(result["calibration"], OUTPUT / "calibration")
        print("Regenerated fixed audit without network or database writes")
        return
    result = build(date.fromisoformat(args.start), date.fromisoformat(args.end), args.refresh)
    print(
        json.dumps(
            dict(
                counts=result["classification_counts"],
                progress=result["calibration"].get("progress"),
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
