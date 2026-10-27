"""Pure, conservative shadow execution; this module cannot submit orders.

Snapshots must be collected after the simulated execution deadline.  A later
snapshot is an opportunity at its receipt time, never a fill backdated to the
deadline.  Displayed liquidity is a simulation assumption, not a guaranteed fill.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

ZERO = Decimal(0)
ONE = Decimal(1)


@dataclass(frozen=True)
class Level:
    price: Decimal
    size: Decimal


@dataclass(frozen=True)
class FeePolicy:
    """Caller-verified fee parameters; no market-wide fee default is assumed.

    USD fee per share = rate * (price * (1-price)) ** exponent, optionally
    multiplied by price. ``evidence`` identifies the verified market/config.
    This intentionally does not certify exchange rounding or rebates.
    """

    rate: Decimal
    exponent: int
    evidence: str
    price_multiplier: bool

    def per_share(self, price: Decimal) -> Decimal:
        if not self.rate.is_finite() or self.rate < ZERO or self.exponent < 0:
            raise ValueError("Invalid fee parameters")
        if not self.evidence.strip():
            raise ValueError("Fee policy requires verification evidence")
        return (
            self.rate
            * (price * (ONE - price)) ** self.exponent
            * (price if self.price_multiplier else ONE)
        )


@dataclass(frozen=True)
class BookSnapshot:
    token_id: str
    received_at: datetime
    bids: tuple[Level, ...]
    asks: tuple[Level, ...]
    complete: bool = True


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    quantity: Decimal = ZERO
    gross_value: Decimal = ZERO
    fee: Decimal | None = None
    net_value: Decimal | None = None
    vwap: Decimal | None = None
    unfilled: Decimal = ZERO
    reason: str = ""
    executed_at: datetime | None = None


def _book_reason(
    book: BookSnapshot,
    detected_at: datetime,
    due_at: datetime,
    decision_at: datetime,
    max_book_age_seconds: float,
    market_open: bool | None,
) -> str:
    if any(
        value.tzinfo is None or value.utcoffset() is None
        for value in (book.received_at, detected_at, due_at, decision_at)
    ):
        return "NAIVE_TIMESTAMP"
    if max_book_age_seconds < 0:
        return "INVALID_MAX_BOOK_AGE"
    if due_at < detected_at or decision_at < due_at:
        return "INVALID_EXECUTION_DEADLINE"
    if book.received_at <= detected_at or book.received_at < due_at:
        return "BOOK_BEFORE_EXECUTION_DEADLINE"
    if book.received_at > decision_at:
        return "FUTURE_BOOK"
    if (decision_at - book.received_at).total_seconds() > max_book_age_seconds:
        return "STALE_BOOK"
    if market_open is not True:
        return "MARKET_CLOSED" if market_open is False else "UNKNOWN_MARKET_STATE"
    if not book.complete:
        return "INCOMPLETE_BOOK"
    if not book.token_id:
        return "MISSING_TOKEN_ID"
    for levels in (book.bids, book.asks):
        if len({level.price for level in levels}) != len(levels):
            return "DUPLICATE_BOOK_LEVEL"
        for level in levels:
            if (
                not level.price.is_finite()
                or not level.size.is_finite()
                or not ZERO < level.price < ONE
                or level.size <= ZERO
            ):
                return "INVALID_BOOK_LEVEL"
    if (
        book.bids
        and book.asks
        and max(level.price for level in book.bids) >= min(level.price for level in book.asks)
    ):
        return "CROSSED_BOOK"
    return ""


def _result(
    quantity: Decimal,
    gross: Decimal,
    fee: Decimal,
    unfilled: Decimal,
    fee_policy: FeePolicy | None,
    book: BookSnapshot,
    *,
    buy: bool,
) -> ExecutionResult:
    if quantity == ZERO:
        return ExecutionResult("NO_LIQUIDITY", unfilled=unfilled, reason="EMPTY_EXECUTABLE_SIDE")
    status = "PARTIAL" if unfilled > Decimal("0.000000000001") else "FILLED"
    if fee_policy is None:
        status += "_FEE_UNKNOWN"
    return ExecutionResult(
        status=status,
        quantity=quantity,
        gross_value=gross,
        fee=fee if fee_policy is not None else None,
        net_value=(gross + fee if buy else gross - fee) if fee_policy is not None else None,
        vwap=gross / quantity,
        unfilled=max(ZERO, unfilled),
        reason="DISPLAYED_DEPTH_SIMULATION_ONLY",
        executed_at=book.received_at,
    )


def simulate_buy(
    book: BookSnapshot,
    notional: Decimal,
    *,
    detected_at: datetime,
    due_at: datetime,
    decision_at: datetime,
    fee_policy: FeePolicy | None = None,
    max_book_age_seconds: float = 5,
    market_open: bool | None = None,
) -> ExecutionResult:
    """Walk asks. With known fees, notional is the maximum total USD debit.

    Unknown fees permit only a gross-liquidity scenario, never a certified
    all-in cost or a claim that the position fits the requested cash budget.
    ``unfilled`` is remaining USD budget, unlike SELL's remaining shares.
    """
    if not notional.is_finite() or notional <= ZERO:
        raise ValueError("Notional must be positive and finite")
    reason = _book_reason(book, detected_at, due_at, decision_at, max_book_age_seconds, market_open)
    if reason:
        return ExecutionResult("UNKNOWN", unfilled=notional, reason=reason)
    quantity = gross = fee = ZERO
    remaining = notional
    for level in sorted(book.asks, key=lambda item: item.price):
        fee_per_share = fee_policy.per_share(level.price) if fee_policy else ZERO
        amount = min(level.size, remaining / (level.price + fee_per_share))
        quantity += amount
        gross += amount * level.price
        fee += amount * fee_per_share
        remaining -= amount * (level.price + fee_per_share)
        if remaining <= ZERO:
            break
    return _result(quantity, gross, fee, remaining, fee_policy, book, buy=True)


def simulate_sell(
    book: BookSnapshot,
    quantity: Decimal,
    *,
    holdings: Decimal,
    detected_at: datetime,
    due_at: datetime,
    decision_at: datetime,
    fee_policy: FeePolicy | None = None,
    max_book_age_seconds: float = 5,
    market_open: bool | None = None,
) -> ExecutionResult:
    """Walk bids without shorting; unfilled is requested shares not sold."""
    if not quantity.is_finite() or quantity <= ZERO or not holdings.is_finite() or holdings < ZERO:
        raise ValueError("Quantity/holdings must be finite and nonnegative")
    reason = _book_reason(book, detected_at, due_at, decision_at, max_book_age_seconds, market_open)
    if reason:
        return ExecutionResult("UNKNOWN", unfilled=quantity, reason=reason)
    remaining = min(quantity, holdings)
    sold = gross = fee = ZERO
    for level in sorted(book.bids, key=lambda item: item.price, reverse=True):
        amount = min(level.size, remaining)
        fee_per_share = fee_policy.per_share(level.price) if fee_policy else ZERO
        sold += amount
        gross += amount * level.price
        fee += amount * fee_per_share
        remaining -= amount
        if remaining <= ZERO:
            break
    return _result(sold, gross, fee, quantity - sold, fee_policy, book, buy=False)
