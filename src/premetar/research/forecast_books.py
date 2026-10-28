"""Pure conservative depth replay for existing raw-first trader stream events.

No PONG/last-trade event certifies depth freshness. Stream continuity is scoped
to one connection and full snapshot. Replayed visible depth is observational,
not a guarantee of execution, sequence completeness, matching priority or costs.
"""

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("Expected timezone-aware UTC")
    return value.astimezone(UTC)


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("Invalid decimal")
    try:
        result = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError("Invalid decimal") from error
    if not result.is_finite():
        raise ValueError("Non-finite decimal")
    return result


def _price(value: Any) -> Decimal:
    result = _decimal(value)
    if not 0 < result < 1:
        raise ValueError("Price outside (0,1)")
    return result


def _levels(value: Any) -> dict[Decimal, Decimal]:
    if not isinstance(value, list):
        raise ValueError("Missing full side")
    result: dict[Decimal, Decimal] = {}
    for level in value:
        if not isinstance(level, dict):
            raise ValueError("Malformed level")
        price, size = _price(level.get("price")), _decimal(level.get("size"))
        if price in result or size <= 0:
            raise ValueError("Duplicate or invalid level")
        result[price] = size
    return result


def _uncrossed(bids: dict[Decimal, Decimal], asks: dict[Decimal, Decimal]) -> None:
    if bids and asks and max(bids) >= min(asks):
        raise ValueError("Crossed or locked book")


@dataclass
class _Book:
    connection_id: str
    market: str
    received: datetime
    bids: dict[Decimal, Decimal]
    asks: dict[Decimal, Decimal]


class BookTracker:
    """In-memory replay only; persist incoming raw events in the caller first."""

    def __init__(self, max_age_seconds: float = 10.0) -> None:
        if not math.isfinite(max_age_seconds) or not 0 < max_age_seconds <= 10:
            raise ValueError("Depth age bound must be in (0,10] seconds")
        self.max_age_seconds = max_age_seconds
        self.connection_id: str | None = None
        self.tokens: set[str] = set()
        self.books: dict[str, _Book] = {}
        self.invalid: dict[str, str] = {}

    def _invalidate(self, reason: str) -> None:
        self._invalidate_tokens(self.tokens | self.books.keys(), reason)

    def _invalidate_tokens(self, tokens: set[str], reason: str) -> None:
        for token in tokens:
            self.invalid[token] = reason
            self.books.pop(token, None)

    def _affected_tokens(self, kind: str, payload: dict[str, Any]) -> set[str] | None:
        """Scope bad depth only when every affected subscribed identity is explicit.

        Unknown or incomplete identity cannot safely identify a local failure;
        reconnects and malformed wire messages still invalidate the whole epoch.
        """
        if kind == "BOOK":
            token = payload.get("token_id")
            return {token} if isinstance(token, str) and token in self.tokens else None
        changes = payload.get("price_changes")
        if not isinstance(changes, list) or not changes:
            return None
        affected: set[str] = set()
        for change in changes:
            if not isinstance(change, dict):
                return None
            token = change.get("asset_id")
            if not isinstance(token, str) or token not in self.tokens:
                return None
            affected.add(token)
        return affected

    def view(self, token: str, at: datetime) -> dict[str, Any]:
        """Only the latest replay state is available; never use this as history."""
        at = _utc(at)
        book = self.books.get(token)
        status = self.invalid.get(token, "NO_FULL_SNAPSHOT")
        if token not in self.tokens:
            status = "NOT_SUBSCRIBED"
        elif book is not None:
            if book.connection_id != self.connection_id:
                status = "CONNECTION_INVALID"
            elif book.received > at:
                status = "FUTURE_BOOK"
            elif (at - book.received).total_seconds() > self.max_age_seconds:
                status = "STALE_BOOK"
            else:
                status = "VALID"
        base: dict[str, Any] = {
            "token_id": token,
            "status": status,
            "best_bid": None,
            "best_ask": None,
            "bid_size": None,
            "ask_size": None,
            "midpoint": None,
            "received_at": book.received.isoformat() if book else None,
            "connection_id": book.connection_id if book else self.connection_id,
            "market": book.market if book else None,
            "depth": None,
            "bids": [],
            "asks": [],
            "sequence_completeness": "NOT_INDEPENDENTLY_VERIFIED",
        }
        if status != "VALID" or book is None:
            return base
        bid, ask = max(book.bids, default=None), min(book.asks, default=None)
        return {
            **base,
            "best_bid": str(bid) if bid is not None else None,
            "best_ask": str(ask) if ask is not None else None,
            "bid_size": str(book.bids[bid]) if bid is not None else None,
            "ask_size": str(book.asks[ask]) if ask is not None else None,
            "midpoint": str((bid + ask) / 2) if bid is not None and ask is not None else None,
            "depth": {
                "bid_shares": str(sum(book.bids.values(), Decimal(0))),
                "ask_shares": str(sum(book.asks.values(), Decimal(0))),
            },
            "bids": [
                {"price": str(price), "size": str(book.bids[price])}
                for price in sorted(book.bids, reverse=True)
            ],
            "asks": [
                {"price": str(price), "size": str(book.asks[price])} for price in sorted(book.asks)
            ],
        }

    def observe(
        self, kind: str, payload: dict[str, Any], received: datetime
    ) -> list[dict[str, Any]]:
        """Apply one receive-ordered event and return fixed >=.02 midpoint changes."""
        received = _utc(received)
        connection = payload.get("connection_id")
        if kind == "STOP":
            self._invalidate("PROCESS_STOPPED")
            self.connection_id = None
            return []
        if kind == "STREAMHEALTH":
            state = payload.get("state")
            if state in {"SUBSCRIBED", "SUBSCRIPTIONS_CHANGED"}:
                tokens = payload.get("tokens")
                if (
                    not isinstance(connection, str)
                    or not connection
                    or not isinstance(tokens, list)
                    or any(not isinstance(token, str) or not token for token in tokens)
                    or len(set(tokens)) != len(tokens)
                ):
                    self._invalidate("MALFORMED_SUBSCRIPTION")
                    return []
                if state == "SUBSCRIBED" or connection != self.connection_id:
                    self._invalidate("NEW_CONNECTION_REQUIRES_SNAPSHOT")
                else:
                    for token in self.tokens - set(tokens):
                        self.books.pop(token, None)
                        self.invalid[token] = "NOT_SUBSCRIBED"
                self.connection_id, self.tokens = connection, set(tokens)
                return []
            if connection == self.connection_id and state in {
                "RECONNECTING",
                "MALFORMED_MESSAGE",
            }:
                self._invalidate(str(state))
                if state == "RECONNECTING":
                    self.connection_id = None
            return []
        if kind not in {"BOOK", "WS_DELTA"} or connection != self.connection_id:
            return []
        before = {token: self.view(token, received) for token in self.tokens}
        try:
            if kind == "BOOK":
                token_value = payload.get("token_id")
                market = payload.get("market")
                if (
                    not isinstance(token_value, str)
                    or token_value not in self.tokens
                    or not isinstance(market, str)
                    or not market
                    or payload.get("complete") is not True
                ):
                    raise ValueError("Missing market or subscription/full-snapshot evidence")
                token = token_value
                bids, asks = _levels(payload.get("bids")), _levels(payload.get("asks"))
                _uncrossed(bids, asks)
                prior = self.books.get(token)
                if prior and received < prior.received:
                    raise ValueError("Out-of-order depth receipt")
                if prior and prior.market != market:
                    raise ValueError("Token condition changed")
                self.books[token] = _Book(str(connection), market, received, bids, asks)
                self.invalid.pop(token, None)
            else:
                self._delta(payload, received)
        except (ValueError, TypeError, KeyError):
            affected = self._affected_tokens(kind, payload)
            if affected is None:
                self._invalidate("INVALID_DEPTH_REQUIRES_SNAPSHOT")
            else:
                self._invalidate_tokens(affected, "INVALID_DEPTH_REQUIRES_SNAPSHOT")
            return []
        signals = []
        for token in self.tokens:
            previous, current = before[token], self.view(token, received)
            if (
                previous["status"] == current["status"] == "VALID"
                and previous["midpoint"] is not None
                and current["midpoint"] is not None
                and abs(Decimal(current["midpoint"]) - Decimal(previous["midpoint"]))
                >= Decimal("0.02")
            ):
                signals.append(
                    {
                        "kind": "ORDERBOOK_REPRICING_DETECTED",
                        "token_id": token,
                        "created_at": received.isoformat(),
                        "connection_id": connection,
                        "before": previous,
                        "after": current,
                        "threshold": "0.02",
                        "causal_attribution": "UNKNOWN",
                    }
                )
        return signals

    def _delta(self, payload: dict[str, Any], received: datetime) -> None:
        changes = payload.get("price_changes")
        if not isinstance(changes, list) or not changes:
            raise ValueError("Missing price changes")
        updates: dict[str, _Book] = {}
        seen: set[tuple[str, str, Decimal]] = set()
        for change in changes:
            if not isinstance(change, dict):
                raise ValueError("Malformed change")
            token = change.get("asset_id")
            if not isinstance(token, str):
                raise ValueError("Missing delta asset identity")
            book = self.books.get(token)
            if token not in self.tokens or book is None:
                raise ValueError("Delta without full snapshot")
            if book.market != payload.get("market") or received < book.received:
                raise ValueError("Wrong condition or out-of-order receipt")
            if token not in updates:
                updates[token] = _Book(
                    book.connection_id, book.market, received, dict(book.bids), dict(book.asks)
                )
            target = updates[token]
            side = change.get("side")
            if side not in {"BUY", "SELL"}:
                raise ValueError("Invalid change side")
            price, size = _price(change.get("price")), _decimal(change.get("size"))
            identity = (token, side, price)
            if identity in seen or size < 0:
                raise ValueError("Duplicate change or negative size")
            seen.add(identity)
            levels = target.bids if side == "BUY" else target.asks
            if size == 0:
                levels.pop(price, None)
            else:
                levels[price] = size
        for target in updates.values():
            _uncrossed(target.bids, target.asks)
        for change in changes:
            target = updates[change["asset_id"]]
            for key, levels, empty in (
                ("best_bid", target.bids, Decimal(0)),
                ("best_ask", target.asks, Decimal(1)),
            ):
                if key not in change or change[key] is None:
                    continue
                expected = (max(levels) if key == "best_bid" else min(levels)) if levels else empty
                if _decimal(change[key]) != expected:
                    raise ValueError("Top quote disagrees with replayed depth")
        self.books.update(updates)

    def opportunities(
        self, yes: str, no: str, at: datetime, condition_id: str | None = None
    ) -> dict[str, Any]:
        """Visible pair prices only; caller must verify exact binary outcome identity."""
        yes_view, no_view = self.view(yes, at), self.view(no, at)
        base: dict[str, Any] = {
            "yes": yes_view,
            "no": no_view,
            "direct_no_asks": [],
            "complement_yes_bids": [],
            "net_execution": "BLOCKED_UNKNOWN_FEES_AND_MATCHING_PRIORITY",
            "guaranteed_fill": False,
            "binary_identity": "CALLER_MUST_VERIFY_EXACT_PAIR",
        }
        if yes == no:
            return {**base, "status": "INVALID_PAIR"}
        if yes_view["status"] != "VALID" or no_view["status"] != "VALID":
            return {**base, "status": "PAIR_NOT_FRESH"}
        if yes_view["connection_id"] != no_view["connection_id"]:
            return {**base, "status": "DIFFERENT_CONNECTIONS"}
        if yes_view["market"] != no_view["market"] or (
            condition_id is not None and yes_view["market"] != condition_id
        ):
            return {**base, "status": "WRONG_CONDITION"}
        return {
            **base,
            "status": "COMPLEMENTARY_INDICATIVE_NOT_FILL",
            "direct_no_asks": no_view["asks"],
            "complement_yes_bids": [
                {"price": str(Decimal(1) - Decimal(level["price"])), "size": level["size"]}
                for level in yes_view["bids"]
            ],
        }
