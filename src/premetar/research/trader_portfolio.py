"""Pure reconstruction of append-only shadow lots and exits.

Plans do not reserve or sell holdings. Callers persist actual simulated fills,
then reconstruct remaining holdings from those immutable events. Lots must be
provided in original BUY receipt order. There are no orders or database writes.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import TypedDict

ZERO = Decimal(0)
TAKE_PROFIT_INCREMENT = Decimal("0.05")
TAKE_PROFIT_CAP = Decimal("0.99")


@dataclass(frozen=True)
class ShadowLot:
    lot_id: str
    token_id: str
    strategy: str
    delay_seconds: int
    notional: Decimal
    quantity: Decimal
    target_buy_quantity: Decimal
    entry_gross: Decimal
    entry_fee: Decimal | None
    entry_net: Decimal | None
    entry_vwap: Decimal


@dataclass(frozen=True)
class ExitRecord:
    lot_id: str
    quantity: Decimal
    gross_value: Decimal
    fee: Decimal | None
    net_value: Decimal | None
    kind: str


@dataclass(frozen=True)
class ExitPlan:
    lot_id: str
    token_id: str
    quantity: Decimal
    kind: str
    limit_price: Decimal | None = None
    payout_per_share: Decimal | None = None


def remaining_quantity(lot: ShadowLot, exits: list[ExitRecord]) -> Decimal:
    if not lot.quantity.is_finite() or lot.quantity <= ZERO:
        raise ValueError("Lot quantity must be positive and finite")
    sold = ZERO
    for event in exits:
        if event.lot_id == lot.lot_id:
            if not event.quantity.is_finite() or event.quantity < ZERO:
                raise ValueError("Exit quantity must be finite and nonnegative")
            sold += event.quantity
    if sold > lot.quantity:
        raise ValueError("Immutable exits exceed lot holdings")
    return lot.quantity - sold


def follow_exit_plans(
    lots: list[ShadowLot],
    exits: list[ExitRecord],
    *,
    token_id: str,
    target_sell_quantity: Decimal,
) -> list[ExitPlan]:
    """FIFO target shares separately for each delay/notional shadow cohort.

    A copied lot represents a fraction of its original source BUY shares. The
    public SELL consumes source shares once per cohort, not once per lot. If
    previous execution failed, the next SELL still sees actual remaining copy
    holdings. Source positions before monitoring are unknowable; this rule is
    explicitly a frozen copy-position allocation, not wallet inventory truth.
    """
    if not target_sell_quantity.is_finite() or target_sell_quantity < ZERO:
        raise ValueError("Target SELL size must be finite and nonnegative")
    budgets: dict[tuple[int, Decimal], Decimal] = {}
    plans: list[ExitPlan] = []
    for lot in lots:
        if lot.token_id != token_id or lot.strategy != "COPY_FOLLOW":
            continue
        if not lot.target_buy_quantity.is_finite() or lot.target_buy_quantity <= ZERO:
            raise ValueError("Original target BUY quantity must be positive")
        remaining = remaining_quantity(lot, exits)
        cohort = (lot.delay_seconds, lot.notional)
        budget = budgets.get(cohort, target_sell_quantity)
        source_equivalent = remaining / lot.quantity * lot.target_buy_quantity
        consumed = min(budget, source_equivalent)
        if consumed > ZERO:
            amount = min(remaining, consumed / lot.target_buy_quantity * lot.quantity)
            plans.append(ExitPlan(lot.lot_id, token_id, amount, "COPY_FOLLOW"))
            budgets[cohort] = budget - consumed
    return plans


def take_profit_plans(
    lots: list[ShadowLot],
    exits: list[ExitRecord],
    *,
    token_id: str,
    best_bid: Decimal,
) -> list[ExitPlan]:
    """Frozen absolute-price +0.05 target capped at 0.99, before exit fees.

    Depth execution still has to be simulated at/above the returned limit. A
    quote touching the threshold alone is not a successful fill or net profit.
    """
    if not best_bid.is_finite() or not ZERO <= best_bid <= 1:
        raise ValueError("Invalid best bid")
    plans: list[ExitPlan] = []
    for lot in lots:
        if lot.token_id != token_id or lot.strategy != "COPY_TAKE_PROFIT":
            continue
        if not lot.entry_vwap.is_finite() or not ZERO < lot.entry_vwap < 1:
            raise ValueError("Invalid entry VWAP")
        threshold = min(TAKE_PROFIT_CAP, lot.entry_vwap + TAKE_PROFIT_INCREMENT)
        # A capped threshold below entry is not a take-profit opportunity.
        if threshold <= lot.entry_vwap:
            continue
        remaining = remaining_quantity(lot, exits)
        if remaining > ZERO and best_bid >= threshold:
            plans.append(ExitPlan(lot.lot_id, token_id, remaining, "COPY_TAKE_PROFIT", threshold))
    return plans


def settlement_plans(
    lots: list[ShadowLot],
    exits: list[ExitRecord],
    *,
    token_id: str,
    payout: Decimal,
    verified_resolution: bool,
) -> list[ExitPlan]:
    """Only caller-verified final token payout 0/1 permits paper settlement."""
    if not verified_resolution:
        return []
    if payout not in (ZERO, Decimal(1)):
        raise ValueError("Only verified final binary 0/1 payouts supported")
    plans = []
    for lot in lots:
        if lot.token_id == token_id:
            remaining = remaining_quantity(lot, exits)
            if remaining > ZERO:
                plans.append(
                    ExitPlan(lot.lot_id, token_id, remaining, "SETTLEMENT", payout_per_share=payout)
                )
    return plans


class PortfolioMetrics(TypedDict):
    lot_count: int
    closed_lots: int
    unresolved_lots: int
    unverifiable_closed_lots: int
    verified_closed_lots: int
    wins: int
    losses: int
    break_even: int
    net_pnl: Decimal | None
    closed_cost: Decimal
    net_roi: Decimal | None
    win_rate: Decimal | None
    profit_factor: Decimal | None
    average_profit: Decimal | None
    average_loss: Decimal | None
    maximum_closed_equity_drawdown: Decimal | None
    unresolved_quantity: Decimal


def portfolio_metrics(lots: list[ShadowLot], exits: list[ExitRecord]) -> PortfolioMetrics:
    """Only fully closed, fee-known lots contribute to realized net metrics.

    Drawdown follows final exit-record order, excludes open inventory, and is
    explicitly closed-equity drawdown, not marked portfolio drawdown.
    """
    if len({lot.lot_id for lot in lots}) != len(lots):
        raise ValueError("Duplicate immutable lot IDs")
    known_ids = {lot.lot_id for lot in lots}
    if any(event.lot_id not in known_ids for event in exits):
        raise ValueError("Exit without original lot")
    closed = unknown = 0
    unresolved = ZERO
    costs = ZERO
    pnl_by_lot: dict[str, Decimal] = {}
    for lot in lots:
        remaining = remaining_quantity(lot, exits)
        if remaining > ZERO:
            unresolved += remaining
            continue
        closed += 1
        events = [event for event in exits if event.lot_id == lot.lot_id]
        if (
            lot.entry_fee is None
            or lot.entry_net is None
            or any(event.fee is None or event.net_value is None for event in events)
        ):
            unknown += 1
            continue
        proceeds = sum((event.net_value for event in events if event.net_value is not None), ZERO)
        costs += lot.entry_net
        pnl_by_lot[lot.lot_id] = proceeds - lot.entry_net
    profits = [value for value in pnl_by_lot.values() if value > ZERO]
    losses = [value for value in pnl_by_lot.values() if value < ZERO]
    pnl = sum(pnl_by_lot.values(), ZERO)
    equity = peak = drawdown = ZERO
    ordered = sorted(
        pnl_by_lot, key=lambda key: max(i for i, event in enumerate(exits) if event.lot_id == key)
    )
    for key in ordered:
        equity += pnl_by_lot[key]
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    count = len(pnl_by_lot)
    return {
        "lot_count": len(lots),
        "closed_lots": closed,
        "unresolved_lots": len(lots) - closed,
        "unverifiable_closed_lots": unknown,
        "verified_closed_lots": count,
        "wins": len(profits),
        "losses": len(losses),
        "break_even": count - len(profits) - len(losses),
        "net_pnl": pnl if count else None,
        "closed_cost": costs,
        "net_roi": pnl / costs if costs > ZERO else None,
        "win_rate": Decimal(len(profits)) / Decimal(count) if count else None,
        "profit_factor": sum(profits, ZERO) / -sum(losses, ZERO) if losses else None,
        "average_profit": sum(profits, ZERO) / Decimal(len(profits)) if profits else None,
        "average_loss": sum(losses, ZERO) / Decimal(len(losses)) if losses else None,
        "maximum_closed_equity_drawdown": drawdown if count else None,
        "unresolved_quantity": unresolved,
    }
