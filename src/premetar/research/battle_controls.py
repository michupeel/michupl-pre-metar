"""Frozen analytical controls, not shadow orders or independently evidenced fills.

The randomization is fixed by order identity and seed before outcomes exist.
Price/liquidity mismatches and missing deadlines are retained, never resampled.
"""

import hashlib
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from premetar.pws.daily_time import local_day_bounds
from premetar.research.limit99 import clock, fresh_book, number

VERSION = "EPWA-MATCHED-CONTROLS-v1"
SEED = 20261028
HORIZONS = (5, 10, 30, 60, 300, 900, 3600)
MAX_CONTROLS = 1000


def _time(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timezone required")
        return value.astimezone(UTC)
    return clock(str(value))


def _event(kind: str, at: datetime, **payload: Any) -> dict[str, Any]:
    return dict(kind=kind, at=at.isoformat(), payload=dict(version=VERSION, **payload))


def _window_flags(peak: dict[str, Any] | None, at: datetime) -> dict[str, Any]:
    known_time = None
    if isinstance(peak, dict):
        try:
            receipt = _time(peak["first_received"]) if peak.get("first_received") else at
            candidate = _time(peak.get("time", (peak.get("times") or [None])[0]))
            if receipt <= at:
                known_time = candidate
        except (ValueError, KeyError, TypeError, OverflowError):
            pass
    start = at.replace(minute=0, second=0, microsecond=0)
    nominal = min(
        (start + timedelta(minutes=m) for m in (-30, 0, 30, 60)),
        key=lambda t: abs((at - t).total_seconds()),
    )
    return dict(
        forecast_peak_time=known_time.isoformat() if known_time else None,
        within_forecast_tmax_window=abs((at - known_time).total_seconds()) <= 3600
        if known_time
        else None,
        forecast_tmax_window_seconds=3600,
        within_nominal_metar_window=abs((at - nominal).total_seconds()) <= 180,
        nearest_nominal_metar=nominal.isoformat(),
        metar_window_seconds=180,
        policy="ANNOTATIONS_ONLY_NEVER_SIMPLE_ENTRY_GATES",
    )


class ControlTracker:
    """Restartable bounded control state; at capacity new controls are rejected.

    Completed identities remain in the checkpoint for deduplication. No eviction
    silently re-registers an old order. After1000 controls the runner must freeze
    this cohort and start an explicitly versioned cohort, not clear its history.
    """

    def __init__(self, state: dict[str, Any] | None = None) -> None:
        self.state: dict[str, Any] = (
            deepcopy(state) if state is not None else dict(version=VERSION, seed=SEED, controls={})
        )
        if self.state.get("version") != VERSION or self.state.get("seed") != SEED:
            raise ValueError("Frozen control version/seed mismatch")
        if (
            not isinstance(self.state.get("controls"), dict)
            or len(self.state["controls"]) > MAX_CONTROLS
        ):
            raise ValueError("Invalid or unbounded control checkpoint")

    def register(
        self, event: dict[str, Any], forecast_peak: dict[str, Any] | None, at: datetime
    ) -> list[dict[str, Any]]:
        at = _time(at)
        payload = event.get("payload") or {}
        if event.get("kind") != "BUY_SUBMITTED" or payload.get("family") != "SIMPLE":
            return []
        order = payload.get("order") or {}
        try:
            order_id = str(order["id"])
            if order_id in self.state["controls"]:
                return []
            price, quantity = number(order["limit"]), number(order["quantity"])
            if not Decimal(".91") < price < Decimal(".98") or quantity <= 0:
                return []
            event_time = _time(event["at"])
            created = _time(order.get("created_at", event["at"]))
            if event_time != at or created != at:
                return [
                    _event(
                        "CONTROL_REJECTED",
                        at,
                        order_id=order_id,
                        reason="REGISTRATION_MUST_USE_ORIGINAL_SUBMISSION_TIME",
                    )
                ]
            day = date.fromisoformat(order["day"])
            day_start, day_end = local_day_bounds(day, "Europe/Warsaw")
            if not day_start <= at < day_end:
                return [
                    _event(
                        "CONTROL_REJECTED",
                        at,
                        order_id=order_id,
                        reason="SUBMISSION_OUTSIDE_SETTLEMENT_DAY",
                    )
                ]
            condition, token = str(order["condition_id"]), str(order["token_id"])
            if (
                not order_id
                or not condition
                or not token
                or payload.get("mode") not in {"MAKER", "TAKER"}
            ):
                raise ValueError("Incomplete control identity")
        except (ValueError, KeyError, TypeError, ArithmeticError, OverflowError):
            return [_event("CONTROL_REJECTED", at, reason="MALFORMED_CONTROL_INPUT")]
        controls = self.state["controls"]
        if order_id in controls:
            return []
        if len(controls) >= MAX_CONTROLS:
            return [
                _event(
                    "CONTROL_BACKPRESSURE",
                    at,
                    order_id=order_id,
                    reason="MAX1000_FROZEN_COHORT; NO_ORDER_OR_FILL_CREATED",
                )
            ]
        delay = (
            int.from_bytes(hashlib.sha256(f"{SEED}:{order_id}".encode()).digest()[:8], "big") % 61
        )
        flags = _window_flags(forecast_peak, at)
        control = dict(
            order_id=order_id,
            condition_id=condition,
            token_id=token,
            day=order["day"],
            mode=payload["mode"],
            scenario=payload.get("scenario"),
            latency_ms=payload.get("latency_ms"),
            price=str(price),
            quantity=str(quantity),
            decision_time=at.isoformat(),
            day_end=day_end.isoformat(),
            time_to_settlement_seconds=(day_end - at).total_seconds(),
            random_delay_seconds=delay,
            random_due=(at + timedelta(seconds=delay)).isoformat(),
            random_status="PENDING",
            flags=flags,
            horizons={
                str(seconds): dict(
                    due=(at + timedelta(seconds=seconds)).isoformat(), status="PENDING"
                )
                for seconds in HORIZONS
            },
        )
        controls[order_id] = control
        return [
            _event(
                "CONTROL_ANNOTATION",
                at,
                **{k: v for k, v in control.items() if k != "horizons"},
                seed=SEED,
                horizons_seconds=list(HORIZONS),
                matching_window_seconds=2,
                price_tolerance=".01",
                liquidity_policy="SAME_MODE_DISPLAYED_NO_SIDE_WITHIN_PRICE_TOLERANCE",
                randomization="SHA256(seed:order_id)_FIRST8BYTES_MOD61",
                execution_claim="NO_ORDER_OR_FILL; ANALYTICAL_MATCH_ONLY",
            )
        ]

    def observe(
        self, condition_id: str, book: dict[str, Any], at: datetime
    ) -> list[dict[str, Any]]:
        at = _time(at)
        result = []
        for control in self.state["controls"].values():
            decision = _time(control["decision_time"])
            if at < decision:
                continue
            same = control["condition_id"] == condition_id
            valid = bool(same and fresh_book(book, at, control["token_id"], condition_id))
            received = _time(book["received_at"]) if valid else None
            random_due = _time(control["random_due"])
            if control["random_status"] == "PENDING" and at >= random_due:
                if (
                    valid
                    and received is not None
                    and random_due <= received <= random_due + timedelta(seconds=2)
                    and at <= random_due + timedelta(seconds=2)
                ):
                    side = "bids" if control["mode"] == "MAKER" else "asks"
                    levels = book[side]
                    price = (max if side == "bids" else min)(
                        (number(r["price"]) for r in levels), default=None
                    )
                    limit, quantity = number(control["price"]), number(control["quantity"])
                    available = sum(
                        (
                            number(row["size"])
                            for row in levels
                            if abs(number(row["price"]) - limit) <= Decimal(".01")
                        ),
                        Decimal(0),
                    )
                    remaining = (_time(control["day_end"]) - at).total_seconds()
                    reason = (
                        "MATCHED"
                        if price is not None
                        and abs(price - limit) <= Decimal(".01")
                        and available >= quantity
                        and abs(remaining - control["time_to_settlement_seconds"]) <= 60
                        else "PRICE_LIQUIDITY_OR_TIME_TO_SETTLEMENT_MISMATCH"
                    )
                    matched = reason == "MATCHED"
                    control["random_status"] = "MATCHED" if matched else "UNMATCHED"
                    result.append(
                        _event(
                            "CONTROL_MATCH" if matched else "CONTROL_UNMATCHED",
                            at,
                            order_id=control["order_id"],
                            condition_id=condition_id,
                            due=random_due.isoformat(),
                            book_received_at=received.isoformat(),
                            observed_at=at.isoformat(),
                            price=str(price) if price is not None else None,
                            visible_quantity=str(available),
                            proposed_quantity=control["quantity"],
                            price_tolerance=".01",
                            reason=reason,
                            elapsed_seconds=(at - decision).total_seconds(),
                            execution_claim="DISPLAYED_MATCH_NOT_EXECUTION",
                            flags=control["flags"],
                        )
                    )
                elif at > random_due + timedelta(seconds=2):
                    control["random_status"] = "UNMATCHED"
                    result.append(
                        _event(
                            "CONTROL_UNMATCHED",
                            at,
                            order_id=control["order_id"],
                            condition_id=control["condition_id"],
                            due=random_due.isoformat(),
                            reason="NO_ELIGIBLE_BOOK_WITHIN2S; NO_HINDSIGHT_MATCH",
                            execution_claim="UNKNOWN",
                        )
                    )
            for horizon, capture in control["horizons"].items():
                if capture["status"] != "PENDING":
                    continue
                due = _time(capture["due"])
                if at < due:
                    continue
                if (
                    valid
                    and received is not None
                    and due <= received <= due + timedelta(seconds=2)
                    and at <= due + timedelta(seconds=2)
                ):
                    capture.update(
                        status="CAPTURED", at=at.isoformat(), book_received_at=received.isoformat()
                    )
                    bid = max((number(row["price"]) for row in book["bids"]), default=None)
                    ask = min((number(row["price"]) for row in book["asks"]), default=None)
                    exit_quantity = sum(
                        (
                            number(row["size"])
                            for row in book["bids"]
                            if number(row["price"]) >= Decimal(".99")
                        ),
                        Decimal(0),
                    )
                    result.append(
                        _event(
                            "CONTROL_HORIZON",
                            at,
                            order_id=control["order_id"],
                            condition_id=condition_id,
                            token_id=control["token_id"],
                            horizon_seconds=int(horizon),
                            due=due.isoformat(),
                            book_received_at=received.isoformat(),
                            best_bid=str(bid) if bid is not None else None,
                            best_ask=str(ask) if ask is not None else None,
                            direct_exit99_visible_quantity=str(exit_quantity),
                            exit99_visible_enough=exit_quantity >= number(control["quantity"]),
                            execution_claim="VISIBLE_QUOTES_NOT_SUPPORTED_OWN_FILL",
                            flags=control["flags"],
                        )
                    )
                elif at > due + timedelta(seconds=2):
                    capture.update(status="UNRESOLVED", at=at.isoformat())
                    result.append(
                        _event(
                            "CONTROL_HORIZON_UNRESOLVED",
                            at,
                            order_id=control["order_id"],
                            condition_id=control["condition_id"],
                            horizon_seconds=int(horizon),
                            due=due.isoformat(),
                            reason="NO_ELIGIBLE_BOOK_WITHIN2S",
                        )
                    )
        return result
