"""EXP0012 deterministic offline forensics; never modifies either running service."""

import argparse
import csv
import hashlib
import json
import random
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts.research.exp0012_bucket_helpers import price_bucket
from scripts.research.hightemptation_books import audit_books, decode_v2_receipt, role_evidence
from scripts.research.hightemptation_charts import render
from scripts.research.hightemptation_inventory import reconstruct
from scripts.research.hightemptation_matching_paths import matching_paths
from scripts.research.hightemptation_metadata import load_market_metadata, trade_local_context

FROZEN_TRADER_SHA = "6cddb1ee11e6a30d9bc9fac15ba659eb1a1a57045c7809e19db2bca3d3709b89"
FROZEN_WEATHER_SHA = "5f3d063bad70795ecdd15f06f0fc0f6d1b965a4c81d4ec8a52395d4266c73d5e"


def csv_write(path: Path, rows: list[dict[str, Any]]) -> None:
    keys = sorted({key for row in rows for key in row}) or ["status"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    k: json.dumps(v, sort_keys=True, default=str)
                    if isinstance(v, (dict, list))
                    else str(v)
                    if isinstance(v, Decimal)
                    else v
                    for k, v in row.items()
                }
            )


def average(values: list[Any]) -> float | None:
    return statistics.mean(float(v) for v in values) if values else None


def median(values: list[Any]) -> float | None:
    return statistics.median(float(v) for v in values) if values else None


def pct(value: Any) -> str:
    return f"{100 * float(value):.2f}" if value is not None else "UNKNOWN"


def cluster_interval(lots: list[dict[str, Any]], seconds: int) -> dict[str, Any]:
    blocks: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for lot in lots:
        block = lot["source_trade_timestamp"][:10]
        blocks[block][0] += int(lot["fully_closed"] and lot["holding_seconds"] <= seconds)
        blocks[block][1] += 1
    if len(blocks) < 20:
        return {"days": len(blocks), "low": None, "high": None, "status": "INSUFFICIENT_DAYS"}
    rng = random.Random(12)
    groups = list(blocks.values())
    ratios = []
    for _ in range(2000):
        selected = rng.choices(groups, k=len(groups))
        ratios.append(sum(v[0] for v in selected) / sum(v[1] for v in selected))
    ratios.sort()
    return {
        "days": len(blocks),
        "low": ratios[49],
        "high": ratios[1949],
        "status": "DESCRIPTIVE_UTC_DAY_BLOCK_BOOTSTRAP_NOT_CAUSAL",
        "replicates": 2000,
        "seed": 12,
    }


def closure_summary(lots: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [lot for lot in lots if lot["fully_closed"]]
    shares = sum((lot["buy_size"] for lot in lots), Decimal(0))
    result: dict[str, Any] = {
        "eligible_buy_lots": len(lots),
        "fully_closed": len(closed),
        "not_fully_closed": len(lots) - len(closed),
        "median_holding_seconds_closed": median([x["holding_seconds"] for x in closed]),
        "verified_opening_balances": 0,
        "accounting": "CONDITIONAL_CLEAN_TRADE_FEED_FIFO",
    }
    for seconds in (5, 10, 30, 60):
        count = sum(lot["holding_seconds"] <= seconds for lot in closed)
        result[str(seconds)] = {
            "closed_count": count,
            "fraction_of_all_eligible": count / len(lots) if lots else None,
            "fraction_of_closed": count / len(closed) if closed else None,
            "share_quantity_closed_fraction": float(
                sum((lot[f"close_quantity_by_{seconds}s"] for lot in lots), Decimal(0)) / shares
            )
            if shares
            else None,
            "uncertainty": cluster_interval(lots, seconds),
        }
    return result


def aggregate(lots: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [lot for lot in lots if lot["primary_eligible"]]
    closed = [lot for lot in eligible if lot["fully_closed"]]
    gross = [lot["gross_pnl"] for lot in closed if lot["gross_pnl"] is not None]
    partial = [lot for lot in eligible if not lot["fully_closed"] and lot["gross_pnl"] is not None]
    matched = [lot for lot in eligible if lot["matched_quantity"] > 0]
    all_gross = sum((lot["gross_pnl"] for lot in matched), Decimal(0))
    matched_cost = sum((lot["matched_cost"] for lot in matched), Decimal(0))
    matched_quantity = sum((lot["matched_quantity"] for lot in matched), Decimal(0))
    shares = sum((lot["buy_size"] for lot in lots), Decimal(0))
    capital = sum((lot["buy_notional"] for lot in lots), Decimal(0))
    return {
        "buy_count": len(lots),
        "eligible_lots": len(eligible),
        "closed_lots": len(closed),
        "shares": sum((lot["buy_size"] for lot in lots), Decimal(0)),
        "notional": sum((lot["buy_notional"] for lot in lots), Decimal(0)),
        "holding_median_seconds": median([lot["holding_seconds"] for lot in closed]),
        "gross_pnl": sum(gross, Decimal(0)) if gross else None,
        "partial_lots_matched_gross_pnl": sum((lot["gross_pnl"] for lot in partial), Decimal(0)),
        "all_matched_gross_pnl": all_gross if matched else None,
        "unclosed_ledger_cost": sum(
            (
                lot["inventory_exposure_unclosed_cost"]
                for lot in eligible
                if not lot["fully_closed"]
            ),
            Decimal(0),
        ),
        "entry_vwap": capital / shares if shares else None,
        "entry_trade_weighted_mean": average([lot["buy_price"] for lot in lots]),
        "capital_weighted_gross_roi_matched": all_gross / matched_cost if matched_cost else None,
        "share_weighted_price_improvement_matched": all_gross / matched_quantity
        if matched_quantity
        else None,
        "trade_weighted_gross_roi_closed": average(
            [lot["return_on_matched_capital_gross"] for lot in closed]
        ),
        "after_exchange_fee_known_lots": sum(
            lot["after_exchange_fee_pnl"] is not None for lot in closed
        ),
        "verified_exchange_fee_subset_pnl": sum(
            (
                lot["after_exchange_fee_pnl"]
                for lot in closed
                if lot["after_exchange_fee_pnl"] is not None
            ),
            Decimal(0),
        )
        if any(lot["after_exchange_fee_pnl"] is not None for lot in closed)
        else None,
        "net_pnl": None,
        "net_status": "HISTORICAL_FEES_OR_TOTAL_EXECUTION_COST_UNKNOWN",
        "buy_role_counts": dict(Counter(lot["buy_role"] for lot in lots)),
        "gross_positive_closed": sum(value > 0 for value in gross),
        "gross_negative_closed": sum(value < 0 for value in gross),
        "gross_flat_closed": sum(value == 0 for value in gross),
        "quantity_weighted_holding_seconds": float(
            sum((lot["quantity_time_sum"] for lot in eligible), Decimal(0))
            / sum((lot["matched_quantity"] for lot in eligible), Decimal(0))
        )
        if any(lot["matched_quantity"] for lot in eligible)
        else None,
    }


def load_weather_reference(snapshot: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(snapshot.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT station_icao,event_time,collector_receive_time,temperature_c FROM observations WHERE product_type='METAR' AND temperature_c IS NOT NULL"
            )
        ]
    finally:
        conn.close()


def temporal_rows(
    lots: list[dict[str, Any]],
    metadata: dict[str, dict[str, Any]],
    weather: list[dict[str, Any]],
    cutoff: datetime,
) -> list[dict[str, Any]]:
    rows = []
    by_station: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for obs in weather:
        by_station[obs["station_icao"]].append(obs)
    for lot in lots:
        context = trade_local_context(lot, metadata[lot["token_id"]])
        clock = datetime.fromisoformat(lot["source_trade_timestamp"])
        context.update(
            local_time=context["local_trade_time"],
            temporal_identity_status=context["timezone_status"],
            outcome=lot.get("outcome"),
            price=lot["buy_price"],
            shares=lot["buy_size"],
            notional=lot["buy_notional"],
            expected_tmax_time=None,
            metar_alignment_status="UNAVAILABLE",
            recorded_metar_subset_maximum_c=None,
            recorded_metar_subset_first_maximum_time=None,
            reference_subset_is_completed_day=False,
        )
        local_date = context["local_time"][:10] if context["local_time"] else None
        context["local_trade_date"] = local_date
        context["same_city_calendar_day_as_market"] = (
            local_date == context["market_date"] if local_date and context["market_date"] else None
        )
        station = context.get("reference_station")
        zone = context.get("timezone")
        day = context.get("market_date")
        if station and zone and day:
            selected = [
                obs
                for obs in by_station.get(station, [])
                if datetime.fromisoformat(obs["event_time"].replace("Z", "+00:00"))
                .astimezone(ZoneInfo(zone))
                .date()
                .isoformat()
                == day
            ]
            if selected:
                highest = max(float(obs["temperature_c"]) for obs in selected)
                first = min(
                    obs["event_time"] for obs in selected if float(obs["temperature_c"]) == highest
                )
                context["recorded_metar_subset_maximum_c"] = highest
                context["recorded_metar_subset_first_maximum_time"] = first
                context["reference_subset_is_completed_day"] = bool(
                    context.get("city_calendar_day_end_utc")
                    and datetime.fromisoformat(context["city_calendar_day_end_utc"]) < cutoff
                )
                nearest = min(
                    selected,
                    key=lambda obs: abs(
                        (
                            datetime.fromisoformat(obs["event_time"].replace("Z", "+00:00")) - clock
                        ).total_seconds()
                    ),
                )
                context["seconds_from_nearest_recorded_metar_nominal"] = (
                    clock - datetime.fromisoformat(nearest["event_time"].replace("Z", "+00:00"))
                ).total_seconds()
                context["metar_alignment_status"] = (
                    "RETROSPECTIVE_NOMINAL_SUBSET_NOT_PUBLICATION_OR_FINAL_TMAX"
                )
                available = [
                    obs
                    for obs in selected
                    if obs["collector_receive_time"]
                    and datetime.fromisoformat(obs["collector_receive_time"].replace("Z", "+00:00"))
                    <= clock
                ]
                context["locally_received_metar_count_at_trade"] = len(available)
        rows.append(context)
    return rows


def run(snapshot_dir: Path, output: Path) -> dict[str, Any]:
    manifest = json.loads((snapshot_dir / "manifest.json").read_text(encoding="utf-8"))
    if (
        manifest["sources"]["trader"]["sha256"] != FROZEN_TRADER_SHA
        or manifest["sources"]["weather"]["sha256"] != FROZEN_WEATHER_SHA
    ):
        raise ValueError(
            "EXP0012 is a frozen study; use a new experiment/protocol for a different data snapshot"
        )
    for source in manifest["sources"].values():
        with Path(source["snapshot"]).open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != source["sha256"]:
                raise ValueError("Snapshot hash mismatch")
    snapshot = Path(manifest["sources"]["trader"]["snapshot"])
    weather_snapshot = Path(manifest["sources"]["weather"]["snapshot"])
    conn = sqlite3.connect(snapshot.resolve().as_uri() + "?mode=ro", uri=True)
    trades = [
        json.loads(row[0])
        for row in conn.execute("SELECT payload FROM events WHERE kind='TRADE' ORDER BY id")
    ]
    nontrade = {
        str(json.loads(row[0])["source_record"].get("token_id"))
        for row in conn.execute(
            "SELECT payload FROM events WHERE kind='ACTIVITY' AND json_extract(payload,'$.source_record.type')!='TRADE'"
        )
    }
    event_counts = dict(conn.execute("SELECT kind,count(*) FROM events GROUP BY kind"))
    conn.close()
    roles = role_evidence(snapshot)
    chain = []
    for path in sorted((snapshot_dir / "rpc").glob("*.json")):
        chain.extend(decode_v2_receipt(json.loads(path.read_text(encoding="utf-8"))))
    fees = {}
    for proof in chain:
        for trade in trades:
            if (
                trade["transaction_hash"].lower() == proof["transaction_hash"].lower()
                and trade["token_id"] == proof["token_id"]
                and trade["side"] == proof["side"]
                and Decimal(trade["size"]) == Decimal(proof["quantity"])
            ):
                roles[trade["trade_id"]] = {
                    "role": proof["role"],
                    "evidence": proof["evidence"],
                    "transaction_hash": proof["transaction_hash"],
                }
                if proof["zero_exchange_fee_verified"]:
                    fees[trade["trade_id"]] = Decimal(0)
    metadata = load_market_metadata(snapshot)
    lots, matches, sales = reconstruct(trades, nontrade, fees)
    for lot in lots:
        meta = metadata[lot["token_id"]]
        lot.update(
            market_kind=meta["market_kind"],
            city=meta["city"],
            market_date=meta["market_date"],
            price_bucket=price_bucket(lot["buy_price"]),
            buy_role=roles.get(lot["trade_id"], {}).get("role", "UNKNOWN"),
        )
        exit_roles = Counter(
            roles.get(identity, {}).get("role", "UNKNOWN") for identity in lot["sell_trade_ids"]
        )
        lot["sell_roles"] = dict(exit_roles)
        lot["role_combination"] = lot["buy_role"] + "/" + ",".join(sorted(exit_roles))
        lot["holding_bucket"] = (
            "UNRESOLVED"
            if not lot["fully_closed"]
            else "<=5s"
            if lot["holding_seconds"] <= 5
            else "5–10s"
            if lot["holding_seconds"] <= 10
            else "10–30s"
            if lot["holding_seconds"] <= 30
            else "30–60s"
            if lot["holding_seconds"] <= 60
            else ">60s"
        )
    weather_lots = [lot for lot in lots if lot["market_kind"] in ("TMAX", "TMIN")]
    clean = [lot for lot in weather_lots if lot["primary_eligible"]]
    no = [lot for lot in weather_lots if str(lot.get("outcome")).lower() == "no"]
    buckets = [
        "BELOW_0.50",
        "0.50–0.70",
        "0.70–0.80",
        "0.80–0.90",
        "0.90–0.95",
        "0.95–0.98",
        "0.98–1.00",
    ]
    distributions = [
        {"price_bucket": bucket, **aggregate([lot for lot in no if lot["price_bucket"] == bucket])}
        for bucket in buckets
    ]
    timing = temporal_rows(
        lots,
        metadata,
        load_weather_reference(weather_snapshot),
        datetime.fromisoformat(manifest["sources"]["weather"]["snapshot_pinned_at"]),
    )
    time_by_id = {row["trade_id"]: row for row in timing}
    for lot in lots:
        lot["local_hour"] = time_by_id[lot["trade_id"]]["local_hour"]
        lot["city_local_hour"] = f"{lot['city']}/{lot['local_hour']}"
        lot["market_month"] = str(lot["market_date"])[:7]
    role_rows = [
        {
            "trade_id": trade["trade_id"],
            "transaction_hash": trade["transaction_hash"],
            "token_id": trade["token_id"],
            "side": trade["side"],
            "market_kind": metadata[trade["token_id"]]["market_kind"],
            "source_time": trade["source_trade_timestamp"],
            "role": roles.get(trade["trade_id"], {}).get("role", "UNKNOWN"),
            "evidence": roles.get(trade["trade_id"], {}).get("evidence"),
            "order_creation_time": None,
        }
        for trade in trades
    ]
    recent = [trade for trade in trades if trade["evidence_class"] == "PROSPECTIVE_POLL"]
    all_books = audit_books(snapshot, trades)
    book_by_id = {row["trade_id"]: row for row in all_books}
    book_rows = [book_by_id[trade["trade_id"]] for trade in recent]
    for row in all_books:
        row["role"] = roles.get(row["trade_id"], {}).get("role", "UNKNOWN")
        if row["side"] == "SELL" and row["role"] in (
            "CHAIN_VERIFIED_TAKER",
            "API_ATTRIBUTED_TAKER",
        ):
            row["sequence_classification"] = "AGGRESSIVE_TAKER_EXIT"
    for lot in lots:
        lot["pre_buy_book_status"] = book_by_id[lot["trade_id"]]["book_status"]
    closed = [lot for lot in clean if lot["fully_closed"]]
    positive = sorted(
        (lot for lot in closed if lot["gross_pnl"] > 0), key=lambda lot: lot["gross_pnl"]
    )
    negative = sorted(
        (lot for lot in closed if lot["gross_pnl"] < 0), key=lambda lot: lot["gross_pnl"]
    )
    choices: list[tuple[str, dict[str, Any]]] = []
    if positive:
        choices.append(("TYPICAL_POSITIVE_CONDITIONAL_FIFO", positive[len(positive) // 2]))
    negative_no = [lot for lot in negative if str(lot.get("outcome")).lower() == "no"]
    if negative_no:
        choices.append(("TYPICAL_NEGATIVE_NO_CONDITIONAL_FIFO", negative_no[len(negative_no) // 2]))
    elif negative:
        choices.append(("TYPICAL_NEGATIVE_CONDITIONAL_FIFO", negative[len(negative) // 2]))
    if negative:
        choices.append(("LARGE_NEGATIVE_COUNTEREXAMPLE", negative[0]))
    for lot in closed:
        if lot["evidence_class"] == "PROSPECTIVE_POLL":
            choices.append(("PROSPECTIVE_AGGRESSIVE_EXIT", lot))
    examples = []
    seen = set()
    for category, lot in choices:
        if lot["trade_id"] in seen:
            continue
        seen.add(lot["trade_id"])
        context = time_by_id[lot["trade_id"]]
        examples.append(
            {
                "example_category": category,
                **lot,
                "local_time": context["local_time"],
                "reference_station": context["reference_station"],
                "forecast_tmax_time": None,
                "forecast_status": "UNAVAILABLE",
                "buy_book": book_by_id.get(lot["trade_id"], {"book_status": "NO_HISTORICAL_BOOK"}),
                "sell_books": [
                    book_by_id.get(
                        identity, {"book_status": "NO_HISTORICAL_BOOK", "trade_id": identity}
                    )
                    for identity in lot["sell_trade_ids"]
                ],
                "verified_result": "EXCHANGE_FEE_NET_ONLY_GAS_EXCLUDED"
                if lot["after_exchange_fee_pnl"] is not None
                else "CONDITIONAL_GROSS_ONLY",
            }
        )
    rows_by_group: list[dict[str, Any]] = []
    for key in (
        "price_bucket",
        "local_hour",
        "role_combination",
        "holding_bucket",
        "condition_id",
        "city",
        "city_local_hour",
        "market_month",
        "outcome",
        "market_kind",
    ):
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for lot in weather_lots:
            groups[str(lot.get(key))].append(lot)
        rows_by_group.extend(
            {"group_dimension": key, "group_value": value, **aggregate(group)}
            for value, group in sorted(groups.items())
        )
    pattern_base = [
        lot
        for lot in clean
        if str(lot.get("outcome")).lower() == "no"
        and Decimal(".88") <= lot["buy_price"] <= Decimal(".92")
    ]
    patterns = [
        lot
        for lot in pattern_base
        if lot["fully_closed"]
        and 3 <= lot["holding_seconds"] <= 15
        and Decimal(".01") <= lot["sell_vwap"] - lot["buy_price"] <= Decimal(".03")
    ]
    local_summary = {}
    for label in ("TMAX", "TMIN", "TMAX_NO", "TMAX_YES", "TMIN_NO", "TMIN_YES"):
        kind, _, outcome_filter = label.partition("_")
        selected = [
            row
            for row in timing
            if row["market_kind"] == kind
            and row["local_hour"] is not None
            and (not outcome_filter or str(row["outcome"]).upper() == outcome_filter)
        ]
        within = [row for row in selected if row["within_14_16_local"]]
        same_day = [row for row in selected if row["same_city_calendar_day_as_market"] is True]
        same_day_within = [row for row in same_day if row["within_14_16_local"]]
        local_summary[label] = {
            "buys_with_local_clock": len(selected),
            "within_14_16": len(within),
            "fraction_14_16": len(within) / len(selected) if selected else None,
            "notional_fraction_14_16": float(
                sum((row["notional"] for row in within), Decimal(0))
                / sum((row["notional"] for row in selected), Decimal(0))
            )
            if selected
            else None,
            "hour_counts": dict(Counter(str(row["local_hour"]) for row in selected)),
            "causal_forecast_tmax_count": 0,
            "true_final_observed_tmax_count": 0,
            "same_city_day_count": len(same_day),
            "other_city_day_count": len(selected) - len(same_day),
            "same_city_day_14_16_count": len(same_day_within),
            "same_city_day_14_16_fraction": len(same_day_within) / len(same_day)
            if same_day
            else None,
        }
    summary = {
        "snapshot": manifest,
        "event_counts": event_counts,
        "trade_rows": len(trades),
        "buy_lots": len(lots),
        "weather_buy_lots": len(weather_lots),
        "weather_no_buys": len(no),
        "flag_counts": dict(Counter(flag for lot in lots for flag in lot["integrity_flags"])),
        "closure_all_weather": closure_summary(clean),
        "closure_no_weather": closure_summary(
            [lot for lot in clean if str(lot.get("outcome")).lower() == "no"]
        ),
        "closure_TMAX": closure_summary([lot for lot in clean if lot["market_kind"] == "TMAX"]),
        "closure_TMIN": closure_summary([lot for lot in clean if lot["market_kind"] == "TMIN"]),
        "economics": aggregate(weather_lots),
        "price_distribution": distributions,
        "local_timing": local_summary,
        "roles": dict(Counter(row["role"] for row in role_rows)),
        "sell_roles": dict(Counter(row["role"] for row in role_rows if row["side"] == "SELL")),
        "pattern": {
            "definition": "NO .88–.92, exactcompleteFIFO3–15s, VWAPimprovement .01–.03",
            "eligible_buy_count": len(pattern_base),
            "matching_count": len(patterns),
            "gross_pnl": sum((lot["gross_pnl"] for lot in patterns), Decimal(0)),
            "fully_costed_net_pnl": None,
            "quick_higher_exit_any_improvement_count": sum(
                lot["fully_closed"]
                and 3 <= lot["holding_seconds"] <= 15
                and lot["sell_vwap"] > lot["buy_price"]
                for lot in pattern_base
            ),
        },
        "net_fully_costed_verified_lots": 0,
        "chain_proofs": chain,
        "prospective_case_count": len(recent) // 2,
        "book_audit": book_rows,
        "all_trade_book_status_counts": dict(Counter(row["book_status"] for row in all_books)),
        "requested_passive_example": "UNAVAILABLE_NO_WALLET_ATTRIBUTABLE_PASSIVE_EXIT",
        "requested_predicted_tmax_example": "UNAVAILABLE_NO_CAUSAL_FORECAST_ARCHIVE",
    }
    summary["matching_paths"] = matching_paths(snapshot, snapshot_dir / "rpc")
    buy_paths = [
        path
        for path in summary["matching_paths"]
        if path["side"] == "BUY"
        and path["matching_path"] == "OPPOSITE_OUTCOME_BUY_BUY_MINT_SUPPORTED"
        and path["quantity"] == "38.35"
        and path["collateral"] == "37.583"
        and path["counterparty_count"] == 4
    ]
    sell_paths = [
        path
        for path in summary["matching_paths"]
        if path["side"] == "SELL"
        and path["matching_path"] == "DIRECT_SAME_TOKEN_SELL_TO_BUY_TRANSFER"
        and path["quantity"] == "38.35"
        and path["collateral"] == "37.9665"
    ]
    if len(buy_paths) != 1 or len(sell_paths) != 1:
        raise ValueError(
            "Saved Ankara receipt evidence is incomplete; do not render the case-specific findings"
        )
    closed_no = [
        lot for lot in clean if lot["fully_closed"] and str(lot.get("outcome")).lower() == "no"
    ]
    summary["no_exit_targets"] = {
        "exact_closed_count": len(closed_no),
        "sell_vwap_near_0_99_count": sum(
            abs(lot["sell_vwap"] - Decimal(".99")) <= Decimal(".000001") for lot in closed_no
        ),
        "comparison_tolerance": "0.000001",
        "entry_median": median([lot["buy_price"] for lot in no]),
        "entry_exact_0_98_count": sum(lot["buy_price"] == Decimal(".98") for lot in no),
        "TMAX_NO_count": sum(lot["market_kind"] == "TMAX" for lot in no),
        "TMAX_NO_exact_0_98_count": sum(
            lot["market_kind"] == "TMAX" and lot["buy_price"] == Decimal(".98") for lot in no
        ),
    }
    output.mkdir(parents=True, exist_ok=True)
    csv_write(output / "hightemptation_price_distribution.csv", distributions)
    csv_write(output / "hightemptation_holding_times.csv", lots)
    csv_write(output / "hightemptation_maker_taker.csv", role_rows)
    csv_write(output / "hightemptation_tmax_timing.csv", timing)
    csv_write(output / "hightemptation_execution_examples.csv", examples)
    csv_write(output / "hightemptation_book_audit.csv", all_books)
    csv_write(output / "hightemptation_fifo_matches.csv", matches)
    csv_write(output / "hightemptation_sale_accounting.csv", sales)
    csv_write(output / "hightemptation_grouped_economics.csv", rows_by_group)
    csv_write(output / "hightemptation_matching_paths.csv", summary["matching_paths"])
    freq = Counter(str(lot["buy_price"].normalize()) for lot in no)
    csv_write(
        output / "hightemptation_price_frequencies.csv",
        [
            {"price": price, "buy_count": count}
            for price, count in sorted(freq.items(), key=lambda item: (-item[1], Decimal(item[0])))
        ],
    )
    cent = Counter(
        str(lot["buy_price"].quantize(Decimal(".01"), rounding=ROUND_HALF_UP)) for lot in no
    )
    summary["natural_price_modes"] = freq.most_common(12)
    summary["fixed_cent_clusters"] = cent.most_common(12)
    summary["charts"] = [str(path) for path in render(output)]
    (output / "hightemptation_exp0012_summary.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8"
    )
    write_report(output, summary, examples)
    return summary


def write_report(output: Path, summary: dict[str, Any], examples: list[dict[str, Any]]) -> None:
    closure = summary["closure_no_weather"]
    e = summary["economics"]
    local = summary["local_timing"]
    text = "# EXP-0012 — Tmax timing, limit exits and microstructure\n\n"
    text += "Retrospective forensic research; no services restarted, no production changes or real orders.\n\n"
    text += f"Trade snapshot: {summary['snapshot']['sources']['trader']['snapshot_pinned_at']}, SHA256 `{summary['snapshot']['sources']['trader']['sha256']}`. Weather snapshot separately pinned {summary['snapshot']['sources']['weather']['snapshot_pinned_at']}; clocks are not treated as simultaneous.\n\n"
    text += f"Scope: {summary['trade_rows']} public economic rows, {summary['buy_lots']} BUY lots, {summary['weather_buy_lots']} weather BUYs, {summary['weather_no_buys']} NO weather BUYs. Complete returned keyset history is not a complete on-chain transfer ledger. Opening balances remain unverified for every historical token.\n\n"
    text += "## Quantity accounting\n\nConditional FIFO replaces first-later-SELL pairing. Partial sales, multiple buys and exact remaining quantities are retained. Same-second mixed sides and ambiguous transaction projections are excluded. Tokens with oversells/nontrade activity are flagged. Every reported matching statistic below is conditional on the trade-only ledger; none certifies unknown opening inventory.\n\n"
    text += f"Flags by BUY lot: `{json.dumps(summary['flag_counts'])}`. Primary clean NO weather cohort {closure['eligible_buy_lots']} BUYs; exactly closed {closure['fully_closed']}; not exactly closed {closure['not_fully_closed']}. Median exact-closure source block interval {closure['median_holding_seconds_closed']}s. Source clocks have second precision and may follow actual exchange matching. All-outcome control: {summary['closure_all_weather']['eligible_buy_lots']} eligible BUYs/{summary['closure_all_weather']['fully_closed']} exactly closed; the holding chart includes both YES and NO.\n\n"
    text += "|Interval|Exact closures|% all eligible BUY lots|% exactly closed lots|% purchased share quantity sold|95% day-block interval, all eligible|\n|---|---|---|---|---|---|\n"
    for seconds in (5, 10, 30, 60):
        row = closure[str(seconds)]
        ci = row["uncertainty"]
        text += f"|{seconds}s|{row['closed_count']}|{pct(row['fraction_of_all_eligible'])}|{pct(row['fraction_of_closed'])}|{pct(row['share_quantity_closed_fraction'])}|{pct(ci['low'])}–{pct(ci['high'])}%|\n"
    text += "\nUTC-day resampling uses2000replicates/seed12. Descriptive intervals do not fix non-random history selection, temporal dependence across days or missing transfer inventory. Open lots remain in the all-eligible denominator.\n\n"
    text += "## NO prices and economic results\n\nBuckets are left-closed/right-open;0.98 belongs in the final bucket,1.00 is included. Frequencies and fixed1cent clusters are descriptive, not optimized strategy parameters.\n\n|Bucket|BUY rows|Shares|Notional|Clean exact-closed median(s)|Conditional gross, closed only|Verified full-cost net|\n|---|---|---|---|---|---|---|\n"
    for row in summary["price_distribution"]:
        text += f"|{row['price_bucket']}|{row['buy_count']}|{row['shares']}|{row['notional']}|{row['holding_median_seconds']}|{row['gross_pnl']}|UNKNOWN|\n"
    text += f"\nNatural exact-price modes: `{summary['natural_price_modes']}`. Cent clusters: `{summary['fixed_cent_clusters']}`. Gross positive/negative/flat clean closed lots: {e['gross_positive_closed']}/{e['gross_negative_closed']}/{e['gross_flat_closed']}. Capital and volume totals cover all buys, while gross columns cover only clearly labeled clean closed lots; they are not whole-wallet PnL. No full-cost historical net verified.\n\n"
    text += f"Conditional matched portions of still-open ledger lots add gross {e['partial_lots_matched_gross_pnl']}; all matched portions total {e['all_matched_gross_pnl']}. Unclosed ledger cost {e['unclosed_ledger_cost']} is not current wallet holdings or mark-to-market loss: redemption/transfer history is incomplete. Closed-only results can omit settlement losses and must not be quoted as whole-wallet profit or accuracy.\n\n"
    target = summary["no_exit_targets"]
    text += f"NO entry median {target['entry_median']}; exact0.98 appears {target['entry_exact_0_98_count']}times. Of {target['exact_closed_count']} clean exactly-closed NO lots, {target['sell_vwap_near_0_99_count']} exit VWAPs are within0.000001 of0.99. Executed BUY VWAP is not the original limit price; neither the median nor its clusters establish a predetermined order cap.\n\n"
    text += f"Predefined0.88–0.92NO /3–15s /+0.01–0.03 probe: {summary['pattern']['matching_count']} matches out of {summary['pattern']['eligible_buy_count']} eligible entry-range BUYs. This describes source-block timing and conditional gross performance, not passive order placement or profitability after unverified costs.\n\n"
    text += f"Allowing any positive executed-price improvement instead of only0.01–0.03 yields {summary['pattern']['quick_higher_exit_any_improvement_count']}quick higher exits in that same entry-range denominator. This is a separately disclosed broad descriptive question, not a retuned profitability search.\n\n"
    text += "## Roles and passive-exit hypothesis\n\n"
    text += f"All recorded rows: `{summary['roles']}`; SELL roles: `{summary['sell_roles']}`. UNKNOWN is retained, and the known subset is selected by recent feed coverage. It cannot determine the maker/taker mix of all historical SELLs.\n\n"
    text += "The positive API subset is explicitly sampled through taker_only=true: all-known-taker is an ascertainment artifact, not an unbiased population estimate. Only transaction-specific verified roles justify a mechanism classification.\n\n"
    text += "Ankara BUY and SELL receipts were independently fetched once each and decoded against the official current CTFExchangeV2 ABI/address. OrdersMatched identifies HighTempTation as taker-order owner in both; the matching aggregate OrderFilled fee is0. This is a real counterexample to a universal passive-limit-exit explanation. Economic price limits on aggressive orders do not make an execution a passive maker fill. Original order creation remains unknown.\n\n"
    text += "The pair exchanged37.583out/37.9665in for38.35shares: +0.3835quoted collateral units after observed exchange fees, excluding unverified gas/relay/rebate costs. Current collateral is pUSD, not an inferred historical USDC balance. Complete realized portfolio profit is not established by this incremental pair.\n\n"
    text += "## Important correction: the entry used the opposite outcome\n\n"
    for path in summary["matching_paths"]:
        text += f"{path['side']}: `{path['transaction_hash']}`, {path['matching_path']}; target quantity {path['quantity']}, collateral {path['collateral']}, counterparties {path['counterparty_count']}.\n\n"
    text += "For the Ankara BUY, four maker-side BUY orders on the exact sibling YES token paid0.02per share. Their quantities12.35+5+6+15 total38.35; their0.767collateral plus the target37.583 totals38.35. Both outcomes and condition mapping agree with captured Gamma metadata, and the ExchangeV2 implementation supports BUY/BUY mint matching. This is not a purchase from a direct NO ask. The SELL then matched a BUY on the same NO token at0.99. Original placement times and prior public visibility of these maker orders remain unverified.\n\n"
    text += "Therefore the previous shadow NO_LIQUIDITY result established only that direct asks were empty. Its direct-asks-only model did not assess opposite-outcome mint liquidity. It cannot establish that every native matching path was unavailable, nor that a fast copy could not execute through such a path. Reliable same-epoch sibling depth at our decision time is missing, so that alternative copy result is UNVERIFIABLE. No production collector or shadow engine is changed here.\n\n"
    text += "A future bounded measurement should capture both binary outcomes and compare direct askNO with1-bidYES after validating contract/version, available size, fees and quote freshness. That is a proposed test, not a claim those quotes coexisted or a deployed arbitrage rule.\n\n"
    text += "## Local timing and Tmax\n\n"
    for kind, row in local.items():
        text += f"{kind}: {row['within_14_16']}/{row['buys_with_local_clock']} BUYs in14:00–16:00city local time ({pct(row['fraction_14_16'])}%), notional share {pct(row['notional_fraction_14_16'])}%. Hour counts `{row['hour_counts']}`.\n\n"
        text += f"Same city-calendar date as market: {row['same_city_day_count']}; other local dates {row['other_city_day_count']}. Same-day14–16 count {row['same_city_day_14_16_count']}, fraction {row['same_city_day_14_16_fraction']}. These are geographic calendar references, not verified settlement windows for uncaptured rules.\n\n"
    text += "Geographic IANA references permit descriptive local hours, not retroactive settlement-rule verification. Only captured exact token+condition metadata establishes a station reference. Captured London markets useEGLC, while the weather collector monitorsEGLL; Heathrow cannot stand in for LondonCity.\n\n"
    text += "No archived causal forecast Tmax hour exists in these inputs. No true final settlement-source Tmax time is established. Those fields remainNULL. Optional local METAR subset maxima are explicitly retrospective/incomplete and not final daily Tmax or decision inputs. Current market endDate is not assumed to be local midnight.\n\n"
    text += "Global historical market tape, depth-by-local-hour and matched no-trade controls are unavailable. Own-wallet SELL activity is not a global liquidity baseline. A14–16histogram cannot establish favorable expected Tmax timing or distinguish weather repricing from mean reversion.\n\n"
    text += "## Actual book evidence and examples\n\n"
    text += f"All-history book classification: `{summary['all_trade_book_status_counts']}`. Source-block-relative pre-trade status does not establish a physically pre-match book.\n\n"
    for row in summary["book_audit"]:
        text += f"- {row['side']} `{row['trade_id']}`: {row['book_status']}; subscribed at source anchor={row.get('subscribed_at_source_anchor')}; post-receipt empty-side={row.get('empty_side_status')}; role={row['role']}.\n"
    text += "\nA subscription existing earlier does not establish uninterrupted valid depth. Raw HTTP200asks:[] must match exact asset, condition, both sides and raw SHA before EMPTY_SIDE_CONFIRMED. Provider book clocks can lead local receipt; no millisecond event ordering or global liquidity absence is inferred. Replayed aggregated quantities do not identify order owners.\n\n"
    for example in examples:
        text += f"- {example['example_category']}: `{example['trade_id']}`, {example['city']}, BUY{example['buy_price']}, quantity{example['buy_size']}, matched{example['matched_quantity']}, remainder{example['remaining_quantity']}, exact closure{example['holding_seconds']}s, sellVWAP{example['sell_vwap']}, conditionalgross{example['gross_pnl']}, fee-net{example['after_exchange_fee_pnl']}. {example['verified_result']}.\n"
        text += f"  Source BUY {example['source_trade_timestamp']} ({example['local_time']} local), last matched SELL {example['last_matched_sell_time']}. BUY role {example['buy_role']}; SELL evidence {example['sell_roles']}. Pre-entry book {example['buy_book'].get('book_status')}; limit placement and forecast Tmax remain UNKNOWN.\n"
    text += "\nFive real sequences are attempted; historical illustrations lack contemporaneous books/fees and are not five fully proven mechanisms. No wallet-attributable passive-limit example or causal forecast-Tmax example exists. Explicit unknown fields remain in the examples CSV.\n\n"
    text += "## Conclusions and bounded next test\n\nFast higher-price NO exits are a common conditional execution pattern; passive limit placement is not demonstrated. Ankara supports an aggressive taker exit, and recent API evidence is consistent with another such case. The historical maker/taker denominator is mostly unknown. Weather timing versus repricing remains unresolved. A hybrid is plausible, not identified.\n\n"
    text += "## Direct answers to the eight research questions\n\n"
    pattern = summary["pattern"]
    target = summary["no_exit_targets"]
    clock = summary["local_timing"]["TMAX_NO"]
    text += f"1. Around0.90: {pattern['quick_higher_exit_any_improvement_count']}/{pattern['eligible_buy_count']} cleanNO entries0.88–0.92 close higher within3–15source seconds. The stricter +0.01–0.03 probe has {pattern['matching_count']}cases; many exits are around0.99. No evidence establishes immediate passive limit placement.\n"
    text += "2. Exact quantity-closure rates are in the NO table above, with both all-eligible and closed-only denominators; not first-later-SELL intervals.\n"
    text += "3. Whole-history SELL maker/taker majority is UNKNOWN; taker-only positive evidence is a selected sample. Ankara is independently chain-verified TAKER/TAKER.\n"
    text += f"4. NO/Tmax same-city-day14–16: {clock['same_city_day_14_16_count']}/{clock['same_city_day_count']} ({pct(clock['same_city_day_14_16_fraction'])}%). Expected forecast Tmax alignment is UNTESTABLE without the original forecast archive.\n"
    text += f"5. Ankara0.98 is not an exceptional price: exact0.98 is the strongest exact-price mode, {target['entry_exact_0_98_count']}/{summary['weather_no_buys']}NO buys; {target['TMAX_NO_exact_0_98_count']}/{target['TMAX_NO_count']}specificallyTmaxNO. VWAP is not an order-limit observation.\n"
    text += "6. No price/holding combination has fully verified historical all-cost profitability. Ankara has +0.3835pUSD after observed zero exchange fees; gas/relay/rebates and original wider inventory remain outside that statement. Gross-only groups and losses are exported completely.\n"
    text += "7. Aggressive matching and a BUY/BUY mint entry are proven in Ankara. That does not identify the information trigger or exclude passive/hybrid behavior elsewhere; weather causality and mean reversion lack matched controls.\n"
    text += "8. The demonstrated route can be measured prospectively through both outcome books. Its pre-entry availability and post-detection copy profitability are not established here; the direct-ask-only shadow model was incomplete for that route. No execution rule is activated.\n\n"
    text += "Faithful replication requires a causally recorded entry signal and executable pre-entry book, not a hindsight rule based on the trader's fills. Existing delayed copies found no direct ask at the sampled opportunities, but omitted the demonstrated opposite-outcome matching path. No profitable replication rule or general impossibility of copying is established.\n\n"
    text += "Propose only: freeze a bounded watchlist by weather event/date before activity (include sibling outcomes), preserve valid full snapshots plus same-epoch deltas, and record canonical market identity/clock evidence. Current late subscription on some tokens prevents pre-entry reconstruction. Do not change current services in this experiment. Add legitimate forecast archives and matched no-trade periods before evaluating Tmax causality.\n\n"
    text += "Reproduce: `uv run python -m scripts.research.hightemptation_tmax_limit_exit --snapshot-dir data/research/exp0012 --output reports/trader`. Sources/method details: docs/research/EXP0012_PROTOCOL.md, EXP0012_METADATA.md and EXP0012_BOOK_AUDIT.md. Immutable snapshots and original public RPC responses are retained ignored locally; normalized research outputs are committed.\n"
    (output / "hightemptation_tmax_limit_exit.md").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", type=Path, default=Path("data/research/exp0012"))
    parser.add_argument("--output", type=Path, default=Path("reports/trader"))
    args = parser.parse_args()
    result = run(args.snapshot_dir, args.output)
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "trade_rows",
                    "buy_lots",
                    "closure_all_weather",
                    "natural_price_modes",
                    "pattern",
                    "local_timing",
                    "sell_roles",
                )
            },
            indent=2,
            default=str,
        )
    )
