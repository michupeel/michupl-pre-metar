"""Pure predefined price buckets; local Qwen proposal reviewed and tested."""

from decimal import Decimal


def price_bucket(price: Decimal) -> str:
    if not price.is_finite():
        raise ValueError("Price must be a finite number")

    if price < 0 or price > 1:
        raise ValueError("Price must be between 0 and 1 inclusive")

    if price < Decimal("0.50"):
        return "BELOW_0.50"

    buckets = [
        (Decimal("0.50"), Decimal("0.70"), "0.50–0.70"),
        (Decimal("0.70"), Decimal("0.80"), "0.70–0.80"),
        (Decimal("0.80"), Decimal("0.90"), "0.80–0.90"),
        (Decimal("0.90"), Decimal("0.95"), "0.90–0.95"),
        (Decimal("0.95"), Decimal("0.98"), "0.95–0.98"),
        (Decimal("0.98"), Decimal("1.00"), "0.98–1.00"),
    ]

    for lower, upper, label in buckets:
        if lower <= price < upper:
            return label

    # Handle the case where price == 1.00
    return "0.98–1.00"
