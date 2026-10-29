"""EXP-0016 pure, fail-closed decision evidence; never submits or invents fills."""

import json
import re
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from premetar.research.limit99 import clock, fresh_book, number
from premetar.research.trader_monitor import open_market, verified_fee

ZONE = ZoneInfo("Europe/Warsaw")
STRATEGIES = ("D1_FORECAST_VALUE_V1", "D1_TO_D0_REPRICING_V1", "D1_HOLD_TO_SETTLEMENT_V1")
CONFIG_PATH = Path(__file__).resolve().parents[3] / "configs/experiments/epwa-d1-v1.json"


def default_config() -> dict[str, Any]:
    return dict(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))


def local_day_bounds(day: date) -> tuple[datetime, datetime]:
    """Calendar boundaries, not a fixed 24h delta (Warsaw DST days differ)."""
    return (
        datetime.combine(day, time.min, ZONE).astimezone(UTC),
        datetime.combine(day + timedelta(days=1), time.min, ZONE).astimezone(UTC),
    )


def parse_outcome(label: str) -> dict[str, Any] | None:
    """Only explicit Celsius labels; tails must never be silently made exact."""
    text = label.strip().replace("−", "-")
    match = re.fullmatch(
        r"(-?\d+)\s*°?\s*C(?:\s+(or below|or higher|or above|or lower))?", text, re.I
    )
    if not match:
        return None
    suffix = (match[2] or "").lower()
    return {
        "kind": "AT_MOST"
        if suffix in {"or below", "or lower"}
        else "AT_LEAST"
        if suffix
        else "EXACT",
        "temperature_c": int(match[1]),
        "label": label,
    }


def outcome_wins(outcome: dict[str, Any], settled_integer: int) -> bool:
    kind, value = outcome["kind"], number(outcome["temperature_c"])
    if kind == "EXACT":
        return settled_integer == value
    if kind == "AT_MOST":
        return settled_integer <= value
    if kind == "AT_LEAST":
        return settled_integer >= value
    if kind == "BELOW":
        return settled_integer < value
    if kind == "ABOVE":
        return settled_integer > value
    raise ValueError("Unknown outcome semantics")


def _quote(
    book: dict[str, Any], budget: Decimal, tick: Decimal, minimum: Decimal
) -> dict[str, Any]:
    remaining, quantity, cost = budget, Decimal(0), Decimal(0)
    for level in sorted(book["asks"], key=lambda row: number(row["price"])):
        price, size = number(level["price"]), number(level["size"])
        if price % tick:
            return {"status": "INVALID_TICK", "quantity": "0", "gross_cost_usd": "0"}
        take = min(size, remaining / price).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
        quantity += take
        cost += take * price
        remaining -= take * price
        if remaining < Decimal("0.000001"):
            break
    return {
        "status": "DEPTH_SUPPORTED_CONDITIONAL"
        if quantity >= minimum
        else "INSUFFICIENT_LIQUIDITY_OR_MIN_SIZE",
        "quantity": str(quantity),
        "gross_cost_usd": str(cost),
        "fees_usd": "0",
        "average_buy_price": str(cost / quantity) if quantity else None,
        "budget_used_fraction": float(cost / budget) if budget else 0,
        "execution_path": "DIRECT_BOOK_SUPPORTED",
        "is_fill": False,
        "semantics": "DECISION_DEPTH_ONLY_NOT_ARRIVAL_OR_OWN_EXECUTION",
    }


def _probability(
    probability: dict[str, Any], at: datetime, day: date, condition: str, config: dict[str, Any]
) -> tuple[Decimal | None, str | None]:
    try:
        # Promotion is a separate audited decision, never a runtime inference
        # from a caller's CALIBRATED flag or a favorable training statistic.
        promotion = config.get("calibration_promotion_id")
        if not promotion or probability.get("promotion_id") != promotion:
            return None, "PROBABILITY_UNVALIDATED"
        audit = probability.get("audit", {})
        if not (
            audit.get("verified_settlement_targets") is True
            and audit.get("original_horizon_forecasts") is True
            and audit.get("chronological_out_of_sample_validation") is True
            and re.fullmatch(r"[0-9a-f]{64}", str(audit.get("artifact_sha256", "")))
            and audit.get("forecast_record_ids")
            and audit.get("settlement_record_ids")
            and audit.get("validation_record_ids")
            and clock(audit["verified_at"]) <= at
        ):
            return None, "CALIBRATION_AUDIT_MISSING"
        yes = number(probability["yes_probability"])
        if not 0 <= yes <= 1:
            return None, "INVALID_PROBABILITY"
        if (
            probability.get("status") != "CALIBRATED"
            or probability.get("validated_out_of_sample") is not True
            or int(probability["sample_size"]) < 30
        ):
            return None, "PROBABILITY_UNVALIDATED"
        if probability.get("condition_id") != condition:
            return None, "PROBABILITY_OUTCOME_IDENTITY_MISMATCH"
        if not 0 <= (at - clock(probability["available_at"])).total_seconds() <= 3600:
            return None, "PROBABILITY_UNAVAILABLE_OR_STALE"
        if (
            date.fromisoformat(probability["training_last_settlement_date"])
            >= min(day, at.astimezone(ZONE).date())
            or clock(probability["training_last_outcome_received_at"]) > at
        ):
            return None, "CALIBRATION_LOOKAHEAD"
        if probability.get("horizon_bucket") != horizon_bucket(at, day):
            return None, "CALIBRATION_HORIZON_MISMATCH"
        return yes, None
    except (ValueError, TypeError, KeyError, ArithmeticError):
        return None, "PROBABILITY_UNVALIDATED"


def horizon_bucket(at: datetime, settlement_day: date) -> str:
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("Timezone required")
    local = at.astimezone(ZONE)
    days = (settlement_day - local.date()).days
    if days == 1:
        return (
            "D1_MORNING" if local.hour < 12 else "D1_AFTERNOON" if local.hour < 18 else "D1_EVENING"
        )
    if days == 0:
        return "D0_MORNING" if local.hour < 12 else "D0_INTRADAY"
    return "OUTSIDE_PRIMARY_HORIZON"


def evaluate_candidate(
    market: dict[str, Any],
    books: dict[str, dict[str, Any]],
    probability: dict[str, Any],
    at: datetime,
    *,
    config: dict[str, Any] | None = None,
    portfolio: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist this evidence even when no probability, depth, identity or signal exists.

    No order state is mutated. An ENTRY_SIGNAL still needs a distinct prospective
    arrival book before any simulated fill; maker/complementary fills stay unknown.
    """
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("Timezone required")
    at = at.astimezone(UTC)
    cfg, account = config or default_config(), portfolio or {}
    identity, metadata = market.get("identity", market), market.get("metadata", market)
    condition = str(identity.get("condition_id", ""))
    result: dict[str, Any] = {
        "study": "EXP0016",
        "rule_version": cfg["version"],
        "created_at": at.isoformat(),
        "condition_id": condition,
        "status": "RESEARCH_CANDIDATE",
        "reasons": [],
        "sides": {},
        "strategy_versions": list(STRATEGIES),
        "maker_status": "UNKNOWN_QUEUE_NO_FILL_ASSUMED",
        "complementary_path": "THEORETICAL_ONLY_NOT_EXECUTED_OR_DOUBLE_COUNTED",
        "is_order": False,
    }
    reasons: list[str] = result["reasons"]
    try:
        day = date.fromisoformat(str(identity.get("settlement_date", identity.get("day", ""))))
    except ValueError:
        result.update(status="BLOCKED", reasons=["INVALID_SETTLEMENT_DATE"])
        return result
    result.update(settlement_date=day.isoformat(), horizon_bucket=horizon_bucket(at, day))
    if day != at.astimezone(ZONE).date() + timedelta(days=1):
        reasons.append("OUTSIDE_D_MINUS_1_ENTRY_DAY")
    rules = market.get("rules", {})
    if not (
        rules.get("verified") is True
        and rules.get("reference_station") == "EPWA"
        and rules.get("timezone") == "Europe/Warsaw"
        and all(rules.get(k) for k in ("settlement_source", "daily_maximum_definition", "rounding"))
    ):
        reasons.append("SETTLEMENT_RULES_UNVERIFIED")
    if identity.get("airport", "EPWA") != "EPWA" or not condition:
        reasons.append("MARKET_IDENTITY_UNVERIFIED")
    outcome = identity.get("outcome") or parse_outcome(str(identity.get("outcome_label", "")))
    if not outcome or outcome.get("kind") not in {"EXACT", "AT_MOST", "AT_LEAST", "ABOVE", "BELOW"}:
        reasons.append("OUTCOME_SEMANTICS_UNVERIFIED")
    result["outcome"] = outcome
    try:
        if (
            not 0
            <= (at - clock(market["received_at"])).total_seconds()
            <= cfg["metadata_max_age_seconds"]
        ):
            reasons.append("METADATA_UNAVAILABLE_OR_STALE")
    except (KeyError, ValueError, TypeError):
        reasons.append("METADATA_UNAVAILABLE_OR_STALE")
    if open_market(metadata) is not True:
        reasons.append("MARKET_NOT_VERIFIED_OPEN")
    try:
        fee = verified_fee(metadata)
    except (ValueError, TypeError, ArithmeticError):
        fee = None
    if fee is None:
        reasons.append("UNKNOWN_OR_UNSUPPORTED_FEES")
    yes, probability_reason = _probability(probability, at, day, condition, cfg)
    if probability_reason:
        reasons.append(probability_reason)
    result["probability_status"] = "CALIBRATED" if yes is not None else "PROBABILITY_UNVALIDATED"
    budget = number(cfg["order_budget_usd"])
    try:
        cash = number(account.get("cash", cfg["initial_capital_usd"])) - number(
            account.get("reserved", 0)
        )
        if cash < budget:
            reasons.append("INSUFFICIENT_CASH")
        if int(account.get("open_or_pending_positions", 0)) >= cfg["max_open_positions"]:
            reasons.append("MAX_OPEN_POSITIONS")
        if number(account.get("day_committed_usd", 0)) + budget > number(
            cfg["max_day_committed_usd"]
        ):
            reasons.append("MAX_DAY_EXPOSURE")
        tick, minimum = number(metadata["orderPriceMinTickSize"]), number(metadata["orderMinSize"])
        if tick <= 0 or minimum <= 0:
            raise ValueError("Invalid constraints")
    except (ValueError, TypeError, KeyError, ArithmeticError):
        result.update(
            status="BLOCKED", reasons=reasons + ["INVALID_MARKET_OR_PORTFOLIO_CONSTRAINTS"]
        )
        return result
    for side in ("YES", "NO"):
        tokens = identity.get("tokens", {})
        token = tokens.get(side, identity.get(side.lower()))
        book = books.get(side, books.get(str(token), {}))
        evidence: dict[str, Any] = {
            "token_id": token,
            "reasons": list(reasons),
            "status": "BLOCKED",
            "estimated_probability": float(yes if side == "YES" else 1 - yes)
            if yes is not None
            else None,
            "expected_return_usd": None,
        }
        result["sides"][side] = evidence
        if not token or not fresh_book(book, at, str(token), condition):
            evidence["reasons"].append("NO_FRESH_DIRECT_BOOK")
            continue
        quote = _quote(book, budget, tick, minimum)
        evidence.update(
            quote=quote,
            book_received_at=book["received_at"],
            best_bid=max((float(number(x["price"])) for x in book["bids"]), default=None),
            best_ask=min((float(number(x["price"])) for x in book["asks"]), default=None),
        )
        if quote["status"] != "DEPTH_SUPPORTED_CONDITIONAL" or quote[
            "budget_used_fraction"
        ] < float(cfg["minimum_budget_fill_fraction"]):
            evidence["reasons"].append("INSUFFICIENT_EXECUTABLE_DEPTH")
        if yes is not None and not reasons:
            chance = yes if side == "YES" else 1 - yes
            cost, qty = number(quote["gross_cost_usd"]), number(quote["quantity"])
            ev = chance * qty - cost
            edge = chance - cost / qty if qty else Decimal(0)
            evidence.update(
                expected_return_usd=str(ev),
                probability_edge=str(edge),
                expected_net_return_fraction=str(ev / cost) if cost else None,
            )
            if edge < number(cfg["minimum_probability_edge"]):
                evidence["reasons"].append("INSUFFICIENT_PROBABILITY_EDGE")
            if not cost or ev / cost < number(cfg["minimum_executable_net_return_fraction"]):
                evidence["reasons"].append("INSUFFICIENT_EXPECTED_RETURN")
        evidence["status"] = (
            "ENTRY_SIGNAL"
            if not evidence["reasons"]
            else "RESEARCH_CANDIDATE"
            if evidence["reasons"] == ["PROBABILITY_UNVALIDATED"]
            else "BLOCKED"
        )
    if any(row["status"] == "ENTRY_SIGNAL" for row in result["sides"].values()):
        result["status"] = "ENTRY_SIGNAL"
    elif reasons and reasons != ["PROBABILITY_UNVALIDATED"]:
        result["status"] = "BLOCKED"
    return result


def exit_policy(
    strategy: str,
    settlement_day: date,
    at: datetime,
    *,
    net_return_fraction: Decimal | None = None,
    signal_valid: bool = True,
) -> dict[str, Any]:
    """A trigger is not an exit fill. All prices require fresh arrival-side bids."""
    if strategy not in STRATEGIES or at.tzinfo is None:
        raise ValueError("Unknown strategy or naive time")
    local = at.astimezone(ZONE)
    noon = datetime.combine(settlement_day, time(12), ZONE)
    _, end = local_day_bounds(settlement_day)
    if not signal_valid and local.date() < settlement_day:
        action = "CANCEL_UNFILLED_ENTRY_WITH_LATENCY"
    elif strategy == "D1_HOLD_TO_SETTLEMENT_V1":
        action = "HOLD_UNTIL_VERIFIED_OFFICIAL_RESOLUTION"
    elif strategy == "D1_FORECAST_VALUE_V1":
        action = "ATTEMPT_DIRECT_BID_EXIT" if local >= noon else "WAIT_D0_NOON"
    else:
        action = (
            "ATTEMPT_DIRECT_BID_EXIT"
            if (
                local.date() == settlement_day
                and net_return_fraction is not None
                and net_return_fraction >= Decimal("0.05")
            )
            or at.astimezone(UTC) >= end
            else "WAIT_FROZEN_NET_RETURN_TARGET"
        )
    return {
        "strategy": strategy,
        "action": action,
        "is_fill": False,
        "requires_fresh_arrival_depth": True,
        "unfilled_exit_policy": "RETAIN_INVENTORY_AND_RISK_UNTIL_VERIFIED_SETTLEMENT",
    }
