"""Offline proof of direct versus opposite-outcome matching in saved receipts."""

import json
import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Any

from scripts.research.hightemptation_books import (
    EXCHANGE_V2,
    ORDER_FILLED_TOPIC,
    WALLET,
    decode_v2_receipt,
)


def matching_paths(snapshot: Path, rpc_directory: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(snapshot.resolve().as_uri() + "?mode=ro", uri=True)
    pairs: set[frozenset[str]] = set()
    for (encoded,) in conn.execute("SELECT payload FROM events WHERE kind='MARKET'"):
        market = json.loads(encoded)
        values = market.get("clobTokenIds")
        if isinstance(values, str):
            values = json.loads(values)
        if isinstance(values, list) and len(values) == 2:
            pairs.add(frozenset(map(str, values)))
    conn.close()
    output = []
    for path in sorted(rpc_directory.glob("*.json")):
        envelope = json.loads(path.read_text(encoding="utf-8"))
        verified = decode_v2_receipt(envelope)
        receipt = json.loads(envelope["body"])["result"]
        for proof in verified:
            counterparties: list[dict[str, Any]] = []
            for log in receipt["logs"]:
                topics = log.get("topics", [])
                if (
                    log.get("removed")
                    or log.get("address", "").lower() != EXCHANGE_V2
                    or len(topics) != 4
                    or topics[0] != ORDER_FILLED_TOPIC
                ):
                    continue
                if "0x" + topics[3][-40:].lower() != WALLET:
                    continue
                words = [int(log["data"][i : i + 64], 16) for i in range(2, len(log["data"]), 64)]
                if len(words) != 7:
                    raise ValueError("Unexpected filled ABI")
                counterparties.append(
                    {
                        "side": "BUY" if words[0] == 0 else "SELL" if words[0] == 1 else "INVALID",
                        "token_id": str(words[1]),
                        "making": Decimal(words[2]) / 1_000_000,
                        "taking": Decimal(words[3]) / 1_000_000,
                        "fee_raw": words[4],
                    }
                )
            tokens = {row["token_id"] for row in counterparties}
            quantity, collateral = Decimal(proof["quantity"]), Decimal(proof["collateral"])
            status = "MIXED_OR_UNKNOWN"
            if (
                counterparties
                and proof["side"] == "BUY"
                and all(row["side"] == "BUY" for row in counterparties)
                and len(tokens) == 1
                and proof["token_id"] not in tokens
            ):
                pair = frozenset({proof["token_id"], *tokens})
                if (
                    pair in pairs
                    and sum((row["taking"] for row in counterparties), Decimal(0)) == quantity
                    and sum((row["making"] for row in counterparties), Decimal(0)) + collateral
                    == quantity
                ):
                    status = "OPPOSITE_OUTCOME_BUY_BUY_MINT_SUPPORTED"
            if (
                counterparties
                and proof["side"] == "SELL"
                and all(
                    row["side"] == "BUY" and row["token_id"] == proof["token_id"]
                    for row in counterparties
                )
            ):
                if (
                    sum((row["taking"] for row in counterparties), Decimal(0)) == quantity
                    and sum((row["making"] for row in counterparties), Decimal(0)) == collateral
                ):
                    status = "DIRECT_SAME_TOKEN_SELL_TO_BUY_TRANSFER"
            output.append(
                {
                    **proof,
                    "matching_path": status,
                    "counterparties": counterparties,
                    "counterparty_count": len(counterparties),
                    "sibling_token": next(iter(tokens)) if status.startswith("OPPOSITE") else None,
                    "direct_asks_only_copy_model_complete": False
                    if status.startswith("OPPOSITE")
                    else None,
                    "evidence_scope": "EXECUTED_TRANSACTION_NOT_PREEXISTING_QUOTE_AVAILABILITY",
                }
            )
    return output
