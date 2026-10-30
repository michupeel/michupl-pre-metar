"""EXP0017 reproducible frozen-history + independent bounded live extracts.

No production writer, monitor restart, trading rule or external polling here.
Run sources first, then this module; --capture only creates an isolated snapshot.
"""

import argparse
import csv
import hashlib
import json
import sqlite3
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from premetar.research.entry_timing import (
    VERSION,
    cadence,
    deduplicate,
    execution_key,
    phase_contrast,
    price_bucket,
    receipt_context,
    schedule_offsets,
    summarize,
    timing_bin,
    utc,
)
from premetar.research.forecast_monitor import backup_weather
from premetar.research.trader_normalizer import WALLET
from premetar.research.trader_store import readonly_connection
from scripts.research.hightemptation_inventory import reconstruct
from scripts.research.hightemptation_metadata import (
    CITY_TIMEZONES,
    _rule_fields,
    _tokens,
    day_bounds,
    load_market_metadata,
    market_identity,
)

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/research/exp0017"
OUTPUT = ROOT / "reports/trader"
FROZEN = ROOT / "data/research/exp0012/trader_pinned.sqlite3"
EXPECTED_SHA = "6cddb1ee11e6a30d9bc9fac15ba659eb1a1a57045c7809e19db2bca3d3709b89"


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({k for row in rows for k in row}) or ["status"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            {
                k: json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v
                for k, v in row.items()
            }
            for row in rows
        )


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def capture(directory: Path = DATA) -> dict[str, Any]:
    """Compact logical snapshot with explicit bounded evidence coverage, not13GB copy."""
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "snapshot_manifest.json"
    if manifest_path.exists():
        return dict(json.loads(manifest_path.read_text(encoding="utf-8")))
    source = ROOT / "data/trader/monitor.sqlite3"
    target = directory / "trader_extract.sqlite3"
    if target.exists():
        raise FileExistsError("Incomplete extract exists; inspect before retry")
    source_conn = readonly_connection(source)
    destination = sqlite3.connect(target)
    started = datetime.now(UTC).isoformat()
    counts = {}
    try:
        source_conn.execute("BEGIN")
        ceiling = source_conn.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0]
        destination.execute(
            "CREATE TABLE events(id INTEGER PRIMARY KEY,kind TEXT,received_at TEXT,event_key TEXT,payload TEXT,payload_hash TEXT)"
        )
        for kind, limit in (
            ("TRADE", 50000),
            ("ROLE_EVIDENCE", 5000),
            ("WEATHER", 5000),
            ("ENDPOINT_RECEIPT", 10000),
            ("ACTIVITY", 10000),
            ("MARKET", 5000),
            ("BOOK", 1000),
            ("WS_TRADE", 5000),
        ):
            rows = source_conn.execute(
                "SELECT id,kind,received_at,event_key,payload,payload_hash FROM events WHERE kind=? AND id<=? ORDER BY id DESC LIMIT ?",
                (kind, ceiling, limit),
            ).fetchall()
            destination.executemany("INSERT INTO events VALUES(?,?,?,?,?,?)", rows)
            counts[kind] = dict(copied=len(rows), limit=limit, may_be_truncated=len(rows) == limit)
        destination.execute("CREATE INDEX extract_kind_id ON events(kind,id)")
        destination.commit()
        integrity = destination.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        source_conn.close()
        destination.close()
    weather = backup_weather(
        ROOT / "data/continuous-v1.sqlite3", directory / "weather_snapshot.sqlite3"
    )
    manifest = dict(
        started_at=started,
        snapshot_cutoff=datetime.now(UTC).isoformat(),
        source_max_id=ceiling,
        trader=dict(
            snapshot=str(target), sha256=digest(target), integrity=integrity, coverage=counts
        ),
        weather=weather,
        frozen_sha256=EXPECTED_SHA,
        version=VERSION,
    )
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def trades_at(path: Path) -> list[dict[str, Any]]:
    conn = readonly_connection(path)
    try:
        return [
            json.loads(row[0])
            for row in conn.execute("SELECT payload FROM events WHERE kind='TRADE' ORDER BY id")
        ]
    finally:
        conn.close()


def metadata_for(
    trades: list[dict[str, Any]], enriched: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    metadata = load_market_metadata(FROZEN)
    by_condition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in enriched.get("markets", []):
        by_condition[str(record["market"].get("conditionId"))].append(record)
    for trade in trades:
        token = str(trade["token_id"])
        if token not in metadata:
            kind, city, day = market_identity(str(trade.get("slug") or ""))
            metadata[token] = dict(
                market_kind=kind,
                city=city,
                market_date=day.isoformat() if day else None,
                timezone=CITY_TIMEZONES.get(city),
                reference_station=None,
                settlement_day_end_utc=None,
                metadata_available_at=None,
            )
        meta = metadata[token]
        records = by_condition.get(trade["condition_id"], [])
        for record in sorted(records, key=lambda r: r["received_at"]):
            market = record["market"]
            if token not in _tokens(market):
                continue
            # Recovered exact-contract identity is retrospective, not historical weather.
            fields = _rule_fields(market)
            old_station = meta.get("reference_station")
            if (
                old_station
                and fields["reference_station"]
                and old_station != fields["reference_station"]
            ):
                meta.update(reference_station=None, station_status="CONFLICTING_CAPTURED_VERSIONS")
                break
            if not old_station:
                meta.update(
                    fields,
                    metadata_available_at=record["received_at"],
                    metadata_semantics="RETROSPECTIVE_EXACT_CONTRACT_RULES",
                    metadata_raw_hash=record.get("raw_hash"),
                )
            meta.update(
                contract_outcome=market.get("groupItemTitle") or market.get("question"),
                market_end_date=market.get("endDate"),
                final_resolution_time=None,
                market_closed_time=market.get("closedTime"),
                resolution_time_status="CLOSED_TIME_NOT_CERTIFIED_FINAL_RESOLUTION",
            )
            if fields["local_day_explicit"] and meta.get("timezone") and meta.get("market_date"):
                start, end = day_bounds(
                    datetime.fromisoformat(meta["market_date"]).date(), meta["timezone"]
                )
                meta.update(
                    settlement_day_start_utc=start.isoformat(),
                    settlement_day_end_utc=end.isoformat(),
                )
            break
    return metadata


def load_reports(directory: Path) -> list[dict[str, Any]]:
    archive_path = directory / "metars.json"
    reports = (
        json.loads(archive_path.read_text(encoding="utf-8")).get("reports", [])
        if archive_path.exists()
        else []
    )
    connection = readonly_connection(directory / "weather_snapshot.sqlite3")
    connection.row_factory = sqlite3.Row
    try:
        reports.extend(
            dict(r)
            for r in connection.execute(
                "SELECT station_icao,event_time,collector_receive_time,product_type,raw_text,temperature_c,evidence_class,startup_censored,coverage_gap,source,raw_sha256 FROM observations WHERE product_type IN ('METAR','SPECI')"
            )
        )
    finally:
        connection.close()
    return reports


def align_reports(
    row: dict[str, Any], reports: list[dict[str, Any]], clocks: list[datetime]
) -> None:
    """Historical nominal time matching does not claim historical public availability."""
    at = utc(row["source_trade_timestamp"])
    index = bisect_left(clocks, at)
    nearby = clocks[max(0, index - 1) : index + 1]
    nearest = min(nearby, key=lambda t: (abs((at - t).total_seconds()), t)) if nearby else None
    if nearest is not None and abs((at - nearest).total_seconds()) <= 3600:
        offset = (at - nearest).total_seconds()
        previous_index = index if index < len(clocks) and clocks[index] == at else index - 1
        row.update(
            nearest_nominal=nearest.isoformat(),
            nearest_offset_seconds=offset,
            previous_nominal=clocks[previous_index].isoformat() if previous_index >= 0 else None,
            next_nominal=clocks[index].isoformat() if index < len(clocks) else None,
            timing_bin=timing_bin(offset),
            timing_basis="OBSERVATION_TIME_KNOWN_ARCHIVED_ROUTINE_REPORT",
            nominal_gap_warning=abs(offset) > 1800,
            boundary_uncertain_1s=any(
                abs(offset - v) <= 1 for v in (-300, -180, -60, -30, 0, 30, 60, 180, 300)
            ),
        )
    else:
        row.update(
            nearest_offset_seconds=None,
            nearest_nominal=None,
            previous_nominal=None,
            next_nominal=None,
            timing_bin="UNKNOWN",
            timing_basis="NO_HISTORICAL_REPORT_WITHIN_60_MINUTES",
        )
    row["previous_offset_seconds"] = (
        (at - utc(row["previous_nominal"])).total_seconds() if row.get("previous_nominal") else None
    )
    row["next_offset_seconds"] = (
        (at - utc(row["next_nominal"])).total_seconds() if row.get("next_nominal") else None
    )
    row.update(receipt_context(reports, at, row.get("nearest_nominal")))


def annotate(directory: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if digest(FROZEN) != EXPECTED_SHA:
        raise ValueError("Frozen EXP0012 dataset changed")
    manifest = json.loads((directory / "snapshot_manifest.json").read_text(encoding="utf-8"))
    extracted = Path(manifest["trader"]["snapshot"])
    if digest(extracted) != manifest["trader"]["sha256"]:
        raise ValueError("Extract checksum mismatch")
    baseline = trades_at(FROZEN)
    baseline_ids = {t["trade_id"] for t in baseline}
    trades = deduplicate(baseline + trades_at(extracted))
    if any(t["trader_wallet"].lower() != WALLET for t in trades):
        raise ValueError("Wrong wallet in evidence")
    enriched = json.loads((directory / "markets.json").read_text(encoding="utf-8"))
    connection = readonly_connection(extracted)
    try:
        enriched["markets"].extend(
            dict(market=json.loads(payload), received_at=received, raw_hash=raw_hash)
            for payload, received, raw_hash in connection.execute(
                "SELECT payload,received_at,payload_hash FROM events WHERE kind='MARKET' ORDER BY id"
            )
        )
    finally:
        connection.close()
    meta = metadata_for(trades, enriched)
    all_reports = load_reports(directory)
    by_station: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for report in all_reports:
        by_station[report["station_icao"]].append(report)
    # IEM's 3/4 are hourly/nonhourly heuristics, NOT original ICAO types.
    # Derive recurring nominal minute candidates; retain type uncertainty.
    report_lookup: dict[tuple[str, datetime], list[dict[str, Any]]] = defaultdict(list)
    for report in all_reports:
        report_lookup[(report["station_icao"], utc(report["event_time"]))].append(report)
    cadences = {}
    clocks = {}
    strict_clocks = {}
    hourly_clocks = {}
    for station_code, reports in by_station.items():
        candidates = [r for r in reports if r["product_type"] != "SPECI"]
        counts = Counter(t.minute for t in {utc(r["event_time"]) for r in candidates})
        peak = max(counts.values(), default=0)
        minutes = sorted(m for m, n in counts.items() if n >= max(24, peak * 0.5))
        if len(minutes) > 4:
            minutes = []
        filtered = [r for r in candidates if utc(r["event_time"]).minute in minutes]
        inferred = cadence([dict(r, product_type="METAR") for r in filtered])
        inferred["status"] = "INFERRED_RECURRING_NOMINAL_MINUTES_TYPE_UNVERIFIED"
        inferred["source_minute_counts"] = dict(counts)
        cadences[station_code] = inferred
        clocks[station_code] = sorted({utc(r["event_time"]) for r in filtered})
        strict_clocks[station_code] = sorted(
            {utc(r["event_time"]) for r in reports if r["product_type"] == "METAR"}
        )
        hourly_clocks[station_code] = sorted(
            {
                utc(r["event_time"])
                for r in reports
                if r.get("archive_report_type") == "3" or r["product_type"] == "METAR"
            }
        )
    # Existing audited FIFO reconstruction retains uncertain opening inventory.
    nontrade: set[str] = set()
    for evidence_db in (FROZEN, extracted):
        connection = readonly_connection(evidence_db)
        try:
            for (value,) in connection.execute("SELECT payload FROM events WHERE kind='ACTIVITY'"):
                activity = json.loads(value).get("source_record", {})
                if activity.get("type") != "TRADE":
                    nontrade.add(str(activity.get("token_id")))
        finally:
            connection.close()
    lots, _, _ = reconstruct(trades, nontrade)
    lot_map = {lot["trade_id"]: lot for lot in lots}
    sells: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        if trade["side"] == "SELL":
            sells[trade["token_id"]].append(trade)
    roles = {r["trade_id"]: r for r in read_csv(OUTPUT / "hightemptation_maker_taker.csv")}
    chain_path = OUTPUT / "hightemptation_matching_paths.csv"
    chain = read_csv(chain_path)
    rows = []
    for trade in trades:
        metadata = meta[trade["token_id"]]
        if (
            trade["side"] != "BUY"
            or str(trade.get("outcome")).lower() != "no"
            or metadata["market_kind"] not in ("TMAX", "TMIN")
        ):
            continue
        at = utc(trade["source_trade_timestamp"])
        station = metadata.get("reference_station")
        schedule = cadences.get(str(station), {})
        timezone = metadata.get("timezone")
        row = {
            **trade,
            **metadata,
            "station": station,
            "execution_group": execution_key(trade),
            "population": "FROZEN_EXP0012"
            if trade["trade_id"] in baseline_ids
            else "NEW_SNAPSHOT_EXTENSION",
            "price_bucket": price_bucket(trade["price"]),
            "exact_source_price": trade["price"],
            "price_semantics": "API_ECONOMIC_ROW_PRICE_NOT_PROVEN_SINGLE_ORDER_TICK",
            "local_trade_time": at.astimezone(ZoneInfo(timezone)).isoformat() if timezone else None,
            "local_hour": at.astimezone(ZoneInfo(timezone)).hour if timezone else None,
            "schedule_minutes": schedule.get("minutes", []),
            "schedule_status": schedule.get("status", "UNKNOWN"),
            "public_release_status": "PUBLIC_RELEASE_TIME_UNKNOWN",
            "order_submission_time": None,
            "minutes_to_settlement_day_end": (
                utc(metadata["settlement_day_end_utc"]) - at
            ).total_seconds()
            / 60
            if metadata.get("settlement_day_end_utc")
            else None,
            "minutes_to_city_day_end_unverified": None,
            "prior_metar_made_NO_likely": "UNKNOWN_SETTLEMENT_MAPPING_OR_PRETRADE_INFORMATION",
            "pws_asof": "UNKNOWN_NOT_RECONSTRUCTED_FROM_LATER_DATA",
            "forecast_asof": "UNKNOWN_NOT_RECONSTRUCTED_FROM_LATER_DATA",
            "pre_entry_book": "UNKNOWN_NO_COMPLETE_CONTEMPORANEOUS_HISTORY",
            "net_pnl": None,
        }
        if metadata.get("market_date") and timezone:
            _, end = day_bounds(datetime.fromisoformat(metadata["market_date"]).date(), timezone)
            row["minutes_to_city_day_end_unverified"] = (end - at).total_seconds() / 60
        row.update(schedule_offsets(at, row["schedule_minutes"]))
        row["projected_schedule_offset_seconds"] = row.get("nearest_offset_seconds")
        align_reports(row, by_station.get(str(station), []), clocks.get(str(station), []))
        row["timing_basis"] = "OBSERVED_NOMINAL_RECURRING_SERIES_ICAO_REPORT_TYPE_UNVERIFIED"
        primary_clock = utc(row["nearest_nominal"]) if row.get("nearest_nominal") else None
        matched_reports = (
            report_lookup.get((str(station), primary_clock), []) if primary_clock else []
        )
        row["nominal_report_type_verified"] = any(
            r["product_type"] == "METAR" for r in matched_reports
        )
        row["nearest_report_raw_texts"] = list(
            dict.fromkeys(r["raw_text"] for r in matched_reports)
        )
        for label, series in (
            ("strict_original_type", strict_clocks),
            ("iem_hourly_only", hourly_clocks),
        ):
            alternative = dict(row)
            align_reports(alternative, [], series.get(str(station), []))
            row[label + "_offset_seconds"] = alternative.get("nearest_offset_seconds")
        lot = lot_map.get(trade["trade_id"], {})
        future_sells = [
            r for r in sells[trade["token_id"]] if utc(r["source_trade_timestamp"]) > at
        ]
        first_sell = min(future_sells, key=lambda r: utc(r["source_trade_timestamp"]), default=None)
        row.update(
            first_opposite_sell_time=first_sell["source_trade_timestamp"] if first_sell else None,
            first_opposite_sell_seconds=(
                utc(first_sell["source_trade_timestamp"]) - at
            ).total_seconds()
            if first_sell
            else None,
            first_opposite_sell_price=first_sell["price"] if first_sell else None,
            conditional_full_closure=bool(lot.get("fully_closed")),
            conditional_holding_seconds=lot.get("holding_seconds"),
            conditional_sell_vwap=str(lot["sell_vwap"])
            if lot.get("sell_vwap") is not None
            else None,
            conditional_gross_pnl=str(lot["gross_pnl"])
            if lot.get("gross_pnl") is not None
            else None,
            conditional_fifo_eligible=bool(lot.get("primary_eligible")),
            inventory_status=lot.get("opening_inventory_status", "UNKNOWN"),
            inventory_integrity_flags=lot.get("integrity_flags", []),
            order_role=roles.get(trade["trade_id"], {}).get("role", "UNKNOWN"),
        )
        for proof in chain:
            if (
                proof.get("transaction_hash", "").lower() == trade["transaction_hash"].lower()
                and proof.get("token_id") == trade["token_id"]
                and proof.get("side") == trade["side"]
                and Decimal(proof.get("quantity", "-1")) == Decimal(trade["size"])
            ):
                row.update(
                    order_role=proof.get("role"),
                    block_number=proof.get("block_number"),
                    log_position=proof.get("matched_log_index"),
                    matching_path=proof.get("matching_path"),
                    chain_fee_evidence=proof.get("zero_exchange_fee_verified"),
                )
        row["exit_status"] = (
            "CONDITIONAL_FIFO_CLOSED" if row["conditional_full_closure"] else "UNRECONCILED_OR_OPEN"
        )
        rows.append(row)
    manifest.update(
        cadences=cadences,
        raw_trade_rows=len(trades),
        frozen_trade_rows=len(baseline),
        no_buy_rows=len(rows),
        source_time_start=trades[0]["source_trade_timestamp"],
        source_time_end=trades[-1]["source_trade_timestamp"],
        metar_rows=len(all_reports),
        reports_by_type=dict(Counter(r["product_type"] for r in all_reports)),
    )
    return rows, manifest


def execution_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [
        r for r in rows if r.get("conditional_full_closure") and r.get("conditional_fifo_eligible")
    ]
    first = [
        r["first_opposite_sell_seconds"]
        for r in rows
        if r.get("first_opposite_sell_seconds") is not None
    ]
    holding = [
        r["conditional_holding_seconds"]
        for r in closed
        if r.get("conditional_holding_seconds") is not None
    ]
    gross = [
        Decimal(r["conditional_gross_pnl"])
        for r in closed
        if r.get("conditional_gross_pnl") is not None
    ]
    return dict(
        conditional_fifo_closed_n=len(closed),
        first_later_sell_n=len(first),
        median_first_later_sell_seconds=median(first) if first else None,
        median_conditional_full_closure_seconds=median(holding) if holding else None,
        closed_gross_loss_n=sum(v < 0 for v in gross),
        closed_gross_pnl=str(sum(gross)) if gross else None,
        unrealized_pnl=None,
        net_pnl=None,
        inventory_note="CONDITIONAL_FIFO_NOT_VERIFIED_OPENING_INVENTORY; FIRST_SELL_NOT_PROVEN_LOT_EXIT",
    )


def group_view(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result = summarize(rows)
    result["price_groups"] = [
        dict(price_bucket=bucket, **summarize([r for r in rows if r["price_bucket"] == bucket]))
        for bucket in sorted({r["price_bucket"] for r in rows})
    ]
    for item in result["price_groups"]:
        item["within_60s_pct"] = item["percentages"]["within_60s"]
        item.update(
            execution_summary([r for r in rows if r["price_bucket"] == item["price_bucket"]])
        )
    result["execution_summary"] = execution_summary(rows)
    result["control"] = phase_contrast(rows)
    result["control_day_sensitivity"] = phase_contrast(rows, cluster_by="settlement_day")
    result["nominal_type_unverified_n"] = sum(
        r.get("nearest_offset_seconds") is not None and not r.get("nominal_report_type_verified")
        for r in rows
    )
    result["strict_original_type_aligned_n"] = sum(
        r.get("strict_original_type_offset_seconds") is not None for r in rows
    )
    result["archive_hourly_only_sensitivity"] = summarize(
        [
            dict(
                r,
                nearest_offset_seconds=r["iem_hourly_only_offset_seconds"],
                timing_bin=timing_bin(r["iem_hourly_only_offset_seconds"]),
            )
            for r in rows
            if r.get("iem_hourly_only_offset_seconds") is not None
        ]
    )
    result["exits"] = dict(
        first_sell_known_n=sum(r["first_opposite_sell_time"] is not None for r in rows),
        conditional_full_closure_n=sum(r["conditional_full_closure"] for r in rows),
        sold_at_099_n=sum(
            r["conditional_sell_vwap"] is not None
            and abs(Decimal(r["conditional_sell_vwap"]) - Decimal(".99")) <= Decimal(".000001")
            for r in rows
        ),
        inventory_status="UNKNOWN_OPENING_INVENTORY_CONDITIONAL_FIFO_ONLY",
    )
    result["examples"] = [
        {
            k: r.get(k)
            for k in (
                "source_trade_timestamp",
                "station",
                "price",
                "nearest_offset_seconds",
                "first_metar_receipt",
                "transaction_hash",
                "exit_status",
            )
        }
        for r in rows[-10:]
    ]
    return result


def plots(rows: list[dict[str, Any]], output: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    scheduled = [r for r in rows if r.get("nearest_offset_seconds") is not None]
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), constrained_layout=True)
    axes[0, 0].hist(
        [r["nearest_offset_seconds"] / 60 for r in scheduled], bins=range(-31, 32), color="#267d98"
    )
    axes[0, 0].set(
        xlabel="Execution minus recurring nominal report (minutes; ICAO type uncertain)",
        ylabel="Economic rows",
        title=f"Historical nominal alignment (N={len(scheduled)})",
    )
    xs = [r["nearest_offset_seconds"] / 60 for r in scheduled if r["local_hour"] is not None]
    ys = [r["local_hour"] for r in scheduled if r["local_hour"] is not None]
    axes[0, 1].hist2d(xs, ys, bins=[range(-31, 32), range(25)], cmap="Blues")
    axes[0, 1].set(
        xlabel="Nominal offset (minutes)",
        ylabel="Airport local hour",
        title="Counts, not matched activity rates",
    )
    frequencies = Counter(r["price_bucket"] for r in rows)
    axes[1, 0].barh(list(frequencies), list(frequencies.values()), color="#267d98")
    axes[1, 0].set(title="NO BUY price partitions", xlabel="Economic rows")
    axes[1, 1].hist(
        [
            r["minutes_to_settlement_day_end"] / 60
            for r in rows
            if r["minutes_to_settlement_day_end"] is not None
            and -24 <= r["minutes_to_settlement_day_end"] / 60 <= 72
        ],
        bins=48,
        color="#267d98",
    )
    axes[1, 1].set(
        xlabel="Hours to rule-supported local day end (not resolution)",
        title="Known boundaries only",
    )
    fig.suptitle("EXP0017 / NO 0.90-0.99 - execution is not order submission; publication unknown")
    fig.savefig(output / "entry_timing_overview.png", dpi=150)
    plt.close(fig)


def run(directory: Path = DATA, output: Path = OUTPUT) -> dict[str, Any]:
    rows, manifest = annotate(directory)
    output.mkdir(parents=True, exist_ok=True)
    primary = [r for r in rows if Decimal(".90") <= Decimal(r["price"]) <= Decimal(".99")]
    groups = {
        "ALL": group_view(primary),
        "EPWA": group_view([r for r in primary if r.get("station") == "EPWA"]),
        "ALL_PRICES_CONTROL": group_view(rows),
        "EPWA_ALL_PRICES_CONTROL": group_view([r for r in rows if r.get("station") == "EPWA"]),
    }
    airports = [
        dict(
            airport=station,
            **group_view([r for r in primary if (r.get("station") or "UNKNOWN") == station]),
        )
        for station in sorted({r.get("station") or "UNKNOWN" for r in rows})
    ]
    publication = directory / "analysis_manifest_v1_1.json"
    inputs = {
        str(p.name): digest(p)
        for p in (
            directory / "markets.json",
            directory / "metars.json",
            directory / "snapshot_manifest.json",
        )
    }
    if publication.exists():
        publication_data = json.loads(publication.read_text(encoding="utf-8"))
        if publication_data["input_hashes"] != inputs:
            raise ValueError(
                "Analysis input changed; preserve prior analysis manifest and create a new revision"
            )
    else:
        publication_data = dict(published_at=datetime.now(UTC).isoformat(), input_hashes=inputs)
        publication.write_text(json.dumps(publication_data, indent=2), encoding="utf-8")
    published = publication_data["published_at"]
    catalog = dict(
        version=VERSION,
        published_at=published,
        snapshot_cutoff=manifest["snapshot_cutoff"],
        source_rows=len(rows),
        scope="PRIMARY: 0.90<=NO BUY<=0.99; all-price controls separate. Recurring nominal archive series, original ICAO types unverified; local receipts separate",
        groups=groups,
        limitations=[
            "Execution/block timestamps are not order creation or decision times.",
            "Historical metadata and METAR backfills do not establish historical public availability.",
            "No complete market-wide matched price/liquidity activity denominator; uniform phase contrast is descriptive only.",
            "Conditional FIFO is not verified opening inventory or net profitability.",
            "Some station mappings, archive reports, publication times and contemporaneous weather/books remain UNKNOWN.",
            "IEM strips original METAR/SPECI prefixes; hourly/nonhourly classes are not authoritative ICAO types. Primary alignment uses recurring nominal-minute candidates, not verified routine type; hourly-only sensitivity separately available.",
        ],
    )
    write_csv(output / "entry_timing.csv", rows)
    write_csv(
        output / "entry_timing_by_time_bin.csv",
        [
            dict(
                timing_bin=key,
                **summarize([r for r in rows if r["timing_bin"] == key]),
                **execution_summary([r for r in rows if r["timing_bin"] == key]),
            )
            for key in sorted({r["timing_bin"] for r in rows})
        ],
    )
    write_csv(
        output / "entry_timing_by_local_hour.csv",
        [
            dict(
                local_hour=hour,
                n=sum(r["local_hour"] == hour for r in rows),
                exact_098_n=sum(
                    r["local_hour"] == hour and r["price_bucket"] == "EXACT_0.98" for r in rows
                ),
            )
            for hour in range(24)
        ],
    )
    write_csv(output / "entry_timing_by_airport.csv", airports)
    write_csv(output / "entry_timing_by_price.csv", groups["ALL"]["price_groups"])

    def proximity(r: dict[str, Any]) -> str:
        return (
            "UNKNOWN"
            if r.get("minutes_to_settlement_day_end") is None
            else "AFTER_DAY_END"
            if r["minutes_to_settlement_day_end"] < 0
            else "0_TO_1H"
            if r["minutes_to_settlement_day_end"] <= 60
            else "1_TO_3H"
            if r["minutes_to_settlement_day_end"] <= 180
            else "3_TO_6H"
            if r["minutes_to_settlement_day_end"] <= 360
            else "6_TO_12H"
            if r["minutes_to_settlement_day_end"] <= 720
            else "OVER_12H"
        )

    write_csv(
        output / "entry_timing_by_settlement_proximity.csv",
        [
            dict(proximity=key, **group_view([r for r in rows if proximity(r) == key]))
            for key in sorted({proximity(r) for r in rows})
        ],
    )
    write_csv(
        output / "entry_timing_matched_controls.csv",
        [dict(airport=r["airport"], **r["control"]) for r in airports],
    )
    examples: list[dict[str, Any]] = []
    for key in ("CONDITIONAL_FIFO_CLOSED", "UNRECONCILED_OR_OPEN"):
        cohort = [r for r in rows if r["exit_status"] == key]
        for bucket in sorted({r["price_bucket"] for r in cohort}):
            selected = [r for r in cohort if r["price_bucket"] == bucket]
            examples.extend(selected[:2])
    examples.extend([r for r in rows if r.get("station") == "EPWA"][:5])
    examples.extend(
        [
            dict(r, representative_category="CONDITIONAL_GROSS_LOSS")
            for r in rows
            if r.get("conditional_gross_pnl") is not None
            and Decimal(r["conditional_gross_pnl"]) < 0
        ][:3]
    )
    examples.extend(
        [
            dict(r, representative_category="INVENTORY_AMBIGUOUS")
            for r in rows
            if r.get("inventory_integrity_flags")
        ][:3]
    )
    examples.extend(
        [
            dict(r, representative_category="CHAIN_VERIFIED_EXECUTION")
            for r in rows
            if r.get("order_role") == "CHAIN_VERIFIED_TAKER"
        ][:3]
    )
    examples.extend(
        [
            dict(r, representative_category="EHAM_BEFORE_NOMINAL_PUBLICATION_UNKNOWN")
            for r in rows
            if r.get("station") == "EHAM"
        ][-3:]
    )
    examples = list({r["trade_id"]: r for r in examples}.values())
    write_csv(output / "entry_timing_execution_examples.csv", examples)
    (output / "entry_timing_summary.json").write_text(
        json.dumps(catalog, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )
    (output / "entry_timing_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )
    # Atomic replacement read by the existing static mount; no ASGI restart.
    static = ROOT / "src/premetar/dashboard/static/entry_timing_summary.json"
    temp = static.with_suffix(".tmp")
    temp.write_text(json.dumps(catalog, sort_keys=True, default=str), encoding="utf-8")
    temp.replace(static)
    plots(primary, output)
    write_report(output, catalog, airports, examples, manifest)
    return catalog


def write_report(
    output: Path,
    catalog: dict[str, Any],
    airports: list[dict[str, Any]],
    examples: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> None:
    all_rows = catalog["groups"]["ALL"]
    text = f"# EXP0017 — HighTempTation METAR entry timing\n\nVersion `{VERSION}`. Frozen EXP0012 + independently frozen current extract.\nSnapshot cutoff {catalog['snapshot_cutoff']}; historical source backfills available no earlier than {catalog['published_at']}.\n\n"
    text += "**Execution time is not order submission or trader decision time. Nominal METAR time is not public release.**\n\n"
    text += f"## Population\n\n{all_rows['n']} weather NO BUY rows; {all_rows['independent_executions']} transaction/token execution clusters (not proven parent orders). {all_rows['schedule_n']} align with archived recurring nominal candidates (original ICAO type unverified); {all_rows['unknown_station_n']} unknown exact stations. Baseline frozen raw trade rows {manifest['frozen_trade_rows']}; merged raw economic rows {manifest['raw_trade_rows']}.\n\n"
    text += f"**Main price population: 0.90 <= p <= 0.99. All-price control has {catalog['groups']['ALL_PRICES_CONTROL']['n']} rows. {all_rows['nominal_type_unverified_n']} primary alignments have unverified original ICAO report type; strict original-type aligned count is {all_rows['strict_original_type_aligned_n']}.**\n\n"
    text += "IEM's hourly/nonhourly classes do not certify routine versus SPECI. Recurring minute candidates use unique nominal timestamps: at least24 occurrences and at least half the dominant minute frequency, maximum4slots. This source-quality correction is not a tuned trading rule. Raw unknown types stay unknown; off-cadence records are excluded from primary timing.\n\n"
    text += (
        "Hourly-only sensitivity (NOT authoritative routine): "
        + json.dumps(all_rows["archive_hourly_only_sensitivity"], ensure_ascii=False)
        + "\n\n"
    )
    text += "Source-quality correction: upstream IEM hourly/reset-time heuristics cannot certify ICAO METAR/SPECI. Earlier prototype counts are not final routine-METAR evidence. Strict type-verified historical analysis is insufficient; recurring-nominal candidate analysis and hourly-only sensitivity are descriptive.\n\n"
    text += "## Mandatory questions\n\n"
    p = all_rows["percentages"]
    text += f"1. Within ±30s / ±60s / ±180s: {p['within_30s']}% / {p['within_60s']}% / {p['within_180s']}%, denominator {all_rows['schedule_n']} economic rows. Unknown alignments excluded explicitly. Whole-second timestamps make threshold membership uncertain within1s.\n"
    text += f"2. Before / after / exact nominal: {p['before']}% / {p['after']}% / {p['exact_nominal']}%; median signed offset {all_rows['median_offset_seconds']}s.\n"
    text += f"3. Matched background clustering: **NOT IDENTIFIABLE**. {json.dumps(all_rows['control'], ensure_ascii=False)}\n"
    exact: dict[str, Any] = next(
        (r for r in all_rows["price_groups"] if r["price_bucket"] == "EXACT_0.98"), {}
    )
    text += f"4. Exactly0.98 (strict Decimal equality, no near-tick merging): {json.dumps(exact, ensure_ascii=False)}\n"
    text += "5. Time-to-settlement uses rule-supported local day end only; closedTime/endDate are not certified final-resolution times. Price-specific medians below; unknown boundaries remain missing.\n"
    text += f"6. Airport heterogeneity: {len(airports) - int(any(r['airport'] == 'UNKNOWN' for r in airports))} exact station groups; see full table and CSV. All-airport pattern cannot be transferred to EPWA.\n"
    text += f"7. Target first local receipt known {all_rows['receipt_known_n']}; target received before/at source trade {all_rows['known_before_trade_n']}. Earliest trustworthy local source receipt, not historical archive receipt. Freshness and coverage still matter.\n"
    text += "8. Price movement vs price level: historical pre-entry book/market-wide transaction denominator generally absent; cannot separate momentum/imbalance from price selection. Prospective sidecar records controls without new external polling.\n"
    text += "9. Immediate exit-order placement: **UNOBSERVABLE**. Later SELL execution and conditional FIFO closure are not submission evidence. Opening inventory unknown; net costs not established.\n"
    text += "10. H1–H8 remain competing explanations; descriptive timing may support association but cannot establish METAR anticipation, access or causation. No profitable strategy/edge is established.\n\n"
    text += "## By airport (observed nominal reports, economic-row denominator)\n\n|Station|NO buys|Aligned|±60s %|Before %|After %|Median offset s|First local receipt known|\n|---|---:|---:|---:|---:|---:|---:|---:|\n"
    for row in airports:
        text += f"|{row['airport']}|{row['n']}|{row['schedule_n']}|{row['percentages']['within_60s']}|{row['percentages']['before']}|{row['percentages']['after']}|{row['median_offset_seconds']}|{row['receipt_known_n']}|\n"
    text += "\n## Price and day-end cohorts\n\n|Price bucket|Rows|Aligned|±60s %|Median signed s|Median minutes until rule-supported day end|\n|---|---:|---:|---:|---:|---:|\n"
    for row in all_rows["price_groups"]:
        text += f"|{row['price_bucket']}|{row['n']}|{row['schedule_n']}|{row['percentages']['within_60s']}|{row['median_offset_seconds']}|{row['median_minutes_to_day_end']}|\n"
    text += (
        "\n## Execution evidence\n\n"
        + json.dumps(all_rows["exits"], indent=2)
        + "\n\nConditional gross-only FIFO; fees/gas, prior inventory, open remainder and simultaneous records prohibit claiming verified net profits. Known Ankara BUY/BUY mint entry and taker SELL proof is joined only by exact transaction/token/side/quantity. Unknown block/log fields stay NULL. Exact prices may be economic-row VWAPs.\n\n"
    )
    text += "## Representative real records\n\nSelection is deterministic: first two in each price/closure cell, first five EPWA, first three conditional gross losses and ambiguous cases, exact chain-proven entries, and last three EHAM. Not maximum-profit examples. Full identifiers/roles/flags in execution_examples CSV.\n\n|UTC execution|Station|Price|Nominal offset s|First later SELL s|Conditional gross PnL|Status|\n|---|---|---:|---:|---:|---:|---|\n"
    for row in examples:
        text += f"|{row['source_trade_timestamp']}|{row.get('station')}|{row['price']}|{row.get('nearest_offset_seconds')}|{row.get('first_opposite_sell_seconds')}|{row.get('conditional_gross_pnl')}|{row['exit_status']}|\n"
    text += "\n## Method, clocks and unknowns\n\nSee docs/research/EXP0017_PROTOCOL.md and SOURCES.md. Every trade belongs to one exclusive price partition and one offset bin or UNKNOWN. Raw TAC/COR and IEM hourly classes are preserved; original METAR/SPECI prefix is absent in all archived rows. No unknown report is certified routine. Nearest actually archived recurring nominal candidate within60min, tie earlier; missing reports create uncertainty, no synthetic timestamps. Cadence/projection exposed separately. Current parsed rule descriptions are exact-contract retrospective identity, never proof trader knew them earlier. Forecast/PWS/book context absent at source time stays UNKNOWN; archived later records never fill that gap. Uniform-phase descriptive contrast is not a matched market-activity test; correlated fills are grouped and uncertainty resamples settlement dates. Missing complete price/liquidity/market-lifecycle denominators prevents a causal or significance claim. Final resolution time remains unknown when only a market closed timestamp is returned.\n\n"
    text += "Sources: [Polymarket market metadata](https://docs.polymarket.com/api-reference/markets/list-markets), [public trade feed](https://data-api.polymarket.com/v2/docs), [IEM raw METAR archive](https://mesonet.agron.iastate.edu/request/download.phtml), [AWC API](https://aviationweather.gov/data/api/). IEM is a university archive of reports, not a verified historical publication clock.\n\n"
    text += "Reproduce: `uv run python -m scripts.research.hightemptation_entry_timing`; source network capture is separate and cached. Reports and static JSON regenerate from frozen files; no collector data modified. New sidecar is public-record observation only, with startup/gap censoring, independent storage and bounded rings. No order execution or model changes.\n"
    (output / "exp0017_hightemptation_metar_entry_timing.md").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="store_true")
    args = parser.parse_args()
    if args.capture:
        print(json.dumps(capture(), indent=2))
    else:
        result = run()
        print(
            json.dumps(
                {
                    k: result["groups"]["ALL"][k]
                    for k in ("n", "schedule_n", "percentages", "median_offset_seconds", "control")
                },
                indent=2,
            )
        )
