"""Pure, cash-conserving shadow lifecycle. No network or authenticated execution.

All fills are conditional simulations, never exchange-observed own executions.
Pessimistic maker cannot be filled using anonymous public depth alone.
"""

import hashlib
import json
import re
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from premetar.research.trader_monitor import open_market, verified_fee

ZONE = ZoneInfo("Europe/Warsaw")
D = Decimal
ZERO = D(0)
TERMINAL = {"FILLED", "CANCELLED", "EXPIRED", "REJECTED", "SETTLED", "UNKNOWN"}


def clock(value: str) -> datetime:
    at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("Timezone required")
    return at.astimezone(UTC)


def number(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("Boolean is not a price")
    result = D(str(value))
    if not result.is_finite():
        raise ValueError("Non-finite number")
    return result


def eligible(price: Decimal, boundary: bool = False) -> bool:
    return price == D(".98") if boundary else D(".91") < price < D(".98")


def fresh_book(book: dict[str, Any], at: datetime, token: str, condition: str) -> bool:
    try:
        if book.get("status") != "VALID" or book.get("token_id") != token:
            return False
        if book.get("market") != condition or not book.get("connection_id"):
            return False
        if not 0 <= (at - clock(book["received_at"])).total_seconds() <= 5:
            return False
        sides = []
        for name in ("bids", "asks"):
            values = [(number(r["price"]), number(r["size"])) for r in book[name]]
            if any(not ZERO < p < 1 or q <= ZERO for p, q in values):
                return False
            if len({p for p, _ in values}) != len(values):
                return False
            sides.append(values)
        return not (
            sides[0] and sides[1] and max(p for p, _ in sides[0]) >= min(p for p, _ in sides[1])
        )
    except (ValueError, KeyError, TypeError, ArithmeticError):
        return False


def take_depth(
    levels: list[dict[str, Any]], quantity: Decimal, limit: Decimal, buy: bool
) -> tuple[Decimal, Decimal]:
    """Quantity and gross, bounded by a marketable limit; no invented liquidity."""
    filled = gross = ZERO
    for row in sorted(levels, key=lambda r: number(r["price"]), reverse=not buy):
        price, size = number(row["price"]), number(row["size"])
        if (buy and price > limit) or (not buy and price < limit):
            break
        amount = min(size, quantity - filled)
        filled += amount
        gross += amount * price
        if filled == quantity:
            break
    return filled, gross


class Limit99:
    def __init__(self, config: dict[str, Any], state: dict[str, Any] | None = None) -> None:
        self.config = config
        if config.get("max_attempts_per_contract_day_variant") != 1:
            raise ValueError("v1 supports exactly one attempt per contract/day")
        self.hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        self.state = state or {"config_hash": self.hash, "portfolios": {}, "serial": 0}
        if self.state["config_hash"] != self.hash:
            raise ValueError("Frozen config mismatch; never reset an existing portfolio")
        self.events: list[dict[str, Any]] = []
        if not self.state["portfolios"]:
            for family in ("SIMPLE", "HYBRID", "SIMPLE_98_CONTROL"):
                for latency in config["latencies_ms"]:
                    for mode, scenarios in (
                        ("TAKER", ["DEPTH_SUPPORTED"]),
                        ("MAKER", config["maker_scenarios"]),
                    ):
                        for scenario in scenarios:
                            key = f"{family}:{mode}:{scenario}:{latency}"
                            self.state["portfolios"][key] = dict(
                                family=family,
                                mode=mode,
                                scenario=scenario,
                                latency_ms=latency,
                                cash=config["initial_capital_usd"],
                                realized="0",
                                fees="0",
                                reserved="0",
                                orders=[],
                                positions={},
                                attempts=[],
                                day_committed={},
                                submitted_orders=0,
                                supported_buy_fills=0,
                                positions_opened=0,
                                exits_at_target=0,
                                exits_below_target=0,
                                weather_rejections=0,
                                capital_seconds="0",
                                last_mark=None,
                                maximum_equity=config["initial_capital_usd"],
                                maximum_drawdown="0",
                                marks={},
                            )

    def emit(self, kind: str, at: datetime, p: dict[str, Any], **payload: Any) -> None:
        self.state["serial"] += 1
        self.events.append(
            deepcopy(
                dict(
                    kind=kind,
                    at=at.isoformat(),
                    payload=dict(
                        family=p.get("family"),
                        mode=p.get("mode"),
                        scenario=p.get("scenario"),
                        latency_ms=p.get("latency_ms"),
                        version=self.config["version"],
                        config_hash=self.hash,
                        serial=self.state["serial"],
                        **payload,
                    ),
                )
            )
        )

    def drain(self) -> list[dict[str, Any]]:
        result, self.events = self.events, []
        return result

    def restart(self, at: datetime) -> None:
        """No restored quote or hypothetical queue becomes fresh after a restart."""
        for p in self.state["portfolios"].values():
            p["marks"] = {}
            for order in p["orders"]:
                if order["state"] not in TERMINAL:
                    order["queue_valid"] = False
                    order["execution_unknown"] = True
                    self.terminate(p, order, at, "UNKNOWN", "PROCESS_RESTART_WITH_OPEN_ORDER")
                    self.emit(
                        "QUEUE_EVIDENCE_LOST", at, p, order_id=order["id"], reason="PROCESS_RESTART"
                    )

    def submit(
        self,
        p: dict[str, Any],
        at: datetime,
        market: dict[str, Any],
        book: dict[str, Any],
        weather: dict[str, Any],
    ) -> None:
        identity, metadata = market["identity"], market["metadata"]
        condition, day = identity["condition_id"], identity["day"]
        attempt = f"{condition}:{day}"
        if attempt in p["attempts"]:
            return
        try:
            tick = number(metadata["orderPriceMinTickSize"])
            minimum = number(metadata["orderMinSize"])
            if tick <= 0 or minimum <= 0 or D(".99") % tick:
                return
            levels = book["bids"] if p["mode"] == "MAKER" else book["asks"]
            if not levels:
                return
            price = (max if p["mode"] == "MAKER" else min)(number(r["price"]) for r in levels)
            if not eligible(price, p["family"] == "SIMPLE_98_CONTROL") or price % tick:
                return
            p["attempts"].append(attempt)
            # SIMPLE and boundary-control eligibility never read meteorological fields.
            gate = False
            if p["family"] == "HYBRID":
                adaptive = weather.get("adaptive_tmax")
                if isinstance(adaptive, dict):
                    adaptive = adaptive.get("temperature_c", adaptive.get("value"))
                label = str(identity.get("outcome_label", ""))
                match = re.fullmatch(r"(-?\d+)°?C", label.strip())
                gate = bool(
                    weather.get("weather_gate")
                    and weather.get("created_at")
                    and 0 <= (at - clock(weather["created_at"])).total_seconds() <= 90
                    and adaptive is not None
                    and match
                    and int(match[1]) >= float(adaptive) + 1
                )
                if not gate:
                    p["weather_rejections"] += 1
                    self.emit(
                        "WEATHER_REJECT",
                        at,
                        p,
                        condition_id=condition,
                        reason="FROZEN_HYBRID_GATE_NOT_MET",
                        weather=weather,
                        decision_book=book,
                    )
                    return
            budget = min(
                number(self.config["order_budget_usd"]), number(p["cash"]) - number(p["reserved"])
            )
            quantity = (budget / price).quantize(D(".000001"), rounding=ROUND_DOWN)
            exposure = sum(number(pos["cost"]) for pos in p["positions"].values())
            reason = None
            if verified_fee(metadata) is None:
                reason = "UNKNOWN_OR_UNSUPPORTED_FEES"
            elif quantity < minimum:
                reason = "MIN_ORDER_SIZE_OR_CASH"
            elif (
                len(
                    {c for c, pos in p["positions"].items() if number(pos["quantity"]) > 0}
                    | {
                        o["condition_id"]
                        for o in p["orders"]
                        if o["side"] == "BUY"
                        and (o["state"] not in TERMINAL or o.get("execution_unknown"))
                    }
                )
                >= self.config["max_open_positions"]
            ):
                reason = "MAX_OPEN_POSITIONS"
            elif number(p["day_committed"].get(day, "0")) + number(
                p["reserved"]
            ) + quantity * price > number(self.config["max_day_committed_usd"]):
                reason = "MAX_DAY_COMMITTED"
            if reason:
                self.emit(
                    "ORDER_REJECTED",
                    at,
                    p,
                    condition_id=condition,
                    reason=reason,
                    entry_limit=str(price),
                    quantity=str(quantity),
                    decision_book=book,
                )
                return
            fee = verified_fee(metadata)
            assert fee is not None
            order = dict(
                id=f"{self.hash[:8]}-{self.state['serial'] + 1}",
                side="BUY",
                condition_id=condition,
                token_id=identity["no"],
                day=day,
                limit=str(price),
                quantity=str(quantity),
                filled="0",
                state="PENDING_SUBMISSION",
                created_at=at.isoformat(),
                due_at=(at + timedelta(milliseconds=p["latency_ms"])).isoformat(),
                expires_at=(
                    at + timedelta(seconds=self.config["entry_lifetime_seconds"])
                ).isoformat(),
                queue_ahead="0",
                queue_valid=True,
                mode=p["mode"],
                fee_evidence=fee.evidence,
                connection_id=book["connection_id"],
            )
            p["orders"].append(order)
            p["submitted_orders"] += 1
            p["reserved"] = str(number(p["reserved"]) + quantity * price)
            self.emit(
                "BUY_SUBMITTED",
                at,
                p,
                order=order.copy(),
                condition_id=condition,
                decision_book=book,
                market_identity=identity,
                market_metadata=metadata,
                market_metadata_received_at=market["received_at"],
                verified_tick_size=str(tick),
                verified_minimum_size=str(minimum),
                weather=weather if p["family"] == "HYBRID" else None,
                exposure_usd=str(exposure),
                complementary_path="THEORETICAL_ONLY",
                direct_path="DIRECT_BOOK_SUPPORTED",
                uncertainty="CONDITIONAL_SIMULATION_NOT_REAL_ORDER",
            )
        except (ValueError, TypeError, KeyError, ArithmeticError) as error:
            self.emit(
                "ORDER_REJECTED",
                at,
                p,
                condition_id=condition,
                reason="INVALID_CANDIDATE_METADATA",
                error_class=type(error).__name__,
            )

    def accrue(self, p: dict[str, Any], at: datetime) -> None:
        cost = sum((number(pos["cost"]) for pos in p["positions"].values()), ZERO)
        if p["last_mark"]:
            elapsed = max(0.0, (at - clock(p["last_mark"])).total_seconds())
            p["capital_seconds"] = str(number(p["capital_seconds"]) + cost * D(str(elapsed)))
        p["last_mark"] = at.isoformat()

    def terminate(
        self, p: dict[str, Any], o: dict[str, Any], at: datetime, state: str, reason: str
    ) -> None:
        o["terminal_reason"] = reason
        if reason.startswith("ARRIVAL_BOOK"):
            state = "UNKNOWN"
            o["execution_unknown"] = True
        if o["side"] == "BUY" and state != "UNKNOWN":
            p["reserved"] = str(
                max(
                    ZERO,
                    number(p["reserved"])
                    - (number(o["quantity"]) - number(o["filled"])) * number(o["limit"]),
                )
            )
        o["state"] = state
        self.emit(
            "ORDER_" + state, at, p, order=o.copy(), condition_id=o["condition_id"], reason=reason
        )

    def fill(
        self,
        p: dict[str, Any],
        o: dict[str, Any],
        quantity: Decimal,
        gross: Decimal,
        at: datetime,
        evidence: dict[str, Any],
        role: str,
    ) -> None:
        if quantity <= 0:
            return
        self.accrue(p, at)
        condition = o["condition_id"]
        if o["side"] == "BUY":
            pos = p["positions"].setdefault(
                condition, dict(quantity="0", cost="0", day=o["day"], token_id=o["token_id"])
            )
            if number(pos["quantity"]) == 0:
                p["positions_opened"] += 1
            pos["quantity"] = str(number(pos["quantity"]) + quantity)
            pos["cost"] = str(number(pos["cost"]) + gross)
            pos.setdefault("opened_at", at.isoformat())
            pos.setdefault("realized", "0")
            p["cash"] = str(number(p["cash"]) - gross)
            p["reserved"] = str(max(ZERO, number(p["reserved"]) - quantity * number(o["limit"])))
            p["day_committed"][o["day"]] = str(
                number(p["day_committed"].get(o["day"], "0")) + gross
            )
            p["supported_buy_fills"] += 1
            sell = dict(
                o,
                id=o["id"] + f"-exit-{o['filled']}",
                side="SELL",
                limit=".99",
                quantity=str(quantity),
                filled="0",
                state="PENDING_SUBMISSION",
                created_at=at.isoformat(),
                due_at=(at + timedelta(milliseconds=p["latency_ms"])).isoformat(),
                expires_at=None,
                mode="LIMIT_EXIT",
                queue_ahead="0",
                queue_valid=True,
            )
            p["orders"].append(sell)
            self.emit("SELL_99_SUBMITTED", at, p, order=sell.copy(), condition_id=condition)
        else:
            pos = p["positions"][condition]
            if quantity > number(pos["quantity"]):
                raise ValueError("Cannot sell unowned paper inventory")
            cost = number(pos["cost"]) * quantity / number(pos["quantity"])
            pos["quantity"] = str(number(pos["quantity"]) - quantity)
            pos["cost"] = str(number(pos["cost"]) - cost)
            p["cash"] = str(number(p["cash"]) + gross)
            p["realized"] = str(number(p["realized"]) + gross - cost)
            pos["realized"] = str(number(pos.get("realized", "0")) + gross - cost)
            if number(pos["quantity"]) == 0:
                p["exits_at_target"] += 1
                pos["last_exit_at"] = at.isoformat()
        o["filled"] = str(number(o["filled"]) + quantity)
        o["state"] = (
            "FILLED" if number(o["filled"]) == number(o["quantity"]) else "PARTIALLY_FILLED"
        )
        self.emit(
            "BUY_FILL" if o["side"] == "BUY" else "SELL_FILL",
            at,
            p,
            order=o.copy(),
            condition_id=condition,
            quantity=str(quantity),
            gross=str(gross),
            fee="0",
            fee_evidence=o["fee_evidence"],
            role=role,
            evidence=evidence,
            uncertainty="CONDITIONAL_DEPTH" if role == "TAKER" else p["scenario"],
        )

    def advance(
        self,
        p: dict[str, Any],
        at: datetime,
        market: dict[str, Any],
        book: dict[str, Any] | None,
        trade: dict[str, Any] | None,
    ) -> None:
        condition = market["identity"]["condition_id"]
        book = deepcopy(book) if book else None
        try:
            trade_volume = number(trade.get("size", "0")) if trade else ZERO
        except (ValueError, ArithmeticError):
            trade_volume = ZERO
        for o in list(p["orders"]):
            if o["condition_id"] != condition or o["state"] in TERMINAL:
                continue
            # No cancellation is effective before its declared arrival.
            if o.get("cancel_at") and at >= clock(o["cancel_at"]):
                self.terminate(
                    p, o, at, "EXPIRED" if o["side"] == "BUY" else "CANCELLED", "CANCEL_ARRIVED"
                )
                continue
            closed = (
                open_market(market["metadata"]) is False
                or o["day"] != at.astimezone(ZONE).date().isoformat()
            )
            if (closed or o.get("expires_at") and at >= clock(o["expires_at"])) and not o.get(
                "cancel_at"
            ):
                o["cancel_at"] = (
                    at + timedelta(milliseconds=self.config["cancellation_latency_ms"])
                ).isoformat()
                o["state"] = "CANCEL_PENDING"
                self.emit("CANCEL_REQUEST", at, p, order=o.copy(), condition_id=condition)
            if closed:
                continue
            remaining = number(o["quantity"]) - number(o["filled"])
            if o.get("rested_at"):
                if trade and p["scenario"] != "PESSIMISTIC" and o["queue_valid"]:
                    try:
                        if not book or not fresh_book(book, at, o["token_id"], condition):
                            continue
                        if (
                            verified_fee(market["metadata"]) is None
                            or not 0
                            <= (at - clock(market["received_at"])).total_seconds()
                            <= self.config["metadata_max_age_seconds"]
                        ):
                            continue
                        if (
                            trade.get("token_id") != o["token_id"]
                            or trade.get("market") != condition
                            or trade.get("connection_id") != o["connection_id"]
                        ):
                            continue
                        if clock(trade["received_at"]) <= clock(o["rested_at"]):
                            continue
                        source_time = datetime.fromtimestamp(
                            float(trade["source_timestamp"]) / 1000, UTC
                        )
                        if source_time - timedelta(milliseconds=1) <= clock(
                            o["rested_at"]
                        ) or source_time > clock(trade["received_at"]):
                            continue
                        side = "SELL" if o["side"] == "BUY" else "BUY"
                        if trade.get("side") != side or number(trade["price"]) != number(
                            o["limit"]
                        ):
                            continue
                        volume = trade_volume
                        if volume <= 0:
                            continue
                        queue = (
                            number(o["queue_ahead"])
                            if p["scenario"] in {"EVIDENCE_SUPPORTED", "DEPTH_SUPPORTED"}
                            else ZERO
                        )
                        spent = min(queue, volume)
                        o["queue_ahead"] = str(queue - spent)
                        quantity = min(remaining, volume - spent)
                        self.fill(
                            p,
                            o,
                            quantity,
                            quantity * number(o["limit"]),
                            at,
                            trade,
                            "MAKER_CONDITIONAL",
                        )
                        trade_volume -= spent + quantity
                    except (ValueError, TypeError, KeyError, ArithmeticError):
                        continue
                continue
            if at < clock(o["due_at"]):
                continue
            if (
                not book
                or not fresh_book(book, at, o["token_id"], condition)
                or clock(book["received_at"]) < clock(o["due_at"])
            ):
                if at > clock(o["due_at"]) + timedelta(
                    seconds=self.config["maximum_arrival_gap_seconds"]
                ):
                    self.terminate(p, o, at, "REJECTED", "ARRIVAL_BOOK_UNRESOLVED")
                continue
            if (clock(book["received_at"]) - clock(o["due_at"])).total_seconds() > self.config[
                "maximum_arrival_gap_seconds"
            ]:
                self.terminate(p, o, at, "REJECTED", "ARRIVAL_BOOK_TOO_LATE")
                continue
            if (
                verified_fee(market["metadata"]) is None
                or not 0
                <= (at - clock(market["received_at"])).total_seconds()
                <= self.config["metadata_max_age_seconds"]
            ):
                self.terminate(p, o, at, "REJECTED", "CURRENT_FEE_UNVERIFIED")
                continue
            if o["side"] == "BUY" and o["mode"] == "MAKER":
                if any(number(row["price"]) <= number(o["limit"]) for row in book["asks"]):
                    self.terminate(p, o, at, "REJECTED", "POST_ONLY_WOULD_CROSS")
                    continue
            else:
                levels = book["asks"] if o["side"] == "BUY" else book["bids"]
                quantity, gross = take_depth(
                    levels, remaining, number(o["limit"]), o["side"] == "BUY"
                )
                self.fill(p, o, quantity, gross, at, book, "TAKER")
                consume = quantity
                for row in sorted(
                    levels, key=lambda r: number(r["price"]), reverse=o["side"] == "SELL"
                ):
                    amount = min(number(row["size"]), consume)
                    row["size"] = str(number(row["size"]) - amount)
                    consume -= amount
                    if consume <= 0:
                        break
                levels[:] = [row for row in levels if number(row["size"]) > 0]
                if o["state"] == "FILLED":
                    continue
                if o["side"] == "BUY":
                    self.terminate(p, o, at, "CANCELLED", "MARKETABLE_ENTRY_IOC_REMAINDER")
                    continue
            o["rested_at"] = at.isoformat()
            o["connection_id"] = book["connection_id"]
            o["queue_ahead"] = str(
                sum(
                    (
                        number(row["size"])
                        for row in book["bids" if o["side"] == "BUY" else "asks"]
                        if number(row["price"]) == number(o["limit"])
                    ),
                    ZERO,
                )
            )
            o["state"] = "RESTING" if number(o["filled"]) == 0 else "PARTIALLY_FILLED"
            self.emit(
                "ORDER_RESTING", at, p, order=o.copy(), condition_id=condition, arrival_book=book
            )

    def observe(
        self,
        at: datetime,
        market: dict[str, Any],
        book: dict[str, Any] | None,
        weather: dict[str, Any],
        trade: dict[str, Any] | None = None,
    ) -> None:
        identity, metadata = market["identity"], market["metadata"]
        if trade:
            fingerprint = hashlib.sha256(
                json.dumps(
                    [
                        trade.get(k)
                        for k in ("token_id", "market", "source_timestamp", "price", "size", "side")
                    ]
                ).encode()
            ).hexdigest()
            seen = self.state.setdefault("seen_trades", {})
            today = at.astimezone(ZONE).date().isoformat()
            seen = {key: value for key, value in seen.items() if value == today}
            self.state["seen_trades"] = seen
            if fingerprint in seen or len(seen) >= 100000:
                trade = None
            else:
                seen[fingerprint] = today
        for p in self.state["portfolios"].values():
            self.advance(p, at, market, book, trade)
            condition = identity["condition_id"]
            if (
                condition in p["positions"]
                and number(p["positions"][condition]["quantity"]) > 0
                and book
                and fresh_book(book, at, identity["no"], condition)
            ):
                p["marks"][condition] = dict(
                    book=book,
                    at=at.isoformat(),
                    fee_known=verified_fee(metadata) is not None,
                    fee_received=market.get("received_at"),
                )
            try:
                ready = (
                    identity.get("airport") == "EPWA"
                    and identity.get("station_match") is True
                    and identity.get("day") == at.astimezone(ZONE).date().isoformat()
                    and 0
                    <= (at - clock(market["received_at"])).total_seconds()
                    <= self.config["metadata_max_age_seconds"]
                    and open_market(metadata) is True
                )
                if ready and book and fresh_book(book, at, identity["no"], condition):
                    self.submit(p, at, market, book, weather)
            except (ValueError, KeyError, TypeError):
                continue

    def invalidate(self, at: datetime, connection: str | None, token: str | None = None) -> None:
        for p in self.state["portfolios"].values():
            p["marks"] = {
                condition: mark
                for condition, mark in p["marks"].items()
                if (token is not None and mark["book"].get("token_id") != token)
                or (token is None and mark["book"].get("connection_id") == connection)
            }
            for o in p["orders"]:
                if (
                    (token is None or o["token_id"] == token)
                    and o["state"] not in TERMINAL
                    and o.get("rested_at")
                    and o.get("connection_id") != connection
                ):
                    o["queue_valid"] = False

    def settle(self, at: datetime, market: dict[str, Any]) -> None:
        """Only captured final resolution metadata, never our METAR daily proxy."""
        metadata, identity = market["metadata"], market["identity"]
        if (
            clock(market["received_at"]) > at
            or identity.get("airport") != "EPWA"
            or identity.get("station_match") is not True
        ):
            return
        if metadata.get("umaResolutionStatus") != "resolved" or metadata.get("closed") is not True:
            return
        prices = metadata.get("outcomePrices")
        outcomes = metadata.get("outcomes")
        try:
            prices = json.loads(prices) if isinstance(prices, str) else prices
            outcomes = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
            if len(prices) != 2 or set(number(v) for v in prices) != {ZERO, D(1)}:
                return
            no_index = [str(v).lower() for v in outcomes].index("no")
            payout = number(prices[no_index])
        except (ValueError, TypeError, ArithmeticError):
            return
        for p in self.state["portfolios"].values():
            condition = identity["condition_id"]
            pos = p["positions"].get(condition)
            for o in p["orders"]:
                if o["condition_id"] == condition and o["state"] not in TERMINAL:
                    self.terminate(p, o, at, "SETTLED", "VERIFIED_RESOLUTION")
            if not pos or pos.get("settled") or number(pos["quantity"]) <= 0:
                continue
            value = number(pos["quantity"]) * payout
            self.accrue(p, at)
            p["cash"] = str(number(p["cash"]) + value)
            p["realized"] = str(number(p["realized"]) + value - number(pos["cost"]))
            pos["realized"] = str(number(pos.get("realized", "0")) + value - number(pos["cost"]))
            self.emit(
                "SETTLEMENT",
                at,
                p,
                condition_id=condition,
                payout=str(payout),
                quantity=pos["quantity"],
                net_pnl=str(value - number(pos["cost"])),
                metadata=metadata,
            )
            pos.update(quantity="0", cost="0", settled=True)

    def metrics(self, at: datetime) -> list[dict[str, Any]]:
        result = []
        for p in self.state["portfolios"].values():
            positions = [pos for pos in p["positions"].values() if number(pos["quantity"]) > 0]
            cost = sum((number(pos["cost"]) for pos in positions), ZERO)
            liquidation = ZERO
            unknown_orders = [o for o in p["orders"] if o.get("execution_unknown")]
            known = not unknown_orders
            for condition, pos in p["positions"].items():
                quantity = number(pos["quantity"])
                if quantity == 0:
                    continue
                mark = p["marks"].get(condition)
                if (
                    not mark
                    or not fresh_book(mark["book"], at, pos["token_id"], condition)
                    or not mark.get("fee_known")
                    or not 0
                    <= (at - clock(mark["fee_received"])).total_seconds()
                    <= self.config["metadata_max_age_seconds"]
                ):
                    known = False
                    continue
                sold, value = take_depth(mark["book"]["bids"], quantity, ZERO, False)
                if sold < quantity:
                    known = False
                liquidation += value
            cash = number(p["cash"])
            equity = cash + liquidation if known else None
            if equity is not None:
                p["maximum_equity"] = str(max(number(p["maximum_equity"]), equity))
                p["maximum_drawdown"] = str(
                    max(number(p["maximum_drawdown"]), number(p["maximum_equity"]) - equity)
                )
            self.accrue(p, at)
            filled_orders = sum(o["side"] == "BUY" and number(o["filled"]) > 0 for o in p["orders"])
            closed_positions = sum(
                number(pos["quantity"]) == 0
                and not pos.get("settled")
                and not any(
                    o["condition_id"] == condition
                    and o["side"] == "BUY"
                    and o["state"] not in TERMINAL
                    for o in p["orders"]
                )
                for condition, pos in p["positions"].items()
            )
            complete_positions = [
                pos
                for condition, pos in p["positions"].items()
                if number(pos["quantity"]) == 0
                and not any(
                    o["condition_id"] == condition
                    and o["side"] == "BUY"
                    and o["state"] not in TERMINAL
                    for o in p["orders"]
                )
            ]
            closed_pnls = [number(pos.get("realized", "0")) for pos in complete_positions]
            profits = [value for value in closed_pnls if value > 0]
            losses = [value for value in closed_pnls if value < 0]
            pending_buys = [
                o for o in p["orders"] if o["side"] == "BUY" and o["state"] not in TERMINAL
            ]
            completed = not positions and not pending_buys and not unknown_orders
            committed = sum((number(value) for value in p["day_committed"].values()), ZERO)
            exit_seconds = sorted(
                (clock(pos["last_exit_at"]) - clock(pos["opened_at"])).total_seconds()
                for pos in complete_positions
                if pos.get("last_exit_at") and pos.get("opened_at")
            )
            day_risks = {}
            for day in {pos["day"] for pos in positions}:
                daily = [pos for pos in positions if pos["day"] == day]
                daily_cost = sum((number(pos["cost"]) for pos in daily), ZERO)
                total_qty = sum((number(pos["quantity"]) for pos in daily), ZERO)
                day_risks[day] = {
                    "OTHER": float(daily_cost - total_qty),
                    **{
                        condition: float(daily_cost - total_qty + number(pos["quantity"]))
                        for condition, pos in p["positions"].items()
                        if pos["day"] == day and number(pos["quantity"]) > 0
                    },
                }
            for o in unknown_orders:
                if o["side"] != "BUY":
                    continue
                day, condition = o["day"], o["condition_id"]
                values = day_risks.setdefault(day, {"OTHER": 0.0})
                daily = [pos for pos in positions if pos["day"] == day]
                baseline = sum(
                    (number(pos["cost"]) - number(pos["quantity"]) for pos in daily), ZERO
                )
                held = p["positions"].get(condition)
                if held:
                    baseline += number(held["quantity"])
                values[condition] = values.get(condition, float(baseline)) + float(
                    (number(o["quantity"]) - number(o["filled"])) * number(o["limit"])
                )
            # Zero recovery is a stress bound, not a liquidation mark or realized loss.
            result.append(
                dict(
                    family=p["family"],
                    mode=p["mode"],
                    scenario=p["scenario"],
                    latency_ms=p["latency_ms"],
                    status="UNRESOLVED_EXECUTION" if unknown_orders else "PROSPECTIVE_SHADOW",
                    submitted_orders=p["submitted_orders"],
                    supported_buy_fills=filled_orders,
                    buy_fill_fragments=p["supported_buy_fills"],
                    positions_opened=len(p["positions"]),
                    exits_at_target=sum(
                        number(pos["quantity"]) == 0
                        and not pos.get("settled")
                        and not any(
                            o["condition_id"] == condition
                            and o["side"] == "BUY"
                            and o["state"] not in TERMINAL
                            for o in p["orders"]
                        )
                        for condition, pos in p["positions"].items()
                    ),
                    exits_below_target=p["exits_below_target"],
                    open_positions=len(positions),
                    realized_pnl=float(number(p["realized"])) if not unknown_orders else None,
                    known_conditional_realized_pnl=float(number(p["realized"])),
                    unresolved_orders=len(unknown_orders),
                    unresolved_possible_positions=len(
                        {o["condition_id"] for o in unknown_orders if o["side"] == "BUY"}
                    ),
                    unrealized_pnl=float(liquidation - cost) if known else None,
                    net_pnl=float(equity - number(self.config["initial_capital_usd"]))
                    if equity is not None
                    else None,
                    equity=float(equity) if equity is not None else None,
                    cash=float(cash),
                    reserved=float(number(p["reserved"])),
                    maximum_loss=float(cost + sum(
                        ((number(o["quantity"])-number(o["filled"]))*number(o["limit"])
                         for o in unknown_orders if o["side"] == "BUY"
                    )),
                    maximum_loss_semantics="CONSERVATIVE_COST_BOUND_NO_ASSUMED_DIVERSIFICATION",
                    conditional_loss_by_single_winning_condition=day_risks,
                    bucket_partition_status="DISJOINT_EXHAUSTIVE_PARTITION_NOT_CERTIFIED",
                    stress_zero_recovery_equity=float(cash - number(p["reserved"])),
                    drawdown=float(number(p["maximum_drawdown"])) if not unknown_orders else None,
                    fill_rate=filled_orders / p["submitted_orders"]
                    if p["submitted_orders"] and not unknown_orders
                    else None,
                    exit_success_rate=closed_positions / len(p["positions"])
                    if p["positions"]
                    else None,
                    capital_utilization=float(cost / number(self.config["initial_capital_usd"])),
                    exposure_usd=float(cost),
                    capital_time_usd_seconds=p["capital_seconds"] if not unknown_orders else None,
                    known_conditional_capital_time_usd_seconds=p["capital_seconds"],
                    total_committed_usd=float(committed),
                    pending_entry_debit_usd=float(number(p["reserved"])),
                    paper_orders_never_filled=sum(
                        o["side"] == "BUY"
                        and o["state"] in TERMINAL
                        and not o.get("execution_unknown")
                        and number(o["filled"]) == 0
                        for o in p["orders"]
                    ),
                    unfilled_buy_orders_pending=len(pending_buys),
                    average_closed_profit=float(sum(profits, ZERO) / len(profits))
                    if profits
                    else None,
                    average_closed_loss=float(sum(losses, ZERO) / len(losses)) if losses else None,
                    largest_closed_loss=float(min(losses)) if losses else None,
                    closed_only_win_rate=len(profits) / len(closed_pnls) if closed_pnls else None,
                    closed_only_profit_factor=float(sum(profits, ZERO) / -sum(losses, ZERO))
                    if losses
                    else None,
                    expectancy_per_filled_order=float(number(p["realized"]) / filled_orders)
                    if completed and filled_orders
                    else None,
                    expectancy_per_submitted_order=float(
                        number(p["realized"]) / p["submitted_orders"]
                    )
                    if completed and p["submitted_orders"]
                    else None,
                    return_on_committed_capital=float(number(p["realized"]) / committed)
                    if completed and committed
                    else None,
                    return_per_usd_capital_second=float(
                        number(p["realized"]) / number(p["capital_seconds"])
                    )
                    if completed and number(p["capital_seconds"])
                    else None,
                    supported_exit_holding_seconds=exit_seconds,
                    maker_profitability_lower_bound=None,
                    economics_scope="CONDITIONAL_EXCHANGE_CASH_EXCLUDES_UNVERIFIED_EXTERNAL_REDEMPTION_COSTS",
                    initial_capital=float(number(self.config["initial_capital_usd"])),
                    weather_rejections=p["weather_rejections"],
                    fee_usd=p["fees"],
                    uncertainty="MAKER_PROFITABILITY_NOT_IDENTIFIABLE"
                    if p["mode"] == "MAKER"
                    else "CONDITIONAL_DISPLAYED_DEPTH_NOT_GUARANTEED_FILL",
                )
            )
        result.append(
            dict(
                family="WEATHER",
                mode="SIGNAL_ONLY",
                scenario="NOT_IDENTIFIABLE",
                latency_ms=0,
                status="SIGNAL_ONLY",
                net_pnl=None,
                equity=None,
                open_positions=0,
                initial_capital=100,
            )
        )
        return result
