"""Conditional quantity FIFO; neither opening inventory nor order intent is invented."""

from collections import defaultdict, deque
from datetime import datetime
from decimal import Decimal
from typing import Any

ZERO = Decimal(0)
DUST = Decimal("0.000002")


def reconstruct(
    trades: list[dict[str, Any]],
    nontrade_tokens: set[str] | None = None,
    verified_fees: dict[str, Decimal] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """One BUY lot per returned economic row, conditional on trade-only inventory.

    Same-second cross-side order and ambiguous same-transaction projections are
    quarantined. A clean trade ledger is NOT proof of zero pre-existing holdings.
    Exchange-fee net is separate from fully costed net (gas/relay cost unknown).
    """
    nontrade_tokens, verified_fees = nontrade_tokens or set(), verified_fees or {}
    by_token: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in trades:
        by_token[row["token_id"]].append(row)
    lots: list[dict[str, Any]] = []
    matches: list[dict[str, Any]] = []
    sales: list[dict[str, Any]] = []
    for token, events in sorted(by_token.items()):
        match_start = len(matches)
        events = sorted(
            events,
            key=lambda row: (
                row["source_trade_timestamp"],
                row["transaction_hash"],
                row["trade_id"],
            ),
        )
        clocks: dict[str, set[str]] = defaultdict(set)
        groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in events:
            clocks[row["source_trade_timestamp"]].add(row["side"])
            groups[(row["transaction_hash"], row["side"])].append(row)
        flags = []
        if any(len(sides) > 1 for sides in clocks.values()):
            flags.append("AMBIGUOUS_SAME_SECOND_BUY_SELL")
        if any(len(rows) > 1 for rows in groups.values()):
            flags.append("AMBIGUOUS_EXECUTION_GROUP")
        if token in nontrade_tokens:
            flags.append("NONTRADE_ACTIVITY_PRESENT")
        blocked = any(flag.startswith("AMBIGUOUS") for flag in flags)
        token_lots: list[dict[str, Any]] = []
        queue: deque[dict[str, Any]] = deque()
        oversell = ZERO
        for row in events:
            quantity, price = Decimal(str(row["size"])), Decimal(str(row["price"]))
            clock = datetime.fromisoformat(row["source_trade_timestamp"])
            if (
                quantity <= 0
                or not quantity.is_finite()
                or not price.is_finite()
                or not ZERO < price < 1
                or clock.tzinfo is None
            ):
                raise ValueError("Invalid normalized trade")
            if row["side"] == "BUY":
                lot = {
                    **row,
                    "buy_size": quantity,
                    "buy_price": price,
                    "buy_notional": quantity * price,
                    "matched_quantity": ZERO,
                    "sell_value": ZERO,
                    "matched_cost": ZERO,
                    "after_exchange_fee_pnl": ZERO,
                    "all_matched_exchange_fees_known": True,
                    "remaining_quantity": quantity if not blocked else None,
                    "last_matched_sell_time": None,
                    "quantity_time_sum": ZERO,
                    "close_quantity_by_5s": ZERO,
                    "close_quantity_by_10s": ZERO,
                    "close_quantity_by_30s": ZERO,
                    "close_quantity_by_60s": ZERO,
                    "sell_trade_ids": [],
                    "match_ids": [],
                    "status": "CONDITIONAL_TRADE_ONLY_FIFO",
                }
                token_lots.append(lot)
                if not blocked:
                    queue.append(lot)
                continue
            sale = {
                **row,
                "matched_quantity": ZERO,
                "unmatched_quantity": quantity,
                "status": "UNMATCHED_OR_UNKNOWN_OPENING",
            }
            sales.append(sale)
            if blocked:
                sale["status"] = "AMBIGUOUS_EXCLUDED"
                continue
            remaining = quantity
            while remaining > 0 and queue:
                lot = queue[0]
                amount = min(remaining, lot["remaining_quantity"])
                duration = (
                    clock - datetime.fromisoformat(lot["source_trade_timestamp"])
                ).total_seconds()
                if duration < 0:
                    raise ValueError("FIFO clock regression")
                gross = amount * (price - lot["buy_price"])
                buy_fee = verified_fees.get(lot["trade_id"])
                sell_fee = verified_fees.get(row["trade_id"])
                fee = (
                    (buy_fee * amount / lot["buy_size"] + sell_fee * amount / quantity)
                    if buy_fee is not None and sell_fee is not None
                    else None
                )
                match = {
                    "match_id": f"{lot['trade_id']}:{row['trade_id']}",
                    "buy_trade_id": lot["trade_id"],
                    "sell_trade_id": row["trade_id"],
                    "token_id": token,
                    "condition_id": row["condition_id"],
                    "quantity": amount,
                    "buy_price": lot["buy_price"],
                    "sell_price": price,
                    "buy_time": lot["source_trade_timestamp"],
                    "sell_time": row["source_trade_timestamp"],
                    "holding_seconds": duration,
                    "gross_pnl": gross,
                    "verified_exchange_fee": fee,
                    "after_exchange_fee_pnl": gross - fee if fee is not None else None,
                    "net_pnl": None,
                    "cost_status": "TOTAL_GAS_OR_RELAY_COST_UNKNOWN",
                    "accounting_status": "CONDITIONAL_TRADE_ONLY_FIFO",
                }
                matches.append(match)
                lot["match_ids"].append(match["match_id"])
                lot["sell_trade_ids"].append(row["trade_id"])
                lot["matched_quantity"] += amount
                lot["matched_cost"] += amount * lot["buy_price"]
                lot["sell_value"] += amount * price
                lot["quantity_time_sum"] += amount * Decimal(str(duration))
                lot["last_matched_sell_time"] = row["source_trade_timestamp"]
                lot["remaining_quantity"] -= amount
                if fee is None:
                    lot["all_matched_exchange_fees_known"] = False
                else:
                    lot["after_exchange_fee_pnl"] += gross - fee
                for seconds in (5, 10, 30, 60):
                    if duration <= seconds:
                        lot[f"close_quantity_by_{seconds}s"] += amount
                remaining -= amount
                if lot["remaining_quantity"] == 0:
                    queue.popleft()
            oversell += remaining
            sale["unmatched_quantity"] = remaining
            sale["matched_quantity"] = quantity - remaining
            sale["status"] = (
                "MATCHED_CONDITIONAL_FIFO"
                if remaining == 0
                else "UNKNOWN_OPENING_OR_NONTRADE_INVENTORY"
            )
        if oversell > DUST:
            flags.append("UNKNOWN_OPENING_OR_NONTRADE_INVENTORY")
        elif oversell > 0:
            flags.append("UNMATCHED_REPORTED_DUST")
        for lot in token_lots:
            matched = lot["matched_quantity"]
            lot["integrity_flags"] = flags.copy()
            lot["opening_inventory_status"] = (
                "UNVERIFIED_NO_INITIAL_BALANCE_OR_COMPLETE_TRANSFER_HISTORY"
            )
            lot["primary_eligible"] = not flags
            lot["fully_closed"] = not blocked and lot["remaining_quantity"] == 0
            lot["dust_tolerance_closed"] = not blocked and lot["remaining_quantity"] <= DUST
            lot["closed_fraction"] = matched / lot["buy_size"] if not blocked else None
            lot["holding_seconds"] = (
                (
                    datetime.fromisoformat(lot["last_matched_sell_time"])
                    - datetime.fromisoformat(lot["source_trade_timestamp"])
                ).total_seconds()
                if lot["fully_closed"]
                else None
            )
            lot["weighted_holding_seconds"] = (
                float(lot["quantity_time_sum"] / matched) if matched else None
            )
            lot["sell_vwap"] = lot["sell_value"] / matched if matched else None
            lot["gross_pnl"] = (
                lot["sell_value"] - lot["matched_cost"] if matched and not blocked else None
            )
            lot["net_pnl"] = None
            lot["adverse_move"] = None
            lot["adverse_move_status"] = "NO_COMPLETE_CONTEMPORANEOUS_MARK_TO_MARKET_PATH"
            lot["failed_exit_attempts"] = None
            lot["failed_exit_status"] = "UNOBSERVABLE_UNFILLED_ORDER_ATTEMPTS"
            lot["remaining_quantity_semantics"] = (
                "TRADE_LEDGER_REMAINDER_NOT_VERIFIED_CURRENT_WALLET_BALANCE"
            )
            lot["after_exchange_fee_pnl"] = (
                lot["after_exchange_fee_pnl"]
                if matched and lot["all_matched_exchange_fees_known"] and not blocked
                else None
            )
            lot["after_exchange_fee_return_on_matched_capital"] = (
                lot["after_exchange_fee_pnl"] / lot["matched_cost"]
                if lot["after_exchange_fee_pnl"] is not None and lot["matched_cost"]
                else None
            )
            lot["return_on_matched_capital_gross"] = (
                lot["gross_pnl"] / lot["matched_cost"]
                if lot["gross_pnl"] is not None and lot["matched_cost"]
                else None
            )
            if blocked:
                lot["status"] = "AMBIGUOUS_EXCLUDED"
            elif flags:
                lot["status"] = "CONDITIONAL_FLAGGED_FIFO"
            lot["inventory_exposure_unclosed_cost"] = (
                lot["remaining_quantity"] * lot["buy_price"]
                if lot["remaining_quantity"] is not None
                else None
            )
            lots.append(lot)
        for match in matches[match_start:]:
            match["integrity_flags"] = flags.copy()
            match["primary_eligible"] = not flags
            if flags:
                match["accounting_status"] = "CONDITIONAL_FLAGGED_FIFO"
    return lots, matches, sales
