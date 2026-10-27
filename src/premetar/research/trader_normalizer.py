"""Strict normalization of the documented public Data API v2 feed."""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

WALLET = "0x6011655c4afb76f36dd1b08a137a1ba73466b31e"


def normalize_trade(row: dict[str, Any], received: datetime, evidence: str) -> dict[str, Any]:
    if received.tzinfo is None or received.utcoffset() is None:
        raise ValueError("NAIVE_RECEIPT")
    if str(row.get("proxy_wallet", "")).lower() != WALLET:
        raise ValueError("WRONG_OR_MISSING_WALLET")
    side = row.get("side")
    if side not in ("BUY", "SELL"):
        raise ValueError("INVALID_SIDE")
    try:
        price, size = Decimal(str(row["price"])), Decimal(str(row["size"]))
        stamp = row["timestamp"]
        if isinstance(stamp, bool) or not isinstance(stamp, int) or stamp <= 0:
            raise ValueError("INVALID_SOURCE_TIME")
        source = datetime.fromtimestamp(stamp, UTC)
    except (KeyError, InvalidOperation, OverflowError, OSError) as exc:
        raise ValueError("MALFORMED_TRADE") from exc
    if not price.is_finite() or not size.is_finite() or not 0 < price < 1 or size <= 0:
        raise ValueError("INVALID_PRICE_OR_SIZE")
    token, condition, tx = (
        str(row.get(k) or "") for k in ("token_id", "condition_id", "transaction_hash")
    )
    if not token.isdigit() or not condition.startswith("0x") or not tx.startswith("0x"):
        raise ValueError("MISSING_IDENTIFIERS")
    # API has no fill/log ID. Identical economic rows are indistinguishable, not proven one fill.
    key = [WALLET, tx, token, side, str(price.normalize()), str(size.normalize()), stamp]
    trade_id = hashlib.sha256(json.dumps(key).encode()).hexdigest()
    latency = (received - source).total_seconds()
    if latency < -1:
        evidence = "SOURCE_CLOCK_ANOMALY"
    return {
        "trade_id": trade_id,
        "transaction_hash": tx,
        "trader_wallet": WALLET,
        "market_id": row.get("market_id"),
        "condition_id": condition,
        "token_id": token,
        "market_title": row.get("title"),
        "outcome": row.get("outcome"),
        "slug": row.get("slug"),
        "event_slug": row.get("event_slug"),
        "side": side,
        "price": str(price),
        "size": str(size),
        "source_trade_timestamp": source.isoformat(),
        "source_timestamp_precision_seconds": 1,
        "first_collector_receipt_utc": received.astimezone(UTC).isoformat(),
        "source_publication_timestamp_if_available": None,
        "trade_detection_latency": latency,
        "evidence_class": evidence,
        "order_role": "UNKNOWN",
        "order_creation_time": None,
        "source": "POLYMARKET_DATA_API_V2",
        "identity_limitation": "Identical fills without log index cannot be distinguished",
    }


def parse_page(payload: Any) -> tuple[list[dict[str, Any]], str | None]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("INVALID_V2_ENVELOPE")
    rows = payload["data"]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("INVALID_TRADE_ROW")
    pagination = payload.get("pagination")
    if not isinstance(pagination, dict):
        raise ValueError("MISSING_PAGINATION")
    cursor = pagination.get("next_cursor")
    if cursor is not None and (not isinstance(cursor, str) or not cursor):
        raise ValueError("INVALID_CURSOR")
    if bool(pagination.get("has_more")) != (cursor is not None):
        raise ValueError("INCONSISTENT_PAGINATION")
    return rows, cursor
