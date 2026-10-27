"""Synthetic minimal receipts for complementary-side classification, no live calls."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.research import hightemptation_matching_paths as module  # noqa: E402


def test_two_buys_require_exact_sibling_mapping_and_collateral_sum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "snapshot.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE events(kind TEXT,payload TEXT)")
    conn.execute(
        "INSERT INTO events VALUES(?,?)", ("MARKET", json.dumps({"clobTokenIds": '["100","200"]'}))
    )
    conn.commit()
    conn.close()
    proof = {"quantity": "10", "collateral": "9.8", "side": "BUY", "token_id": "100"}
    monkeypatch.setattr(module, "decode_v2_receipt", lambda _: [proof])
    words = [0, 200, 200000, 10000000, 0, 0, 0]
    log = {
        "address": module.EXCHANGE_V2,
        "topics": [
            module.ORDER_FILLED_TOPIC,
            "0xhash",
            "0x" + "0" * 24 + "1" * 40,
            "0x" + "0" * 24 + module.WALLET[2:],
        ],
        "data": "0x" + "".join(f"{word:064x}" for word in words),
    }
    folder = tmp_path / "rpc"
    folder.mkdir()
    file = folder / "one.json"
    file.write_text(json.dumps({"body": json.dumps({"result": {"logs": [log]}})}))
    result = module.matching_paths(db, folder)[0]
    assert result["matching_path"] == "OPPOSITE_OUTCOME_BUY_BUY_MINT_SUPPORTED"
    assert result["sibling_token"] == "200"
    words[2] = 100000
    log["data"] = "0x" + "".join(f"{word:064x}" for word in words)
    file.write_text(json.dumps({"body": json.dumps({"result": {"logs": [log]}})}))
    assert module.matching_paths(db, folder)[0]["matching_path"] == "MIXED_OR_UNKNOWN"
