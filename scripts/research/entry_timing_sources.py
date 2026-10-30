"""Bounded, cached EXP0017 public identity and nominal METAR archive evidence.

Writes only a separate research directory. Neither archive time nor present-day
metadata retrieval proves historical public availability.
"""

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sqlite3
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from scripts.research.hightemptation_metadata import market_identity, station_from_rules

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "data/research/exp0012/trader_pinned.sqlite3"
DIRECTORY = ROOT / "data/research/exp0017"


def clock(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timezone required")
    return parsed.astimezone(UTC)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def no_buys(path: Path = BASELINE) -> list[dict[str, Any]]:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    try:
        return [
            row
            for (encoded,) in connection.execute("SELECT payload FROM events WHERE kind='TRADE'")
            if (row := json.loads(encoded)).get("side") == "BUY"
            and str(row.get("outcome", "")).lower() == "no"
            and market_identity(str(row.get("slug", "")))[0] != "OTHER"
        ]
    finally:
        connection.close()


class Capture:
    """One request per second at most; no automatic retry or ignored HTTP error."""

    def __init__(
        self,
        directory: Path,
        client: httpx.Client,
        max_requests: int = 100,
        max_bytes: int = 200_000_000,
    ) -> None:
        self.directory, self.client = directory, client
        self.max_requests, self.max_bytes = max_requests, max_bytes
        self.requests = len(list(directory.glob("*.json")))
        self.bytes = sum(path.stat().st_size for path in directory.glob("*.raw"))
        self.previous_request = 0.0
        directory.mkdir(parents=True, exist_ok=True)

    def get(self, url: str, params: list[tuple[str, str]]) -> tuple[bytes, dict[str, Any]]:
        request = self.client.build_request("GET", url, params=urlencode(params))
        if request.url.host not in {"gamma-api.polymarket.com", "mesonet.agron.iastate.edu"}:
            raise ValueError("Public source allowlist required")
        key = hashlib.sha256(str(request.url).encode()).hexdigest()
        metadata_path = self.directory / f"{key}.json"
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            body = (self.directory / (metadata["sha256"] + ".raw")).read_bytes()
            if hashlib.sha256(body).hexdigest() != metadata["sha256"]:
                raise ValueError("Raw capture hash mismatch")
            return body, metadata
        if self.requests >= self.max_requests or self.bytes >= self.max_bytes:
            raise RuntimeError("Research capture budget exhausted")
        delay = self.previous_request + 1.05 - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        started = datetime.now(UTC).isoformat()
        self.previous_request = time.monotonic()
        self.requests += 1
        # Stream to enforce a hard aggregate byte budget before parsing.
        response = self.client.send(request, stream=True)
        try:
            pieces = []
            for piece in response.iter_bytes():
                self.bytes += len(piece)
                if self.bytes > self.max_bytes:
                    raise RuntimeError("Research capture byte budget exhausted")
                pieces.append(piece)
            body = b"".join(pieces)
        finally:
            response.close()
        metadata = {
            "url": str(request.url),
            "request_start": started,
            "received_at": datetime.now(UTC).isoformat(),
            "http_status": response.status_code,
            "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body),
        }
        raw_path = self.directory / (metadata["sha256"] + ".raw")
        if not raw_path.exists():
            with raw_path.open("xb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
        write_json(metadata_path, metadata)
        return body, metadata


def tokens(market: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for field in ("positionIds", "clobTokenIds"):
        values = market.get(field) or []
        try:
            values = json.loads(values) if isinstance(values, str) else values
        except ValueError:
            continue
        if isinstance(values, list):
            result.update(str(value) for value in values)
    return result


def fetch_markets(capture: Capture, trades: list[dict[str, Any]]) -> dict[str, Any]:
    conditions = sorted({str(row["condition_id"]) for row in trades})
    envelopes, requests, errors = [], [], []
    for offset in range(0, len(conditions), 100):
        batch = conditions[offset : offset + 100]
        try:
            body, receipt = capture.get(
                "https://gamma-api.polymarket.com/markets",
                [("condition_ids", value) for value in batch]
                + [("closed", "any"), ("limit", "100")],
            )
            requests.append(receipt)
            if receipt["http_status"] != 200:
                errors.append({"batch": offset, "http_status": receipt["http_status"]})
                if receipt["http_status"] in (429, 503):
                    break
                continue
            markets = json.loads(body)
            if not isinstance(markets, list):
                raise ValueError("Unexpected Gamma schema")
            for market in markets:
                if market.get("conditionId") not in batch:
                    raise ValueError("Gamma returned unrelated market; refusing identity")
                envelopes.append(
                    {
                        "market": market,
                        "received_at": receipt["received_at"],
                        "raw_hash": receipt["sha256"],
                    }
                )
        except (httpx.HTTPError, ValueError, RuntimeError) as error:
            errors.append({"batch": offset, "error_class": type(error).__name__})
            if isinstance(error, RuntimeError):
                break
    by_condition = {str(row["market"]["conditionId"]): row for row in envelopes}
    covered = sum(
        row["condition_id"] in by_condition
        and row["token_id"] in tokens(by_condition[row["condition_id"]]["market"])
        for row in trades
    )
    return {
        "markets": envelopes,
        "requests": requests,
        "errors": errors,
        "requested_conditions": len(conditions),
        "returned_conditions": len(by_condition),
        "exact_condition_token_trade_rows": covered,
        "semantics": "RETROSPECTIVE_MARKET_IDENTITY_NOT_HISTORICAL_AVAILABILITY",
    }


def parse_archive(
    body: bytes, receipt: dict[str, Any], stations: set[str], report_type: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep nominal UTC source times and report versions; never invent local receipts."""
    text = body.decode("utf-8-sig")
    lines = [line for line in text.splitlines() if not line.startswith("#")]
    rows, errors = [], []
    reader = csv.DictReader(io.StringIO("\n".join(lines)))
    if not {"station", "valid", "metar"}.issubset(set(reader.fieldnames or [])):
        return [], [{"reason": "UNEXPECTED_ARCHIVE_SCHEMA", "raw_hash": receipt["sha256"]}]
    for index, item in enumerate(reader):
        raw = str(item.get("metar") or "").strip()
        # Match the exact original ICAO inside TAC; no city-to-airport guess.
        identity = re.match(
            r"^(?:(?:METAR|SPECI)\s+)?(?:COR\s+)?([A-Z][A-Z0-9]{3})\s+\d{6}Z\b", raw
        )
        if not identity or identity[1] not in stations:
            errors.append(
                {
                    "reason": "UNVERIFIED_ARCHIVE_STATION",
                    "row": index,
                    "raw_hash": receipt["sha256"],
                }
            )
            continue
        try:
            nominal = datetime.fromisoformat(item["valid"].replace("Z", "+00:00"))
            nominal = (
                nominal.replace(tzinfo=UTC) if nominal.tzinfo is None else nominal.astimezone(UTC)
            )
        except (ValueError, KeyError):
            errors.append(
                {"reason": "INVALID_ARCHIVE_TIME", "row": index, "raw_hash": receipt["sha256"]}
            )
            continue
        tac_time = re.search(r"\b(\d{6})Z\b", raw)
        if not tac_time or nominal.strftime("%d%H%M") != tac_time[1]:
            errors.append(
                {"reason": "ARCHIVE_TAC_TIME_MISMATCH", "row": index, "raw_hash": receipt["sha256"]}
            )
            continue
        temperature = None
        match = re.search(r"(?:^|\s)(M?\d{2})/(?:M?\d{2}|//)(?=\s|=|$)", raw)
        if match:
            temperature = -float(match[1][1:]) if match[1].startswith("M") else float(match[1])
        explicit_type = re.match(r"^(METAR|SPECI)\s", raw)
        product_type = explicit_type[1] if explicit_type else "UNKNOWN_ROUTINE_OR_SPECI"
        rows.append(
            {
                "station_icao": identity[1],
                "event_time": nominal.isoformat(),
                "raw_text": raw,
                "product_type": product_type,
                "candidate_product_type": "SPECI" if product_type == "SPECI" else "METAR",
                "report_type_provenance": "EXPLICIT_ORIGINAL_TAC_PREFIX"
                if explicit_type
                else "IEM_HOURLY_CLASSIFIER_NOT_ICAO_REPORT_IDENTITY",
                "classification_flags": []
                if explicit_type
                else ["ORIGINAL_METAR_SPECI_PREFIX_ABSENT"],
                "correction_status": "COR" if re.search(r"\bCOR\b", raw) else None,
                "temperature_c": temperature,
                "archive_first_received_at": receipt["received_at"],
                "collector_receive_time": None,
                "source": "IEM_HISTORICAL_ARCHIVE",
                "timestamp_semantics": "OBSERVATION_TIME_KNOWN_PUBLIC_RELEASE_TIME_UNKNOWN",
                "raw_hash": receipt["sha256"],
                "archive_report_type": report_type,
                "archive_hourly_class": "IEM_HOURLY" if report_type == "3" else "IEM_NONHOURLY",
            }
        )
    return rows, errors


def fetch_metars(
    capture: Capture, trades: list[dict[str, Any]], market_data: dict[str, Any]
) -> dict[str, Any]:
    by_condition = {
        str(row["market"]["conditionId"]): row["market"] for row in market_data["markets"]
    }
    station_times: dict[str, list[datetime]] = {}
    for trade in trades:
        market = by_condition.get(str(trade["condition_id"]))
        if not market or str(trade["token_id"]) not in tokens(market):
            continue
        station, _ = station_from_rules(market)
        if station:
            station_times.setdefault(station, []).append(clock(trade["source_trade_timestamp"]))
    reports: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    stations = sorted(station_times)
    for offset in range(0, len(stations), 8):
        batch = stations[offset : offset + 8]
        times = [stamp for station in batch for stamp in station_times[station]]
        start = (min(times) - timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = (max(times) + timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
        # IEM uses three-letter identifiers for continental US ASOS. Request both
        # literal ICAO and documented domestic identifier, accepting only exact TAC.
        aliases = sorted(set(batch) | {station[1:] for station in batch if station.startswith("K")})
        for report_type in ("3", "4"):
            params = [("station", station) for station in aliases] + [
                ("data", "metar"),
                ("sts", start.isoformat()),
                ("ets", end.isoformat()),
                ("tz", "UTC"),
                ("format", "onlycomma"),
                ("latlon", "no"),
                ("elev", "no"),
                ("missing", "empty"),
                ("report_type", report_type),
            ]
            try:
                body, receipt = capture.get(
                    "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py", params
                )
                requests.append(receipt)
                if receipt["http_status"] != 200:
                    errors.append({"stations": batch, "http_status": receipt["http_status"]})
                    if receipt["http_status"] in (429, 503):
                        return {"reports": reports, "requests": requests, "errors": errors}
                    continue
                parsed, failures = parse_archive(body, receipt, set(batch), report_type)
                reports.extend(parsed)
                errors.extend(failures)
            except (httpx.HTTPError, ValueError, RuntimeError) as error:
                errors.append({"stations": batch, "error_class": type(error).__name__})
                if isinstance(error, RuntimeError):
                    break
        print(
            json.dumps({"archive_batch": batch, "reports": len(reports), "errors": len(errors)}),
            flush=True,
        )
    return {
        "reports": reports,
        "requests": requests,
        "errors": errors,
        "requested_stations": stations,
        "station_counts": dict(Counter(row["station_icao"] for row in reports)),
        "semantics": "ARCHIVED_NOMINAL_REPORTS_NOT_OFFICIAL_HISTORICAL_PUBLICATION_EVIDENCE",
        "parser_version": "EXP0017-IEM-TAC-TYPE-v2",
        "product_type_counts": dict(Counter(row["product_type"] for row in reports)),
        "archive_hourly_class_counts": dict(
            Counter(row["archive_hourly_class"] for row in reports)
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=DIRECTORY)
    parser.add_argument("--markets-only", action="store_true")
    parser.add_argument("--archive-only", action="store_true")
    args = parser.parse_args()
    trades = no_buys()
    with httpx.Client(
        timeout=60,
        follow_redirects=False,
        headers={"User-Agent": "michupl-pre-metar-research/EXP0017"},
    ) as client:
        capture = Capture(args.directory / "evidence", client)
        market_path = args.directory / "markets.json"
        markets = (
            json.loads(market_path.read_text(encoding="utf-8"))
            if args.archive_only
            else fetch_markets(capture, trades)
        )
        if not args.archive_only:
            write_json(market_path, markets)
        print(
            json.dumps(
                {key: value for key, value in markets.items() if key not in {"markets", "requests"}}
            ),
            flush=True,
        )
        if not args.markets_only:
            metars = fetch_metars(capture, trades, markets)
            write_json(args.directory / "metars.json", metars)
            print(
                json.dumps(
                    {
                        key: value
                        for key, value in metars.items()
                        if key not in {"reports", "requests", "errors"}
                    }
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
