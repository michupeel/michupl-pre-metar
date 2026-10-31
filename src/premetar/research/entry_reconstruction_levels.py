"""Apply public absolute price-level updates to a recorded snapshot."""

from decimal import Decimal, InvalidOperation
from typing import Any


def update_levels(
    levels: list[dict[str, Any]], changes: list[dict[str, Any]]
) -> list[dict[str, str]]:
    if not isinstance(levels, list) or not isinstance(changes, list):
        raise ValueError("Levels and changes must be lists")
    level_map: dict[Decimal, Decimal] = {}
    for lvl in levels:
        if not isinstance(lvl, dict) or "price" not in lvl or "size" not in lvl:
            raise ValueError("Missing keys in level")
        try:
            p = Decimal(str(lvl["price"]))
            s = Decimal(str(lvl["size"]))
        except InvalidOperation as error:
            raise ValueError("Invalid decimal level") from error
        if not p.is_finite() or not (Decimal(0) <= p <= Decimal(1)):
            raise ValueError(f"Invalid price: {p}")
        if not s.is_finite() or s < 0:
            raise ValueError(f"Invalid size: {s}")
        level_map[p] = s
    for chg in changes:
        if not isinstance(chg, dict) or "price" not in chg or "size" not in chg:
            raise ValueError("Missing keys in change")
        try:
            p = Decimal(str(chg["price"]))
            s = Decimal(str(chg["size"]))
        except InvalidOperation as error:
            raise ValueError("Invalid decimal update") from error
        if not p.is_finite() or not (Decimal(0) <= p <= Decimal(1)):
            raise ValueError(f"Invalid price: {p}")
        if not s.is_finite() or s < 0:
            raise ValueError(f"Invalid size: {s}")
        level_map[p] = s
    result = []
    for p, s in level_map.items():
        if s > 0:
            result.append({"price": str(p), "size": str(s)})
    result.sort(key=lambda x: Decimal(x["price"]))
    return result
