"""Conservative paired-liquidity evidence; no order or fill simulation."""

from typing import Any

from premetar.research.entry_timing_monitor import clock


def liquidity_paths(
    no: dict[str, Any] | None, yes: dict[str, Any] | None, decision_time: str
) -> dict[str, Any]:
    """Return a descriptive analysis of NO/YES liquidity relative to a decision time.

    Returns one of:
      - INSUFFICIENT_DATA (with reason)
      - THEORETICAL_COMPLEMENT_ONLY
      - NO_EXECUTABLE_PATH
    """

    def _parse_iso(ts: str) -> Any:
        return clock(ts)

    def _finite_float(v: Any) -> float | None:
        if v is None:
            return None
        if (
            not isinstance(v, bool)
            and isinstance(v, (int, float))
            and not (isinstance(v, float) and (v != v or v == float("inf") or v == float("-inf")))
        ):
            return float(v)
        return None

    def _bool_strict(v: Any) -> bool | None:
        if v is None:
            return None
        if isinstance(v, str):
            low = v.strip().lower()
            if low == "yes":
                return True
            if low == "no":
                return False
        if isinstance(v, bool):
            return v
        return None

    # 1. Clock validation
    try:
        decision_dt = _parse_iso(decision_time)
    except (ValueError, TypeError):
        raise ValueError("Invalid decision timestamp") from None

    if decision_dt is None:
        raise ValueError("Invalid decision timestamp")
    decision_val = clock(decision_time)
    if decision_val is None:
        return {"classification": "INSUFFICIENT_DATA", "reason": "clock_rejected_invalid_decision"}

    # 2. Book validation
    if no is None or yes is None:
        return {"classification": "INSUFFICIENT_DATA", "reason": "missing_book"}

    def _validate_book(b: dict[str, Any], label: str) -> dict[str, Any] | None:
        # Must have required keys
        for k in (
            "received_at",
            "bid",
            "ask",
            "bid_quantity",
            "ask_quantity",
            "state",
            "condition_id",
            "outcome",
            "token_id",
        ):
            if k not in b:
                return None
        return b

    no_book = _validate_book(no, "no")
    yes_book = _validate_book(yes, "yes")
    if no_book is None or yes_book is None:
        return {"classification": "INSUFFICIENT_DATA", "reason": "invalid_book_structure"}
    if not no.get("connection_id") or no.get("connection_id") != yes.get("connection_id"):
        return {"classification": "INSUFFICIENT_DATA", "reason": "UNVERIFIED_OR_DIFFERENT_SESSION"}

    # 3. Clock alignment checks
    try:
        no_received = _parse_iso(no_book["received_at"])
        yes_received = _parse_iso(yes_book["received_at"])
    except (ValueError, TypeError):
        return {"classification": "INSUFFICIENT_DATA", "reason": "invalid_book_receipt_time"}

    if (
        no_received is None
        or yes_received is None
        or any(not str(b.get("state", "")).startswith("VALID_") for b in (no, yes))
    ):
        return {"classification": "INSUFFICIENT_DATA", "reason": "invalid_book_state_or_clock"}

    # Book receipt > decision time is invalid
    for book in (no_book, yes_book):
        for field in ("bid", "ask"):
            raw = book.get(field)
            value = _finite_float(raw)
            if raw is not None and (value is None or not 0 <= value <= 1):
                return {"classification": "INSUFFICIENT_DATA", "reason": "INVALID_PRICE"}
        bid, ask = _finite_float(book.get("bid")), _finite_float(book.get("ask"))
        if bid is not None and ask is not None and bid >= ask:
            return {
                "classification": "INSUFFICIENT_DATA",
                "reason": "CROSSED_OR_INCONSISTENT_QUOTED_BOOK",
            }
    if no_received > decision_dt or yes_received > decision_dt:
        return {"classification": "INSUFFICIENT_DATA", "reason": "book_receipt_after_decision"}

    # Age > 10 seconds from decision
    age_no = abs((no_received - decision_dt).total_seconds())
    age_yes = abs((yes_received - decision_dt).total_seconds())
    if age_no > 10 or age_yes > 10:
        return {"classification": "INSUFFICIENT_DATA", "reason": "book_age_exceeds_10s"}

    # Receipt time difference must be <= 1 second
    abs_diff = abs((no_received - yes_received).total_seconds())
    if abs_diff > 1.0:
        return {
            "classification": "INSUFFICIENT_DATA",
            "reason": "receipt_time_difference_exceeds_1s",
        }

    # 4. Condition check: must be same and non-empty
    cond_no = no_book.get("condition_id")
    cond_yes = yes_book.get("condition_id")
    if not cond_no or not cond_yes or cond_no != cond_yes:
        return {"classification": "INSUFFICIENT_DATA", "reason": "condition_mismatch_or_empty"}

    # 5. Outcome check: must be No/Yes (case-insensitive) and different
    outcome_no = _bool_strict(no_book.get("outcome"))
    outcome_yes = _bool_strict(yes_book.get("outcome"))
    if outcome_no is None or outcome_yes is None:
        return {"classification": "INSUFFICIENT_DATA", "reason": "invalid_outcome"}
    if outcome_no is not False or outcome_yes is not True:
        return {"classification": "INSUFFICIENT_DATA", "reason": "outcomes_not_different"}

    # 6. Token check: must be same and non-empty
    token_no = no_book.get("token_id")
    token_yes = yes_book.get("token_id")
    if not token_no or not token_yes or token_no == token_yes:
        return {"classification": "INSUFFICIENT_DATA", "reason": "token_mismatch_or_empty"}

    # 7. Extract numeric values
    no_ask_f = _finite_float(no_book.get("ask"))
    no_bid_f = _finite_float(no_book.get("bid"))
    yes_bid_f = _finite_float(yes_book.get("bid"))

    # 8. Check if both purchase sides (NO ask and YES bid) are None
    if no_ask_f is None and yes_bid_f is None:
        return {
            "classification": "NO_EXECUTABLE_PATH",
            "reason": "NO_RECORDED_PURCHASE_SIDE_NOT_A_GLOBAL_LIQUIDITY_CLAIM",
        }

    # 9. Compute theoretical complement result
    direct_no_ask = no_ask_f if no_ask_f is not None else None

    # theoretical_no_from_yes_bid: 1 - yes.bid if finite bid in [0,1]
    theoretical_no_from_yes_bid = None
    if yes_bid_f is not None and 0 <= yes_bid_f <= 1:
        theoretical_no_from_yes_bid = 1 - yes_bid_f

    direct_quantity = no_book.get("ask_quantity")
    complementary_quantity = yes_book.get("bid_quantity")
    exit_no_bid = no_bid_f if no_bid_f is not None else None

    return {
        "classification": "THEORETICAL_COMPLEMENT_ONLY",
        "direct_no_ask": direct_no_ask,
        "theoretical_no_from_yes_bid": theoretical_no_from_yes_bid,
        "direct_quantity": direct_quantity,
        "complementary_quantity": complementary_quantity,
        "exit_no_bid": exit_no_bid,
        "fees": None,
        "supported_fill_quantity": None,
        "net_profit": None,
        "apparent_crossed_complement": no_bid_f is not None
        and yes_bid_f is not None
        and no_bid_f + yes_bid_f > 1,
        "reason": "EXCHANGE_VERSION_ATOMIC_MATCH_FEES_QUEUE_UNVERIFIED",
    }
