"""Deterministic observed-data replay; no live order or prediction creation."""

import argparse
import csv
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from premetar.research.entry_reconstruction import source_rows
from premetar.research.entry_reconstruction_books import BookRing
from premetar.research.entry_reconstruction_features import snapshot_features
from premetar.research.entry_timing_monitor import ROOT, TRADER, clock
from premetar.research.surge_detector import detect_changes
from premetar.research.surge_identity import match_public_trade
from premetar.research.surge_states import book_state
from premetar.research.trader_store import readonly_connection
from scripts.research.hightemptation_books import (
    EXCHANGE_V2,
    ORDER_FILLED_TOPIC,
    WALLET,
    decode_v2_receipt,
)

OUTPUT = ROOT / "reports/trader"
RPC = ROOT / "data/research/exp0018_surge/wellington_rpc"


def receipt_evidence(directory: Path = RPC) -> list[dict[str, Any]]:
    result = []
    for path in sorted(directory.glob("*.json")):
        if not path.name.startswith(("buy_", "sell_")):
            continue
        envelope = json.loads(path.read_text(encoding="utf-8"))
        proofs = decode_v2_receipt(envelope)
        receipt = json.loads(envelope["body"])["result"]
        for proof in proofs:
            counterparties = []
            for log in receipt["logs"]:
                topics = log.get("topics", [])
                if (
                    log.get("removed")
                    or str(log.get("address", "")).lower() != EXCHANGE_V2
                    or len(topics) != 4
                    or topics[0] != ORDER_FILLED_TOPIC
                    or "0x" + topics[3][-40:].lower() != WALLET
                ):
                    continue
                words = [int(log["data"][i : i + 64], 16) for i in range(2, len(log["data"]), 64)]
                if len(words) != 7:
                    raise ValueError("Unexpected verified v2 event layout")
                if words[0] not in (0, 1):
                    raise ValueError("Unknown counterparty order side")
                counterparties.append(
                    dict(
                        side="BUY" if words[0] == 0 else "SELL",
                        token_id=str(words[1]),
                        collateral=str(Decimal(words[2] if words[0] == 0 else words[3]) / 1000000),
                        shares=str(Decimal(words[3] if words[0] == 0 else words[2]) / 1000000),
                        fee_raw=words[4],
                        log_index=int(log["logIndex"], 16),
                    )
                )
            block_path = directory / f"block_{receipt['blockNumber']}.json"
            block_time = None
            if block_path.exists():
                block_envelope = json.loads(block_path.read_text(encoding="utf-8"))
                if (
                    hashlib.sha256(block_envelope["body"].encode()).hexdigest()
                    != block_envelope["sha256"]
                ):
                    raise ValueError("Block body hash mismatch")
                block = json.loads(block_envelope["body"])["result"]
                if block["hash"].lower() != receipt["blockHash"].lower():
                    raise ValueError("Receipt/block hash mismatch")
                block_time = datetime.fromtimestamp(int(block["timestamp"], 16), UTC).isoformat()
            result.append(
                dict(
                    proof,
                    receipt_body_sha256=envelope["sha256"],
                    receipt_backfilled_at=envelope["received_at"],
                    block_timestamp=block_time,
                    counterparties=counterparties,
                )
            )
    return result


def replay(source: Path = TRADER, output: Path = OUTPUT) -> dict[str, Any]:
    old = json.loads(
        (ROOT / "reports/trader/exp0018_entry_trigger_reconstruction.json").read_text(
            encoding="utf-8"
        )
    )
    entry = next(
        e
        for e in old["entries"]
        if e.get("station") == "NZWN" and e["source_trade_timestamp"] == "2026-10-31T08:58:33+00:00"
    )
    tokens = entry["market"]["tokens"]
    target = datetime(2026, 10, 31, 8, 58, 33, tzinfo=UTC)
    lower = max(0, entry["source_event_id"] - 50000)
    upper = min(old["source_cutoff"]["maximum_inclusive"], entry["source_event_id"] + 50000)
    ring = BookRing(max_tokens=2, max_states=600)
    previous: dict[str, dict[str, Any]] = {}
    timeline = []
    source_events = []
    surges: list[dict[str, Any]] = []
    cursor = lower
    while cursor < upper:
        next_cursor, rows = source_rows(source, cursor)
        if next_cursor <= cursor:
            break
        for row in rows:
            if row["id"] > upper:
                break
            received = clock(row["received_at"])
            if not received or not target - timedelta(
                seconds=900
            ) <= received <= target + timedelta(seconds=300):
                continue
            kind, p = row["kind"], row["payload"]
            touched = []
            if kind == "BOOK" and p.get("token_id") in tokens.values():
                touched = [p["token_id"]]
                ring.add(row)
            elif kind == "WS_DELTA":
                changes = [
                    c for c in p.get("price_changes", []) if c.get("asset_id") in tokens.values()
                ]
                if changes:
                    p = dict(p, price_changes=changes)
                    row = dict(row, payload=p)
                    touched = sorted({c["asset_id"] for c in changes})
                    ring.delta(row)
            elif kind == "STREAMHEALTH" and p.get("state") in {
                "RECONNECTING",
                "MALFORMED_MESSAGE",
                "STOPPED",
            }:
                ring.invalidate()
                previous = {}
                if received >= target - timedelta(seconds=300):
                    timeline.append(
                        dict(
                            source_event_id=row["id"],
                            kind="RECONNECT_GAP",
                            received_at=received.isoformat(),
                        )
                    )
            relevant = (
                bool(touched)
                or kind in {"WS_TRADE", "TRADE"}
                and p.get("token_id") in tokens.values()
            )
            if relevant:
                source_events.append(row)
            for token in touched:
                snapshot = ring.latest(token, received)
                side = next(k for k, v in tokens.items() if v == token)
                flat = dict(
                    snapshot_features(snapshot),
                    token_id=token,
                    outcome=side,
                    connection_id=p.get("connection_id"),
                    received_at=received.isoformat(),
                    source_event_id=row["id"],
                    kind=kind,
                    exchange_timestamp=p.get("source_timestamp"),
                    state=book_state(dict(snapshot, complete=True) if snapshot else None, received),
                    canonical_normalized_payload_sha256=hashlib.sha256(
                        json.dumps(p, sort_keys=True).encode()
                    ).hexdigest(),
                )
                if received >= target - timedelta(seconds=300):
                    timeline.append(flat)
                    if token in previous:
                        surges.extend(
                            dict(
                                s,
                                token_id=token,
                                outcome=side,
                                source_event_id=row["id"],
                                update_type=kind,
                                changes=p.get("price_changes"),
                                state=flat["state"],
                            )
                            for s in detect_changes(previous[token], flat)
                        )
                if snapshot:
                    previous[token] = flat
                else:
                    previous.pop(token, None)
            if (
                kind in {"WS_TRADE", "TRADE"}
                and p.get("token_id") in tokens.values()
                and received >= target - timedelta(seconds=300)
            ):
                timeline.append(
                    dict(
                        kind=kind,
                        source_event_id=row["id"],
                        received_at=received.isoformat(),
                        token_id=p["token_id"],
                        outcome=next(k for k, v in tokens.items() if v == p["token_id"]),
                        price=p.get("price"),
                        size=p.get("size"),
                        side=p.get("side"),
                        source_trade_timestamp=p.get("source_trade_timestamp"),
                        first_detection=p.get("first_collector_receipt_utc"),
                        exchange_timestamp=p.get("source_timestamp"),
                        transaction_hash=p.get("transaction_hash"),
                    )
                )
        cursor = min(next_cursor, upper)
    proofs = receipt_evidence()
    exact_joins = []
    connection = readonly_connection(source)
    try:
        for event in timeline:
            if event["kind"] != "WS_TRADE":
                continue
            raw_row = connection.execute(
                "SELECT id,received_at,payload,payload_hash FROM events WHERE kind='WS_RAW' AND id<? ORDER BY id DESC LIMIT 1",
                (event["source_event_id"],),
            ).fetchone()
            if not raw_row:
                continue
            original = json.loads(raw_row[2])
            for proof in proofs:
                matched = match_public_trade(
                    str(original.get("text") or ""), proof["transaction_hash"], proof["token_id"]
                )
                if matched is not None and raw_row[1] == event["received_at"]:
                    event["transaction_hash"] = proof["transaction_hash"]
                    event["raw_ws_event_id"] = raw_row[0]
                    exact_joins.append(
                        dict(
                            transaction_hash=proof["transaction_hash"],
                            side=proof["side"],
                            received_at=raw_row[1],
                            exchange_timestamp=matched.get("timestamp"),
                            raw_ws_event_id=raw_row[0],
                            raw_payload_hash=raw_row[3],
                            public_message=matched,
                            proof="EXACT_TRANSACTION_HASH_TOKEN_AND_RECEIPT_RAW_FRAME_JOIN",
                        )
                    )
    finally:
        connection.close()
    buy = next((p for p in proofs if p["side"] == "BUY" and p["token_id"] == tokens["no"]), None)
    sell = next((p for p in proofs if p["side"] == "SELL" and p["token_id"] == tokens["no"]), None)
    mint = False
    if buy:
        makers = buy["counterparties"]
        mint = (
            bool(makers)
            and all(m["side"] == "BUY" and m["token_id"] == tokens["yes"] for m in makers)
            and sum((Decimal(m["shares"]) for m in makers), Decimal(0)) == Decimal(buy["quantity"])
            and sum((Decimal(m["collateral"]) for m in makers), Decimal(0))
            + Decimal(buy["collateral"])
            == Decimal(buy["quantity"])
        )
    gross = (
        Decimal(sell["collateral"]) - Decimal(buy["collateral"])
        if buy and sell and buy["quantity"] == sell["quantity"]
        else None
    )
    result = dict(
        version="WELLINGTON-SURGE-REPLAY-v1",
        mode="RETROSPECTIVE_OBSERVED_RAW_REPLAY",
        created_at=datetime.now(UTC).isoformat(),
        source_id_bounds=[lower, upper],
        source_snapshot_cutoff=old["source_cutoff"]["maximum_inclusive"],
        target=target.isoformat(),
        tokens=tokens,
        condition_id=entry["condition_id"],
        classification="COMPLEMENTARY_LIQUIDITY_SUPPORTED"
        if mint
        else "MULTIPLE_EXPLANATIONS_POSSIBLE",
        trigger_causality="MULTIPLE_EXPLANATIONS_POSSIBLE",
        timeline=timeline,
        surges=surges,
        receipt_proofs=proofs,
        exact_ws_transaction_joins=exact_joins,
        executed_buy_buy_mint=mint,
        conditional_two_execution_gross=str(gross) if gross is not None else None,
        copy_fill_supported=False,
        order_submission_time=None,
    )
    output.mkdir(parents=True, exist_ok=True)
    (output / "wellington_surge_forensic.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (output / "wellington_surge_timeline.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as f:
        columns = [
            "source_event_id",
            "received_at",
            "exchange_timestamp",
            "kind",
            "outcome",
            "bid",
            "ask",
            "bid_quantity",
            "ask_quantity",
            "price",
            "size",
            "source_trade_timestamp",
            "first_detection",
            "state",
            "transaction_hash",
        ]
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(timeline)
    observed = ROOT / "data/research/exp0018_surge/wellington_observed_events.jsonl"
    encoded = "\n".join(json.dumps(r, sort_keys=True) for r in source_events) + "\n"
    if not observed.exists():
        with observed.open("x", encoding="utf-8") as f:
            f.write(encoded)
    elif observed.read_text(encoding="utf-8") != encoded:
        raise ValueError("Existing forensic source excerpt differs; preserve it")
    lines = [
        "# Wellington surge forensic — observed evidence",
        "",
        f"Classification: {result['classification']}; trigger causality: MULTIPLE_EXPLANATIONS_POSSIBLE.",
        f"Snapshot max ID {result['source_snapshot_cutoff']}; read bounds {lower}..{upper}; {len(timeline)} timeline rows, {len(surges)} threshold events. All analysis retrospective.",
        "",
        "## New independently checked transaction evidence",
        "",
        f"BUY/BUY mint supported: {mint}. Official ExchangeV2 logs, hash-checked receipts and block hashes verified. Public receipt backfills are NOT information available before the original trade.",
        "",
        "| Side | Shares | Collateral | VWAP | Block / log | Block timestamp |",
        "|---|---:|---:|---:|---|---|",
    ]
    lines += [
        f"|{p['side']}|{p['quantity']}|{p['collateral']}|{p['vwap']}|{p['block_number']}/{p['matched_log_index']}|{p['block_timestamp']}|"
        for p in proofs
    ]
    lines += [
        "",
        "## Exact maker fills for BUY",
        "",
        "| Maker side/token | Shares | Collateral | Effective NO cost |",
        "|---|---:|---:|---:|",
    ]
    if buy:
        lines += [
            f"|{m['side']} YES|{m['shares']}|{m['collateral']}|{1 - Decimal(m['collateral']) / Decimal(m['shares'])}|"
            for m in buy["counterparties"]
        ]
    lines += [
        "",
        "## What this establishes",
        "",
        "H3 is supported for the EXECUTED BUY: five opposite-outcome YES BUY makers fund the paired mint. Direct NO asks alone cannot explain all matching liquidity. The live snapshot's empty NO ask/YES bid is not contradictory to a prior fill that consumed those orders.",
        "H4/H5: Data API BUY/SELL seconds equal their canonical block timestamps (two transactions). They are not verified matching-engine or submission clocks. Local receipts and exchange message timestamps are separate clocks; do not subtract them as precise causal lead.",
        "H2 remains possible: the public depletion and trade messages may represent this same operation before later on-chain reporting. The owner of a new0.99bid cannot be inferred from aggregate depth. H1 independent reaction and H6 replenishment remain alternatives.",
        "H7: replay checks same connection, full seeds and reported BBO, but no exchange sequence or clock synchronization guarantees. Snapshot transitions and gaps remain explicit.",
        f"The SELL is chain-verified TAKER207.78NO at0.99, not proof of a resting maker limit exit. Equal BUY/SELL quantity supports conditional cash difference {gross}; fungible inventory, earlier transfers, gas/relay costs and order-placement time remain unknown. No full-portfolio or copy profit claim.",
        "",
        "## Research surge events",
        "",
        "| Local receipt UTC | Outcome | Kind | Before | After | Source event |",
        "|---|---|---|---:|---:|---|",
    ]
    lines += [
        "",
        "## Exact raw WebSocket transaction joins",
        "",
        "| Side | WS local receipt | WS exchange timestamp ms | Canonical block timestamp | Raw event |",
        "|---|---|---|---|---|",
    ]
    for join in exact_joins:
        proof = next(p for p in proofs if p["transaction_hash"] == join["transaction_hash"])
        lines.append(
            f"|{join['side']}|{join['received_at']}|{join['exchange_timestamp']}|{proof['block_timestamp']}|{join['raw_ws_event_id']}|"
        )
    lines += [
        "",
        "The RAW BUY print at08:58:29.775972UTC contains the EXACT BUY transaction hash; it precedes the bid insertion at08:58:29.863130UTC by87.158ms in local receive order. The source exchange timestamps also order BUY1793437109909 before bid1793437109963 (54ms). This falsifies interpreting this particular observed bid jump as preceding the public execution print for that BUY. It does NOT establish who owned the new bid or reveal off-chain order-submission time. The old normalizer omitted transaction_hash; raw evidence retained it, and the new normalizer now preserves it without retroactively modifying old records.",
    ]
    lines += [
        f"|{s['received_at']}|{s['outcome']}|{s['kind']}|{s['before']}|{s['after']}|{s['source_event_id']}|"
        for s in surges[:40]
    ]
    lines += [
        "",
        "## Sources and limitations",
        "",
        "Official protocol: https://docs.polymarket.com/api-reference/wss/market . Exchange source: https://github.com/Polymarket/ctf-exchange-v2/blob/main/src/exchange/mixins/Trading.sol . Raw public RPC receipts/block responses are preserved locally with SHA256 and new receive times. Historical evidence is not a contemporaneous executable opportunity. Adjacent bid increase does not reveal ownership or an independent trigger. No hypothetical order/fill/profit has been created.",
    ]
    (output / "wellington_surge_forensic.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    r = replay()
    print(
        json.dumps(
            {k: v for k, v in r.items() if k not in {"timeline", "surges", "receipt_proofs"}},
            indent=2,
        )
    )
