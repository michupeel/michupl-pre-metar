"""Delayed wallet association is descriptive, not evidence of a trigger."""

from datetime import timedelta
from typing import Any

from premetar.research.entry_timing_monitor import clock


def associate(surge: dict[str, Any], trades: list[dict[str, Any]], cutoff: str) -> dict[str, Any]:
    surge_condition = surge.get("condition_id")
    surge_received_iso = surge.get("received_at")
    surge_clock = clock(surge_received_iso)
    if surge_clock is None:
        raise ValueError(f"Invalid surge received_at: {surge_received_iso}")

    cutoff_dt = clock(cutoff)
    if cutoff_dt is None or cutoff_dt < surge_clock:
        raise ValueError("Cutoff must be a valid aware datetime ISO string")

    source_following = []
    detection_following = []
    seen_source = set()
    seen_detection = set()

    for trade in trades:
        if trade.get("condition_id") != surge_condition:
            continue
        side = trade.get("side")
        outcome = trade.get("outcome")
        source_ts_iso = trade.get("source_trade_timestamp")
        receipt_iso = trade.get("first_collector_receipt_utc")
        trade_id = trade.get("trade_id")

        if (
            side != "BUY"
            or str(outcome).lower() != "no"
            or trade.get("evidence_class") != "PROSPECTIVE_POLL"
            or not isinstance(trade_id, str)
            or not trade_id
        ):
            continue

        source_clock = clock(source_ts_iso)
        receipt_clock = clock(receipt_iso)

        if source_clock is None or receipt_clock is None:
            continue

        if receipt_clock > cutoff_dt:
            continue

        surge_delta_source = source_clock - surge_clock
        surge_delta_receipt = receipt_clock - surge_clock

        in_source_range = 0 <= surge_delta_source.total_seconds() <= 60
        in_detection_range = 0 <= surge_delta_receipt.total_seconds() <= 60

        if in_source_range and trade_id not in seen_source:
            source_following.append(trade_id)
            seen_source.add(trade_id)

        if in_detection_range and trade_id not in seen_detection:
            detection_following.append(trade_id)
            seen_detection.add(trade_id)

    source_following = sorted(set(source_following))
    detection_following = sorted(set(detection_following))

    has_any = len(source_following) > 0 or len(detection_following) > 0
    deadline = surge_clock + timedelta(seconds=300)

    if cutoff_dt < deadline:
        status = "PENDING_DELAYED_ATTRIBUTION"
    elif has_any:
        status = "OBSERVED_ASSOCIATION"
    else:
        status = "NO_ENTRY_OBSERVED_DELAY_CENSOR_REMAINS"

    return {
        "source_clock_following_trade_ids": source_following,
        "detection_following_trade_ids": detection_following,
        "status": status,
        "no_entry_proven": False,
        "independent_causality_proven": False,
    }
