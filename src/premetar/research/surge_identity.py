"""Exact public-message transaction join; never infer wallet from a market print."""

import json
import re
from typing import Any


def match_public_trade(
    raw_text: str, transaction_hash: str, token_id: str
) -> dict[str, Any] | None:
    """Find the unique trade entry matching token_id and transaction_hash.

    Returns a copy of the matching dictionary if exactly one entry matches,
    otherwise returns None. Handles malformed JSON, invalid hashes, and
    ambiguous (duplicate) matches.
    """
    try:
        data = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        return None

    # Normalize input data to a list of dicts
    if isinstance(data, dict):
        entries: list[dict[str, Any]] = [data]
    elif isinstance(data, list):
        entries = [e for e in data if isinstance(e, dict)]
    else:
        return None

    # Validate transaction_hash format
    if not re.fullmatch(r"0x[0-9a-fA-F]{64}", transaction_hash):
        return None

    # Validate token_id is non-empty
    if not token_id:
        return None

    # Find matching entries
    matches: list[dict[str, Any]] = []
    for entry in entries:
        if entry.get("event_type") != "last_trade_price":
            continue
        if str(entry.get("asset_id", "")) != token_id:
            continue
        entry_hash = entry.get("transaction_hash", "")
        if not isinstance(entry_hash, str):
            continue
        if entry_hash.casefold() == transaction_hash.casefold():
            matches.append(entry)

    # Return copy only if exactly one match
    if len(matches) == 1:
        return dict(matches[0])
    return None
