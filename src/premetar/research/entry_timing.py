"""Frozen EXP0017 descriptive clocks; execution is never order placement."""

import random
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Any

VERSION = "EXP0017-ENTRY-TIMING-v1.1"
BIN_EDGES = (-300, -180, -60, -30, 0, 30, 60, 180, 300)
BIN_LABELS = (
    "<-5m",
    "[-5m,-3m)",
    "[-3m,-1m)",
    "[-60s,-30s)",
    "[-30s,0s)",
    "[0s,30s)",
    "[30s,60s)",
    "[1m,3m)",
    "[3m,5m)",
    ">=5m",
)


def utc(value: str | datetime) -> datetime:
    result = (
        datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    )
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Timezone-aware clock required")
    return result.astimezone(UTC)


def price_bucket(value: str | Decimal) -> str:
    price = Decimal(value)
    if not price.is_finite() or not 0 < price < 1:
        raise ValueError("Invalid price")
    if price < Decimal("0.90"):
        return "BELOW_0.90"
    if price <= Decimal("0.95"):
        return "0.90_TO_0.95_INCLUSIVE"
    if price < Decimal("0.98"):
        return "ABOVE_0.95_BELOW_0.98"
    if price == Decimal("0.98"):
        return "EXACT_0.98"
    if price < Decimal("0.99"):
        return "ABOVE_0.98_BELOW_0.99"
    return "EXACT_0.99" if price == Decimal("0.99") else "ABOVE_0.99"


def timing_bin(offset: float) -> str:
    return BIN_LABELS[sum(offset >= edge for edge in BIN_EDGES)]


def deduplicate(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Earliest recorded receipt; identical feed projections aren't proven fills."""
    found: dict[str, dict[str, Any]] = {}
    for row in trades:
        key = str(row["trade_id"])
        if key not in found or utc(row["first_collector_receipt_utc"]) < utc(
            found[key]["first_collector_receipt_utc"]
        ):
            found[key] = row
    return sorted(found.values(), key=lambda r: (utc(r["source_trade_timestamp"]), r["trade_id"]))


def execution_key(row: dict[str, Any]) -> str:
    return ":".join(str(row[k]) for k in ("transaction_hash", "token_id", "side"))


def cadence(reports: list[dict[str, Any]]) -> dict[str, Any]:
    clocks = sorted({utc(r["event_time"]) for r in reports if r.get("product_type") == "METAR"})
    minutes = Counter(t.minute for t in clocks)
    chosen: list[int] = []
    count = 0
    for minute, n in minutes.most_common():
        chosen.append(minute)
        count += n
        if count >= len(clocks) * 0.90:
            break
    verified = len(clocks) >= 24 and len({t.date() for t in clocks}) >= 2 and len(chosen) <= 4
    return dict(
        minutes=sorted(chosen) if verified else [],
        status="OBSERVED_ARCHIVE_CADENCE" if verified else "INSUFFICIENT_CADENCE",
        routine_cycles=len(clocks),
        minute_counts=dict(minutes),
        support=count / len(clocks) if clocks else None,
        first_nominal=clocks[0].isoformat() if clocks else None,
        last_nominal=clocks[-1].isoformat() if clocks else None,
    )


def schedule_offsets(at: datetime, minutes: list[int]) -> dict[str, Any]:
    at = utc(at)
    if not minutes or any(not 0 <= m <= 59 for m in minutes):
        return dict(nearest_offset_seconds=None, timing_bin="UNKNOWN", nearest_nominal=None)
    hour = at.replace(minute=0, second=0, microsecond=0)
    candidates = sorted({hour + timedelta(hours=h, minutes=m) for h in (-1, 0, 1) for m in minutes})
    previous = max(t for t in candidates if t <= at)
    following = min(t for t in candidates if t >= at)
    nearest = min((previous, following), key=lambda t: (abs((at - t).total_seconds()), t))
    offset = (at - nearest).total_seconds()
    return dict(
        previous_nominal=previous.isoformat(),
        next_nominal=following.isoformat(),
        nearest_nominal=nearest.isoformat(),
        previous_offset_seconds=(at - previous).total_seconds(),
        next_offset_seconds=(at - following).total_seconds(),
        nearest_offset_seconds=offset,
        timing_bin=timing_bin(offset),
        boundary_uncertain_1s=any(abs(offset - edge) <= 1 for edge in BIN_EDGES),
    )


def receipt_context(
    reports: list[dict[str, Any]], at: datetime, nominal: str | None
) -> dict[str, Any]:
    """Only trustworthy actual collector receipts; archives never create these."""
    eligible = [
        r
        for r in reports
        if r.get("collector_receive_time")
        and not r.get("startup_censored")
        and not r.get("coverage_gap")
        and r.get("evidence_class") == "REALTIME_CAPTURED"
        and r.get("product_type") == "METAR"
    ]
    target = [r for r in eligible if nominal and utc(r["event_time"]) == utc(nominal)]
    first = min((utc(r["collector_receive_time"]) for r in target), default=None)
    known = [
        r for r in eligible if utc(r["collector_receive_time"]) <= at and utc(r["event_time"]) <= at
    ]
    latest = max(
        known, key=lambda r: (utc(r["event_time"]), utc(r["collector_receive_time"])), default=None
    )
    return dict(
        first_metar_receipt=first.isoformat() if first else None,
        trade_minus_first_receipt_seconds=(at - first).total_seconds() if first else None,
        previous_available_metar=latest,
        weather_state_availability="FIRST_LOCAL_RECEIPT_KNOWN" if latest else "UNKNOWN",
        publication_status="PUBLIC_RELEASE_TIME_UNKNOWN",
    )


def phase_contrast(
    rows: list[dict[str, Any]], seed: int = 17, cluster_by: str = "market_day"
) -> dict[str, Any]:
    """Duration-normalized descriptive contrast, NOT matched market activity."""
    clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[str] = set()
    for row in rows:
        if (
            row.get("nearest_offset_seconds") is None
            or not row.get("schedule_minutes")
            or row["execution_group"] in seen
        ):
            continue
        seen.add(row["execution_group"])
        key = str(row.get("market_date"))
        if cluster_by == "market_day":
            key = str(row.get("condition_id")) + ":" + key
        clusters[key].append(row)

    items = [r for group in clusters.values() for r in group]
    exposures: dict[tuple[int, ...], float] = {}
    totals: dict[str, tuple[int, float]] = {}
    for key, group in clusters.items():
        expected = 0.0
        for row in group:
            minutes = tuple(row["schedule_minutes"])
            if minutes not in exposures:
                # Continuous union duration on an hour circle, sampled per second.
                exposures[minutes] = (
                    len({(m * 60 + d) % 3600 for m in minutes for d in range(-60, 60)}) / 3600
                )
            expected += exposures[minutes]
        totals[key] = (sum(abs(r["nearest_offset_seconds"]) <= 60 for r in group), expected)
    expected_total = sum(pair[1] for pair in totals.values())
    value = sum(pair[0] for pair in totals.values()) / expected_total if expected_total else None
    samples: list[float] = []
    keys = sorted(clusters)
    rng = random.Random(seed)
    if len(keys) >= 10:
        for _ in range(500):
            draw = [totals[key] for key in rng.choices(keys, k=len(keys))]
            expected = sum(pair[1] for pair in draw)
            if expected:
                samples.append(sum(pair[0] for pair in draw) / expected)
    samples.sort()
    return dict(
        status="UNMATCHED_UNIFORM_PHASE_DESCRIPTIVE_ONLY",
        description="No complete market-wide price/liquidity-conditioned denominator; nominal ±60s share / duration-uniform expectation. Cluster bootstrap, not causal or significance proof.",
        rate_ratio=value,
        ci_low=samples[int(len(samples) * 0.025)] if samples else None,
        ci_high=samples[min(len(samples) - 1, int(len(samples) * 0.975))] if samples else None,
        independent_executions=len(items),
        settlement_day_clusters=len(keys),
        cluster_by=cluster_by,
        seed=seed,
        matched_market_activity_status="NOT_IDENTIFIABLE",
    )


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scheduled = [r for r in rows if r.get("nearest_offset_seconds") is not None]
    offsets = [r["nearest_offset_seconds"] for r in scheduled]
    n = len(scheduled)

    def percent(value: int) -> float | None:
        return 100 * value / n if n else None

    return dict(
        n=len(rows),
        schedule_n=n,
        unknown_station_n=sum(not r.get("station") for r in rows),
        independent_executions=len({r["execution_group"] for r in rows}),
        percentages={
            **{f"within_{w}s": percent(sum(abs(t) <= w for t in offsets)) for w in (30, 60, 180)},
            "before": percent(sum(t < 0 for t in offsets)),
            "after": percent(sum(t > 0 for t in offsets)),
            "exact_nominal": percent(sum(t == 0 for t in offsets)),
        },
        median_offset_seconds=median(offsets) if offsets else None,
        hist=[
            dict(label=label, count=sum(r["timing_bin"] == label for r in scheduled))
            for label in BIN_LABELS
        ],
        receipt_known_n=sum(bool(r.get("first_metar_receipt")) for r in rows),
        known_before_trade_n=sum(
            r.get("trade_minus_first_receipt_seconds") is not None
            and r["trade_minus_first_receipt_seconds"] >= 0
            for r in rows
        ),
        median_minutes_to_day_end=median(
            [
                r["minutes_to_settlement_day_end"]
                for r in rows
                if r.get("minutes_to_settlement_day_end") is not None
            ]
        )
        if any(r.get("minutes_to_settlement_day_end") is not None for r in rows)
        else None,
    )
