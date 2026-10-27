"""Synthetic message fixtures derived from saved public CLOB and receipt shapes."""

import hashlib
import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.research.hightemptation_books import (  # noqa: E402
    EXCHANGE_V2,
    ORDER_FILLED_TOPIC,
    ORDERS_MATCHED_TOPIC,
    WALLET,
    _keccak,
    audit_books,
    decode_v2_receipt,
    verify_event_topics,
)

BASE = datetime(2026, 10, 27, 9, 22, 30, tzinfo=UTC)
TOKEN = "123"
CONDITION = "0xcondition"


def trade(side: str = "BUY", second: float = 0) -> dict[str, Any]:
    return {
        "trade_id": "t",
        "token_id": TOKEN,
        "condition_id": CONDITION,
        "side": side,
        "source_trade_timestamp": (BASE + timedelta(seconds=second)).isoformat(),
        "first_collector_receipt_utc": (BASE + timedelta(seconds=second + 3)).isoformat(),
    }


def snapshot(tmp_path: Path, events: list[tuple[str, float, dict[str, Any]]]) -> Path:
    path = tmp_path / "snapshot.sqlite3"
    with sqlite3.connect(path) as c:
        c.execute(
            "CREATE TABLE events(id INTEGER PRIMARY KEY,kind TEXT,received_at TEXT,payload TEXT)"
        )
        for kind, second, payload in events:
            c.execute(
                "INSERT INTO events(kind,received_at,payload) VALUES(?,?,?)",
                (kind, (BASE + timedelta(seconds=second)).isoformat(), json.dumps(payload)),
            )
    return path


def book(
    *,
    connection: str | None = "one",
    market: str = CONDITION,
    asks: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "token_id": TOKEN,
        "market": market,
        "connection_id": connection,
        "complete": True,
        "bids": [{"price": "0.90", "size": "20"}],
        "asks": asks if asks is not None else [{"price": "0.98", "size": "38.35"}],
        "source": "WS_FULL_SNAPSHOT",
        "source_timestamp": "1793092950000",
    }


def delta(
    *, market: str = CONDITION, connection: str = "one", best_ask: str = "1"
) -> dict[str, Any]:
    return {
        "connection_id": connection,
        "market": market,
        "price_changes": [
            {
                "asset_id": TOKEN,
                "price": "0.98",
                "size": "0",
                "side": "SELL",
                "best_bid": "0.90",
                "best_ask": best_ask,
            }
        ],
    }


def test_full_book_received_after_trade_never_fills_pretrade_history(tmp_path: Path) -> None:
    row = audit_books(snapshot(tmp_path, [("BOOK", 1, book())]), [trade()])[0]
    assert row["book_status"] == "BOOK_FIRST_OBSERVED_AFTER_TRADE"
    assert row["pre_book"] == {}


def test_same_connection_replay_deletes_level_and_preserves_unknown_owner(tmp_path: Path) -> None:
    row = audit_books(
        snapshot(tmp_path, [("BOOK", -3, book()), ("WS_DELTA", -1, delta())]), [trade()]
    )[0]
    assert row["book_status"] == "PRE_TRADE_BOOK_OBSERVED"
    assert row["pre_book"]["best_ask"] is None
    assert row["pre_book"]["source"] == "WS_REPLAY"
    assert row["order_owner_attribution"] == "UNKNOWN"
    assert row["limit_placement_time"] is None


def test_inconsistent_delta_invalidates_snapshot(tmp_path: Path) -> None:
    row = audit_books(
        snapshot(tmp_path, [("BOOK", -3, book()), ("WS_DELTA", -1, delta(best_ask="0.99"))]),
        [trade()],
    )[0]
    assert row["book_status"] == "NO_VALID_BOOK"
    assert row["pre_book"]["consistency"] == "TOP_QUOTE_MISMATCH"


def test_reconnect_cannot_forwardfill_old_snapshot(tmp_path: Path) -> None:
    row = audit_books(
        snapshot(
            tmp_path,
            [
                ("BOOK", -3, book()),
                ("STREAMHEALTH", -2, {"state": "RECONNECTING", "connection_id": "one"}),
                ("WS_DELTA", -1, delta()),
            ],
        ),
        [trade()],
    )[0]
    assert row["book_status"] == "NO_VALID_BOOK"
    assert not row["pre_book"]["valid"]


def test_new_connection_and_stop_invalidate_previous_epoch(tmp_path: Path) -> None:
    row = audit_books(
        snapshot(
            tmp_path,
            [
                ("BOOK", -3, book()),
                ("STOP", -2, {"reason": "GRACEFUL_STOP"}),
                (
                    "STREAMHEALTH",
                    -1,
                    {"state": "SUBSCRIBED", "connection_id": "two", "tokens": [TOKEN]},
                ),
            ],
        ),
        [trade()],
    )[0]
    assert row["book_status"] == "NO_VALID_BOOK"
    assert not row["pre_book"]["valid"]


def test_unsubscribe_disables_old_state(tmp_path: Path) -> None:
    row = audit_books(
        snapshot(
            tmp_path,
            [
                ("BOOK", -3, book()),
                (
                    "STREAMHEALTH",
                    -1,
                    {"state": "SUBSCRIPTIONS_CHANGED", "connection_id": "one", "tokens": []},
                ),
            ],
        ),
        [trade()],
    )[0]
    assert row["book_status"] == "NO_VALID_BOOK"
    assert row["subscribed_at_source_anchor"] is False


def test_wrong_market_cannot_be_pretrade_book(tmp_path: Path) -> None:
    row = audit_books(snapshot(tmp_path, [("BOOK", -1, book(market="0xwrong"))]), [trade()])[0]
    assert row["book_status"] == "WRONG_TOKEN_OR_MARKET"


def test_stale_book_not_forwardfilled(tmp_path: Path) -> None:
    row = audit_books(snapshot(tmp_path, [("BOOK", -10, book())]), [trade()])[0]
    assert row["book_status"] == "STALE_BOOK"


def test_raw_verified_empty_asks_different_from_missing_asks(tmp_path: Path) -> None:
    payload = {
        "asset_id": TOKEN,
        "market": CONDITION,
        "bids": [{"price": "0.99", "size": "100"}],
        "asks": [],
        "timestamp": str(int((BASE + timedelta(seconds=4)).timestamp() * 1000)),
    }
    body = json.dumps(payload)
    raw = {
        "url": "https://clob.polymarket.com/book",
        "params": {"token_id": TOKEN},
        "http_status": 200,
        "body": body,
        "sha256": hashlib.sha256(body.encode()).hexdigest(),
    }
    normalized = {
        **book(connection=None),
        "bids": payload["bids"],
        "asks": [],
        "source": "REST_POST_DEADLINE",
    }
    row = audit_books(
        snapshot(tmp_path, [("RAW", 3.5, raw), ("BOOK", 3.5, normalized)]), [trade()]
    )[0]
    assert row["empty_side_status"] == "EMPTY_SIDE_CONFIRMED"
    assert row["first_post_raw_sha256"] == raw["sha256"]
    assert row["provider_book_clock_minus_receipt_seconds"] == 0.5


def test_empty_normalized_side_without_raw_is_not_confirmed(tmp_path: Path) -> None:
    row = audit_books(snapshot(tmp_path, [("BOOK", 4, book(asks=[]))]), [trade()])[0]
    assert row["empty_side_status"] == "NOT_CONFIRMED"


def test_positive_api_taker_only_supports_aggressive_exit_not_order_placement(
    tmp_path: Path,
) -> None:
    row = audit_books(
        snapshot(
            tmp_path, [("ROLE_EVIDENCE", 10, {"trade_id": "t", "role": "API_ATTRIBUTED_TAKER"})]
        ),
        [trade("SELL")],
    )[0]
    assert row["role"] == "API_ATTRIBUTED_TAKER"
    assert row["sequence_classification"] == "AGGRESSIVE_TAKER_EXIT"
    assert row["limit_placement_time"] is None


def test_ethereum_keccak_topics_match_official_v2_abi() -> None:
    assert verify_event_topics()
    assert _keccak(b"abc") == "0x4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45"


def rpc_envelope() -> dict[str, Any]:
    def topic_address(address: str) -> str:
        return "0x" + "0" * 24 + address.removeprefix("0x")

    def words(values: list[int]) -> str:
        return "0x" + "".join(f"{value:064x}" for value in values)

    order = "0x" + "a" * 64
    logs = [
        {
            "address": EXCHANGE_V2,
            "topics": [
                ORDER_FILLED_TOPIC,
                order,
                topic_address(WALLET),
                topic_address(EXCHANGE_V2),
            ],
            "data": words([0, 123, 37583000, 38350000, 0, 0, 0]),
            "logIndex": "0x1",
        },
        {
            "address": EXCHANGE_V2,
            "topics": [ORDERS_MATCHED_TOPIC, order, topic_address(WALLET)],
            "data": words([0, 123, 37583000, 38350000]),
            "logIndex": "0x2",
        },
    ]
    body = json.dumps(
        {
            "result": {
                "status": "0x1",
                "transactionHash": "0xtx",
                "blockNumber": "0x10",
                "transactionIndex": "0x1",
                "logs": logs,
            }
        }
    )
    return {
        "transaction": "0xtx",
        "body": body,
        "sha256": hashlib.sha256(body.encode()).hexdigest(),
    }


def test_orders_matched_identifies_active_wallet_and_exact_historical_fee() -> None:
    result = decode_v2_receipt(rpc_envelope())
    assert result[0]["role"] == "CHAIN_VERIFIED_TAKER"
    assert result[0]["quantity"] == "38.35"
    assert result[0]["collateral"] == "37.583"
    assert result[0]["zero_exchange_fee_verified"]
    assert result[0]["order_creation_time"] is None


def test_order_filled_maker_field_alone_does_not_prove_passive_role() -> None:
    envelope = rpc_envelope()
    parsed = json.loads(envelope["body"])
    parsed["result"]["logs"] = parsed["result"]["logs"][:1]
    envelope["body"] = json.dumps(parsed)
    envelope["sha256"] = hashlib.sha256(envelope["body"].encode()).hexdigest()
    assert decode_v2_receipt(envelope) == []


def test_corrupt_rpc_body_cannot_classify_role() -> None:
    envelope = rpc_envelope()
    envelope["sha256"] = "wrong"
    with pytest.raises(ValueError, match="hash mismatch"):
        decode_v2_receipt(envelope)
