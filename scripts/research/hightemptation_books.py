"""Offline EXP0012 book/role evidence; never reads or writes a live database.

Full snapshots and locally received deltas can establish what this collector
recorded. Their timing cannot establish off-chain order placement or globally
pre-execution depth. Public aggregate size changes have no wallet ownership.
"""

import hashlib
import json
import sqlite3
from bisect import bisect_right
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

WALLET = "0x6011655c4afb76f36dd1b08a137a1ba73466b31e"
EXCHANGE_V2 = "0xe2222d279d744050d28e00520010520000310f59"
ORDER_FILLED_TOPIC = "0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee"
ORDERS_MATCHED_TOPIC = "0x174b3811690657c217184f89418266767c87e4805d09680c39fc9c031c0cab7c"


def utc(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Timezone-aware clock required")
    return result.astimezone(UTC)


def _keccak(data: bytes) -> str:
    """Small research-only Ethereum Keccak256 for independently checking ABI topics."""
    rotations = (
        (0, 36, 3, 41, 18),
        (1, 44, 10, 45, 2),
        (62, 6, 43, 15, 61),
        (28, 55, 25, 21, 56),
        (27, 20, 39, 8, 14),
    )
    rounds = (
        0x1,
        0x8082,
        0x800000000000808A,
        0x8000000080008000,
        0x808B,
        0x80000001,
        0x8000000080008081,
        0x8000000000008009,
        0x8A,
        0x88,
        0x80008009,
        0x8000000A,
        0x8000808B,
        0x800000000000008B,
        0x8000000000008089,
        0x8000000000008003,
        0x8000000000008002,
        0x8000000000000080,
        0x800A,
        0x800000008000000A,
        0x8000000080008081,
        0x8000000000008080,
        0x80000001,
        0x8000000080008008,
    )
    mask = (1 << 64) - 1
    state = [0] * 25

    def rol(value: int, shift: int) -> int:
        return ((value << shift) | (value >> (64 - shift))) & mask if shift else value

    padded = bytearray(data)
    padded.append(1)
    padded.extend(bytes((-len(padded)) % 136))
    padded[-1] |= 0x80
    for block in range(0, len(padded), 136):
        for index in range(17):
            state[index] ^= int.from_bytes(
                padded[block + index * 8 : block + (index + 1) * 8], "little"
            )
        for constant in rounds:
            columns = [
                state[x] ^ state[x + 5] ^ state[x + 10] ^ state[x + 15] ^ state[x + 20]
                for x in range(5)
            ]
            differences = [columns[(x - 1) % 5] ^ rol(columns[(x + 1) % 5], 1) for x in range(5)]
            for index in range(25):
                state[index] ^= differences[index % 5]
            moved = [0] * 25
            for x in range(5):
                for y in range(5):
                    moved[y + 5 * ((2 * x + 3 * y) % 5)] = rol(state[x + 5 * y], rotations[x][y])
            for x in range(5):
                for y in range(5):
                    state[x + 5 * y] = moved[x + 5 * y] ^ (
                        (~moved[(x + 1) % 5 + 5 * y]) & moved[(x + 2) % 5 + 5 * y]
                    )
            state[0] ^= constant
    return "0x" + b"".join(value.to_bytes(8, "little") for value in state)[:32].hex()


def verify_event_topics() -> bool:
    return (
        _keccak(b"") == "0xc5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
        and _keccak(
            b"OrderFilled(bytes32,address,address,uint8,uint256,uint256,uint256,uint256,bytes32,bytes32)"
        )
        == ORDER_FILLED_TOPIC
        and _keccak(b"OrdersMatched(bytes32,address,uint8,uint256,uint256,uint256)")
        == ORDERS_MATCHED_TOPIC
    )


def decode_v2_receipt(envelope: dict[str, Any], wallet: str = WALLET) -> list[dict[str, Any]]:
    """Decode saved read-only receipt using verified current CTF ExchangeV2 ABI.

    OrdersMatched names the active taker order's owner; OrderFilled.maker alone
    does not imply passive liquidity role. No gas or external rebates assumed.
    """
    if not verify_event_topics():
        raise ValueError("ABI topic verification failed")
    body = envelope.get("body")
    if not isinstance(body, str):
        return []
    if envelope.get("sha256") != hashlib.sha256(body.encode()).hexdigest():
        raise ValueError("Raw RPC body hash mismatch")
    response = json.loads(body)
    receipt = response.get("result")
    if not isinstance(receipt, dict) or receipt.get("status") != "0x1":
        return []
    if (
        str(receipt.get("transactionHash", "")).lower()
        != str(envelope.get("transaction", "")).lower()
    ):
        raise ValueError("RPC transaction mismatch")
    filled: dict[str, dict[str, Any]] = {}
    matches = []
    for log in receipt.get("logs", []):
        if log.get("removed") or str(log.get("address", "")).lower() != EXCHANGE_V2:
            continue
        topics = log.get("topics", [])
        if not topics or topics[0] not in {ORDER_FILLED_TOPIC, ORDERS_MATCHED_TOPIC}:
            continue
        encoded = str(log.get("data", ""))
        if not encoded.startswith("0x") or (len(encoded) - 2) % 64:
            raise ValueError("Invalid event word encoding")
        words = [int(encoded[i : i + 64], 16) for i in range(2, len(encoded), 64)]
        if topics[0] == ORDER_FILLED_TOPIC:
            if len(topics) != 4 or len(words) != 7:
                raise ValueError("Unexpected OrderFilled v2 layout")
            if (
                "0x" + topics[2][-40:].lower() == wallet.lower()
                and "0x" + topics[3][-40:].lower() == EXCHANGE_V2
            ):
                filled[topics[1].lower()] = {
                    "side": words[0],
                    "token": words[1],
                    "making": words[2],
                    "taking": words[3],
                    "fee_raw": words[4],
                    "log_index": int(log["logIndex"], 16),
                }
        else:
            if len(topics) != 3 or len(words) != 4:
                raise ValueError("Unexpected OrdersMatched v2 layout")
            if "0x" + topics[2][-40:].lower() == wallet.lower():
                matches.append((topics[1].lower(), words, log))
    result = []
    for order_hash, words, log in matches:
        aggregate = filled.get(order_hash)
        if not aggregate or [aggregate[k] for k in ("side", "token", "making", "taking")] != words:
            raise ValueError("Missing or inconsistent taker aggregate event")
        if words[0] not in (0, 1):
            raise ValueError("Invalid side enum")
        shares = Decimal(words[3] if words[0] == 0 else words[2]) / 1_000_000
        collateral = Decimal(words[2] if words[0] == 0 else words[3]) / 1_000_000
        result.append(
            {
                "transaction_hash": receipt["transactionHash"],
                "order_hash": order_hash,
                "trader_wallet": wallet.lower(),
                "token_id": str(words[1]),
                "side": "BUY" if words[0] == 0 else "SELL",
                "quantity": str(shares),
                "collateral": str(collateral),
                "vwap": str(collateral / shares),
                "role": "CHAIN_VERIFIED_TAKER",
                "fee_raw": aggregate["fee_raw"],
                "zero_exchange_fee_verified": aggregate["fee_raw"] == 0,
                "exchange": EXCHANGE_V2,
                "block_number": int(receipt["blockNumber"], 16),
                "transaction_index": int(receipt["transactionIndex"], 16),
                "matched_log_index": int(log["logIndex"], 16),
                "order_creation_time": None,
                "gas_excluded": True,
                "gas_payer": receipt.get("from"),
                "collateral_asset": "pUSD; 6 decimal places, reconciled to public source amounts",
                "evidence": "OrdersMatched.takerOrderMaker plus matching aggregate OrderFilled; raw receipt hash verified",
            }
        )
    return result


def role_evidence(snapshot: Path) -> dict[str, dict[str, Any]]:
    connection = sqlite3.connect(snapshot.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return {
            row["trade_id"]: row
            for (encoded,) in connection.execute(
                "SELECT payload FROM events WHERE kind='ROLE_EVIDENCE' ORDER BY id"
            )
            if (row := json.loads(encoded))
        }
    finally:
        connection.close()


def _levels(values: Any) -> dict[Decimal, Decimal]:
    if not isinstance(values, list):
        raise ValueError("Incomplete book")
    levels: dict[Decimal, Decimal] = {}
    for row in values:
        price, size = Decimal(str(row["price"])), Decimal(str(row["size"]))
        if not price.is_finite() or not size.is_finite() or not 0 <= price <= 1 or size < 0:
            raise ValueError("Invalid book level")
        if price in levels:
            raise ValueError("Duplicate level")
        if size > 0:
            levels[price] = size
    return levels


def _top(state: dict[str, Any]) -> tuple[Decimal | None, Decimal | None]:
    return max(state["bids"], default=None), min(state["asks"], default=None)


def _summary(state: dict[str, Any] | None) -> dict[str, Any]:
    if state is None:
        return {}
    bid, ask = _top(state)
    return {
        "received_at": state["received_at"].isoformat(),
        "book_event_id": state["id"],
        "best_bid": str(bid) if bid is not None else None,
        "best_ask": str(ask) if ask is not None else None,
        "bid_size": str(state["bids"][bid]) if bid is not None else None,
        "ask_size": str(state["asks"][ask]) if ask is not None else None,
        "ask_levels": len(state["asks"]),
        "bid_levels": len(state["bids"]),
        "connection_id": state.get("connection_id"),
        "source": state["source"],
        "valid": state["valid"],
        "mapping_verified": state["mapping_verified"],
        "consistency": state.get("consistency", "FULL_SNAPSHOT"),
        "source_timestamp": state.get("source_timestamp"),
        "raw_verified": state.get("raw_verified", False),
    }


def audit_books(snapshot: Path, trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one flat audit row per requested trade without modifying its records.

    Replay is local-receipt ordered, within one connection, and invalidates on
    unsubscribe/reconnect or inconsistent top quotes. No sequence-number guarantee
    is invented. Source block time remains a descriptive, second-precision anchor.
    """
    connection = sqlite3.connect(snapshot.resolve().as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    try:
        roles = role_evidence(snapshot)
        token_conditions = {str(t["token_id"]): str(t["condition_id"]) for t in trades}
        books: dict[str, list[tuple[datetime, int, dict[str, Any]]]] = defaultdict(list)
        raw_books: dict[tuple[str, datetime], dict[str, Any]] = {}
        for _, received, encoded in connection.execute(
            "SELECT id,received_at,payload FROM events WHERE kind='RAW' AND json_extract(payload,'$.url')='https://clob.polymarket.com/book' ORDER BY id"
        ):
            row = json.loads(encoded)
            try:
                body = json.loads(row["body"])
                token = str(body["asset_id"])
                body["_raw_verified"] = row.get("http_status") == 200 and hashlib.sha256(
                    row["body"].encode()
                ).hexdigest() == row.get("sha256")
                body["_raw_verified"] = (
                    body["_raw_verified"] and str(row.get("params", {}).get("token_id")) == token
                )
                body["_raw_sha256"] = row.get("sha256")
                raw_books[(token, utc(received))] = body
            except (ValueError, KeyError, TypeError):
                continue
        for event_id, received, encoded in connection.execute(
            "SELECT id,received_at,payload FROM events WHERE kind='BOOK' ORDER BY id"
        ):
            row = json.loads(encoded)
            token = str(row.get("token_id", ""))
            if token in token_conditions:
                books[token].append((utc(received), event_id, row))
        active_tokens = {
            token
            for token, entries in books.items()
            if any(
                utc(t["source_trade_timestamp"]) >= entries[0][0]
                for t in trades
                if str(t["token_id"]) == token
            )
        }
        events: list[tuple[datetime, int, str, dict[str, Any]]] = []
        subscriptions: dict[str, datetime] = {}
        subscription_states: list[tuple[datetime, set[str]]] = []
        for event_id, received, encoded in connection.execute(
            "SELECT id,received_at,payload FROM events WHERE kind IN ('STREAMHEALTH','STOP') ORDER BY id"
        ):
            row = json.loads(encoded)
            clock = utc(received)
            if "reason" in row and "state" not in row:
                row["state"] = "STOPPED"
            if row.get("state") in {"SUBSCRIBED", "SUBSCRIPTIONS_CHANGED"}:
                subscription_states.append((clock, set(str(t) for t in row.get("tokens", []))))
            elif row.get("state") in {"RECONNECTING", "STOPPED"}:
                subscription_states.append((clock, set()))
            for token in row.get("tokens", []):
                if str(token) in token_conditions:
                    subscriptions.setdefault(str(token), clock)
            events.append((clock, event_id, "HEALTH", row))
        for token in active_tokens:
            for clock, event_id, row in books[token]:
                events.append((clock, event_id, "BOOK", row))
        # Streaming scan: decode only relevant token payloads, not entire raw corpus.
        for event_id, received, encoded in connection.execute(
            "SELECT id,received_at,payload FROM events WHERE kind='WS_DELTA' ORDER BY id"
        ):
            if any(token in encoded for token in active_tokens):
                events.append((utc(received), event_id, "DELTA", json.loads(encoded)))
        events.sort(key=lambda event: (event[0], event[1]))
        states: dict[str, dict[str, Any]] = {}
        histories: dict[str, list[tuple[datetime, dict[str, Any]]]] = defaultdict(list)
        for clock, event_id, kind, row in events:
            if kind == "HEALTH":
                cid = row.get("connection_id")
                for token, state in states.items():
                    if row.get("state") == "STOPPED" and state.get("connection_id"):
                        state = {**state, "valid": False, "consistency": "MONITOR_STOPPED"}
                        states[token] = state
                        histories[token].append((clock, state))
                        continue
                    if (
                        row.get("state") == "SUBSCRIBED"
                        and state.get("connection_id")
                        and state["connection_id"] != cid
                    ):
                        state = {**state, "valid": False, "consistency": "CONNECTION_REPLACED"}
                        states[token] = state
                        histories[token].append((clock, state))
                        continue
                    if state.get("connection_id") != cid:
                        continue
                    if row.get("state") in {"RECONNECTING", "MALFORMED_MESSAGE"} or (
                        "tokens" in row and token not in row["tokens"]
                    ):
                        state = {
                            **state,
                            "valid": False,
                            "consistency": "CONNECTION_OR_SUBSCRIPTION_GAP",
                        }
                        states[token] = state
                        histories[token].append((clock, state))
                continue
            if kind == "BOOK":
                token = str(row["token_id"])
                raw = raw_books.get((token, clock))
                condition = row.get("market") or (raw.get("market") if raw else None)
                try:
                    state = {
                        "bids": _levels(row.get("bids")),
                        "asks": _levels(row.get("asks")),
                        "id": event_id,
                        "received_at": clock,
                        "connection_id": row.get("connection_id"),
                        "source": row.get("source", "UNKNOWN"),
                        "valid": row.get("complete") is True,
                        "source_timestamp": row.get("source_timestamp"),
                        "mapping_verified": condition == token_conditions[token],
                        "raw_verified": bool(
                            raw
                            and raw.get("_raw_verified")
                            and raw.get("asset_id") == token
                            and raw.get("market") == token_conditions[token]
                        ),
                    }
                except (ValueError, KeyError, TypeError):
                    if token in states:
                        invalid = {
                            **states[token],
                            "valid": False,
                            "consistency": "INVALID_FULL_SNAPSHOT",
                        }
                        states[token] = invalid
                        histories[token].append((clock, invalid))
                    continue
                state["valid"] = state["valid"] and state["mapping_verified"]
                states[token] = state
                histories[token].append((clock, state))
                continue
            changed: dict[str, dict[str, Any]] = {}
            for change in row.get("price_changes", []):
                token = str(change.get("asset_id", ""))
                previous = states.get(token)
                if (
                    not previous
                    or previous.get("connection_id") != row.get("connection_id")
                    or not previous["valid"]
                ):
                    continue
                if row.get("market") != token_conditions[token]:
                    invalid = {
                        **previous,
                        "valid": False,
                        "mapping_verified": False,
                        "consistency": "WRONG_DELTA_MARKET",
                    }
                    states[token] = invalid
                    histories[token].append((clock, invalid))
                    continue
                state = changed.setdefault(
                    token,
                    {**previous, "bids": dict(previous["bids"]), "asks": dict(previous["asks"])},
                )
                side = (
                    "bids"
                    if change.get("side") == "BUY"
                    else "asks"
                    if change.get("side") == "SELL"
                    else None
                )
                if side is None:
                    state["valid"] = False
                    continue
                price, size = Decimal(str(change["price"])), Decimal(str(change["size"]))
                if not price.is_finite() or not size.is_finite() or not 0 <= price <= 1 or size < 0:
                    state["valid"] = False
                    continue
                if size == 0:
                    state[side].pop(price, None)
                else:
                    state[side][price] = size
                state["last_change"] = change
            for token, state in changed.items():
                bid, ask = _top(state)
                last = state.pop("last_change", {})
                expected_bid = (
                    Decimal(str(last["best_bid"])) if last.get("best_bid") is not None else None
                )
                expected_ask = (
                    Decimal(str(last["best_ask"])) if last.get("best_ask") is not None else None
                )
                consistent = (
                    (bid if bid is not None else Decimal(0)) == expected_bid
                    if expected_bid is not None
                    else True
                ) and (
                    (ask if ask is not None else Decimal(1)) == expected_ask
                    if expected_ask is not None
                    else True
                )
                state.update(
                    id=event_id,
                    received_at=clock,
                    source="WS_REPLAY",
                    source_timestamp=row.get("source_timestamp"),
                    valid=state["valid"] and consistent,
                    consistency="CONSISTENT_REPLAY_UNSEQUENCED"
                    if consistent
                    else "TOP_QUOTE_MISMATCH",
                )
                states[token] = state
                histories[token].append((clock, state))
        result = []
        for trade in trades:
            token = str(trade["token_id"])
            source, detected = (
                utc(trade["source_trade_timestamp"]),
                utc(trade["first_collector_receipt_utc"]),
            )
            entries = histories.get(token, [])
            index = bisect_right([clock for clock, _ in entries], min(source, detected)) - 1
            pre = entries[index][1] if index >= 0 else None
            first = books.get(token, [])
            post = next((entry for entry in first if entry[0] >= detected), None)
            age = (source - pre["received_at"]).total_seconds() if pre else None
            subscription_index = (
                bisect_right([clock for clock, _ in subscription_states], min(source, detected)) - 1
            )
            subscribed_before_source = (
                token in subscription_states[subscription_index][1]
                if subscription_index >= 0
                else None
            )
            status = (
                "PRE_TRADE_BOOK_OBSERVED"
                if pre and pre["valid"] and age is not None and age <= 5
                else "STALE_BOOK"
                if pre and pre["valid"]
                else "WRONG_TOKEN_OR_MARKET"
                if pre and not pre["mapping_verified"]
                else "NO_VALID_BOOK"
            )
            if pre is None and first:
                status = "BOOK_FIRST_OBSERVED_AFTER_TRADE"
            role = roles.get(trade["trade_id"], {}).get("role", "UNKNOWN")
            row_out = {
                "trade_id": trade["trade_id"],
                "token_id": token,
                "condition_id": trade["condition_id"],
                "side": trade["side"],
                "book_status": status,
                "role": role,
                "first_subscription_at": subscriptions[token].isoformat()
                if token in subscriptions
                else None,
                "subscribed_at_source_anchor": subscribed_before_source,
                "first_book_received_at": first[0][0].isoformat() if first else None,
                "pre_book_age_seconds": age,
                "pre_book": _summary(pre),
                "clock_caveat": "Source block time is second precision and may follow actual matching; no proof of globally pre-execution book",
                "order_owner_attribution": "UNKNOWN",
                "limit_placement_time": None,
                "sequence_classification": "AGGRESSIVE_TAKER_EXIT"
                if trade["side"] == "SELL" and role == "API_ATTRIBUTED_TAKER"
                else "INSUFFICIENT_BOOK_HISTORY"
                if status != "PRE_TRADE_BOOK_OBSERVED"
                else "AMBIGUOUS",
            }
            if post:
                post_raw = raw_books.get((token, post[0]))
                confirmed = bool(
                    post_raw
                    and post_raw.get("_raw_verified")
                    and post_raw.get("asset_id") == token
                    and post_raw.get("market") == trade["condition_id"]
                    and isinstance(post_raw.get("asks"), list)
                    and isinstance(post_raw.get("bids"), list)
                    and post_raw["bids"] == post[2]["bids"]
                    and post_raw["asks"] == post[2]["asks"]
                )
                row_out.update(
                    first_post_book_received_at=post[0].isoformat(),
                    first_post_book_event_id=post[1],
                    first_post_raw_verified=confirmed,
                    first_post_best_bid=str(max(_levels(post[2]["bids"]), default=Decimal(0))),
                    first_post_best_ask=str(min(_levels(post[2]["asks"])))
                    if post[2]["asks"]
                    else None,
                    first_post_bid_size=str(_levels(post[2]["bids"])[max(_levels(post[2]["bids"]))])
                    if post[2]["bids"]
                    else None,
                    first_post_ask_size=str(_levels(post[2]["asks"])[min(_levels(post[2]["asks"]))])
                    if post[2]["asks"]
                    else None,
                    empty_side_status="EMPTY_SIDE_CONFIRMED"
                    if confirmed and post_raw is not None and not post_raw["asks"]
                    else "NOT_CONFIRMED",
                    first_post_raw_sha256=post_raw.get("_raw_sha256") if post_raw else None,
                )
                if (
                    confirmed
                    and post_raw is not None
                    and str(post_raw.get("timestamp", "")).isdigit()
                ):
                    row_out["provider_book_clock_minus_receipt_seconds"] = (
                        datetime.fromtimestamp(int(post_raw["timestamp"]) / 1000, UTC) - post[0]
                    ).total_seconds()
            result.append(row_out)
        return result
    finally:
        connection.close()
