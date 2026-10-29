"""Pure, conservative EPWA settlement reconstruction from captured evidence.

A current archive response is not a historical cutoff snapshot. These functions
never upgrade that distinction merely because its maximum agrees with a market.
"""

import hashlib
import json
import re
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from premetar.research.d1_strategy import outcome_wins, parse_outcome

VERSION = "EPWA-SETTLEMENT-v1"
ZONE = ZoneInfo("Europe/Warsaw")


def _clock(value: Any) -> datetime | None:
    try:
        if isinstance(value, datetime):
            result = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            result = datetime.fromtimestamp(value, UTC)
        elif isinstance(value, str):
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            return None
        return result.astimezone(UTC) if result.tzinfo and result.utcoffset() is not None else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def _day(value: str | date) -> date:
    return date.fromisoformat(value) if isinstance(value, str) else value


def _before(value: Any, cutoff: datetime | None) -> bool:
    parsed = _clock(value)
    return parsed is not None and cutoff is not None and parsed <= cutoff


def local_day_bounds(day: str | date) -> tuple[datetime, datetime]:
    selected = _day(day)
    return (
        datetime.combine(selected, time.min, ZONE).astimezone(UTC),
        datetime.combine(selected + timedelta(days=1), time.min, ZONE).astimezone(UTC),
    )


def round_integer(value: Decimal | str | float | int) -> int:
    """Nearest whole Celsius; an exact half goes to the warmer integer."""
    if isinstance(value, bool):
        raise ValueError("Invalid temperature")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError) as error:
        raise ValueError("Invalid temperature") from error
    if not number.is_finite():
        raise ValueError("Invalid temperature")
    return int((number + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR))


def parse_rules(market: dict[str, Any]) -> dict[str, Any]:
    """Recognize captured rule families; never transfer current rules to old days."""
    description = str(market.get("description") or "")
    source = str(market.get("resolutionSource") or "")
    lower = description.lower()
    explicit_station = bool(re.search(r"\bEPWA\b", description + " " + source, re.I))
    wrh = False
    try:
        reference = urlsplit(source)
        awc = (
            reference.scheme == "https"
            and reference.hostname in {"aviationweather.gov", "www.aviationweather.gov"}
            and reference.path == "/api/data/metar"
        )
        wu = reference.scheme == "https" and reference.hostname in {
            "wunderground.com",
            "www.wunderground.com",
        }
        source_station = parse_qs(reference.query).get("ids") == ["EPWA"]
        wrh = (
            reference.scheme == "https"
            and reference.hostname in {"weather.gov", "www.weather.gov"}
            and reference.path == "/wrh/timeseries"
            and [v.upper() for v in parse_qs(reference.query).get("site", [])] == ["EPWA"]
        )
    except ValueError:
        awc, wu, source_station = False, False, False
    t_remark = "hourly temperature remark" in lower and "eight digits" in lower
    body = "does not carry the hourly temperature remark" in lower and "body" in lower
    speci = "speci" in lower and "does not count" in lower
    local = "local time" in lower or "local date" in lower
    warmer = (
        "half rounded up to the next higher" in lower
        or "half rounded toward" in lower
        or "half rounded towards" in lower
        or "ties" in lower
        and "warmer" in lower
    )
    cutoff = "first datapoint for the following date" in lower and "after which" in lower
    correction = cutoff and "correction" in lower
    deadline = "11:59 pm et on the day following" in lower
    family = (
        "AWC_ROUTINE_T_REMARK_BODY_FALLBACK"
        if awc and t_remark and body and speci
        else "NOAA_WRH_WHOLE_C_TABLE"
        if wrh
        else "WUNDERGROUND_DAILY_TABLE"
        if wu
        else "UNKNOWN"
    )
    verified = bool(
        explicit_station
        and source_station
        and ("celsius" in lower or "°c" in lower)
        and family == "AWC_ROUTINE_T_REMARK_BODY_FALLBACK"
        and local
        and warmer
        and cutoff
        and correction
        and deadline
    )
    return dict(
        version=VERSION,
        family=family,
        status="VERIFIED_CAPTURED_RULE_CLAUSES"
        if verified
        else "PARTIALLY_VERIFIED"
        if explicit_station and family != "UNKNOWN"
        else "UNVERIFIED",
        verified=verified,
        reference_station="EPWA" if explicit_station else None,
        source_url=source or None,
        source_family="AWC" if awc else "NOAA_WRH" if wrh else "WUNDERGROUND" if wu else "UNKNOWN",
        timezone=ZONE.key if local else None,
        temperature_unit="C" if "celsius" in lower or "°c" in lower else None,
        use_t_remark=awc and t_remark,
        body_fallback=awc and body,
        speci_excluded=awc and speci,
        routine_policy="EVERY_REPORT_NOT_BEGINNING_SPECI"
        if "every other report is routine" in lower
        else "UNVERIFIED",
        rounding="NEAREST_TIES_WARMER" if warmer else "UNKNOWN",
        correction_policy="SOURCE_VIEW_AT_FIRST_FOLLOWING_DAY_DATAPOINT_CUTOFF"
        if correction
        else "UNKNOWN",
        resolution_policy="FIRST_FOLLOWING_DAY_METAR_OR_DPLUS1_2359_AMERICA_NEW_YORK"
        if deadline
        else "UNKNOWN",
        fallback_source="WUNDERGROUND_DAILY_TABLE"
        if awc and "weather underground daily observations table" in lower
        else None,
        no_data_policy="LOWEST_BRACKET_ONLY_AFTER_BOTH_SOURCE_DEADLINE_FAILURE"
        if "neither source" in lower and "lowest bracket" in lower
        else "UNKNOWN",
        exceptional_error_policy="UP_TO_SEVEN_DAY_CORRECTION_OR_CLARIFICATION"
        if "seven (7)" in lower and "clarification" in lower
        else "UNKNOWN",
        description_sha256=hashlib.sha256(description.encode()).hexdigest(),
        raw_description=description,
    )


def parse_temperature(raw: str, rules: dict[str, Any]) -> dict[str, Any]:
    text = str(raw).strip()
    result: dict[str, Any] = dict(
        raw_text=text,
        eligible=False,
        temperature_c=None,
        temperature_decimal=None,
        semantics=None,
        quality_flags=[],
    )
    if text.startswith("SPECI"):
        result["reason"] = "SPECI_EXCLUDED"
        return result
    if rules.get("family") != "AWC_ROUTINE_T_REMARK_BODY_FALLBACK":
        result["reason"] = "METAR_NOT_VERIFIED_SETTLEMENT_SOURCE_FOR_RULE_FAMILY"
        return result
    if rules.get("reference_station") != "EPWA" or not re.search(r"(?:^|\s)EPWA\s+\d{6}Z\b", text):
        result["reason"] = "MISSING_OR_WRONG_STATION_REPORT_IDENTITY"
        return result
    # The market explicitly ignores the following four dew-point digits.
    matches = re.findall(r"(?:^|\s)T([01])(\d{3})\d{4}(?=\s|=|$)", text)
    temperatures = {
        (-Decimal(digits) if sign == "1" else Decimal(digits)) / 10 for sign, digits in matches
    }
    if rules.get("use_t_remark") and len(temperatures) > 1:
        result["reason"] = "CONFLICTING_T_REMARKS"
        return result
    if rules.get("use_t_remark") and temperatures:
        value = next(iter(temperatures))
        semantics = "PRECISE_T_REMARK_TENTHS"
    elif rules.get("body_fallback"):
        groups = re.findall(r"(?:^|\s)(M?\d{2})/(?:M?\d{2}|/{1,2})(?=\s|=|$)", text)
        values = {(-Decimal(g[1:]) if g.startswith("M") else Decimal(g)) for g in groups}
        if len(values) != 1:
            result["reason"] = "NO_TEMPERATURE" if not values else "CONFLICTING_BODY_GROUPS"
            return result
        value = next(iter(values))
        semantics = "BODY_WHOLE_CELSIUS_FALLBACK"
        if re.search(r"(?:^|\s)T\S+", text):
            result["quality_flags"].append("MALFORMED_T_REMARK_IGNORED_VALID_BODY_FALLBACK")
    else:
        result["reason"] = "NO_PERMITTED_TEMPERATURE_FIELD"
        return result
    result.update(
        eligible=True,
        reason=None,
        temperature_c=float(value),
        temperature_decimal=str(value),
        semantics=semantics,
        correction=bool(re.search(r"(?:^|\s)COR(?:\s|$)", text)),
    )
    return result


def _list(value: Any) -> list[Any]:
    try:
        result = json.loads(value) if isinstance(value, str) else value
        return result if isinstance(result, list) else []
    except (ValueError, TypeError):
        return []


def resolved_market(event: dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
    """Only closed+UMA resolved+binary payout vector establishes a market label."""
    markets = event if isinstance(event, list) else event.get("markets", [event])
    result: dict[str, Any] = dict(
        confirmed=False,
        status="INSUFFICIENT_EVIDENCE",
        winning_outcome=None,
        winning_label=None,
        integer_outcome=None,
        evidence=[],
    )
    if not isinstance(markets, list) or not markets:
        return result
    winners = []
    unresolved = []
    for market in markets:
        if not isinstance(market, dict):
            unresolved.append("MALFORMED_MARKET")
            continue
        prices, outcomes = _list(market.get("outcomePrices")), _list(market.get("outcomes"))
        try:
            values = [Decimal(str(v)) for v in prices]
            binary = (
                len(values) == 2
                and sorted(values) == [Decimal(0), Decimal(1)]
                and set(outcomes) == {"Yes", "No"}
            )
        except (InvalidOperation, TypeError):
            binary = False
        final = (
            market.get("closed") is True
            and str(market.get("umaResolutionStatus", "")).lower() == "resolved"
            and binary
        )
        result["evidence"].append(
            dict(
                condition_id=market.get("conditionId"),
                closed=market.get("closed"),
                uma_resolution_status=market.get("umaResolutionStatus"),
                outcome_prices=prices,
                certified=final,
            )
        )
        if not final:
            unresolved.append(str(market.get("conditionId")))
            continue
        if values[outcomes.index("Yes")] == 1:
            label = str(market.get("groupItemTitle") or "")
            outcome = parse_outcome(label)
            if outcome:
                winners.append((label, outcome))
    if unresolved or len(winners) != 1:
        result.update(
            status="CONFLICT" if len(winners) > 1 else "INSUFFICIENT_EVIDENCE",
            unresolved_conditions=unresolved,
        )
        return result
    label, outcome = winners[0]
    result.update(
        confirmed=True,
        status="VERIFIED_MARKET_ONLY",
        winning_outcome=outcome,
        winning_label=label,
        integer_outcome=outcome["temperature_c"] if outcome["kind"] == "EXACT" else None,
    )
    return result


def _event_time(report: dict[str, Any], day: date, raw: str) -> tuple[datetime | None, str]:
    for key in (
        "observation_time_utc",
        "observation_time",
        "nominal_time",
        "obsTime",
        "reportTime",
    ):
        value = _clock(report.get(key))
        if value:
            return value, key
    match = re.search(r"(?:^|\s)EPWA\s+(\d{2})(\d{2})(\d{2})Z\b", raw)
    if not match:
        return None, "UNKNOWN"
    start, end = local_day_bounds(day)
    candidates = []
    for shift in range(-1, 3):
        candidate_day = start.date() + timedelta(days=shift)
        try:
            candidate = datetime.combine(candidate_day, time(int(match[2]), int(match[3])), UTC)
        except ValueError:
            continue
        if candidate.day == int(match[1]) and start <= candidate < end:
            candidates.append(candidate)
    return (
        (candidates[0], "METAR_DDHHMMZ_WITH_REQUESTED_LOCAL_DAY_ANCHOR")
        if len(candidates) == 1
        else (None, "UNKNOWN_OR_OUTSIDE_DAY")
    )


def reconstruct_day(
    day: str | date,
    rules: dict[str, Any],
    reports: list[dict[str, Any]],
    *,
    cutoff: datetime | None = None,
    evidence: dict[str, Any] | None = None,
    market_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_day = _day(day)
    start, end = local_day_bounds(selected_day)
    if cutoff is not None and _clock(cutoff) is None:
        raise ValueError("Timezone-aware cutoff required")
    cutoff = _clock(cutoff)
    evidence, market_result = evidence or {}, market_result or {}
    groups: dict[str, list[dict[str, Any]]] = {}
    excluded = []
    for index, report in enumerate(reports):
        raw = str(report.get("raw_text", report.get("rawOb", report.get("raw", ""))))
        parsed = parse_temperature(raw, rules)
        event_time, time_provenance = _event_time(report, selected_day, raw)
        receipt = next(
            (
                _clock(report.get(k))
                for k in (
                    "collector_receive_time",
                    "first_received_utc",
                    "first_received",
                    "received_at",
                )
                if _clock(report.get(k))
            ),
            None,
        )
        row = dict(
            parsed,
            observation_time_utc=event_time.isoformat() if event_time else None,
            observation_time_provenance=time_provenance,
            collector_receive_time=receipt.isoformat() if receipt else None,
            source_reference=report.get("source_reference", report.get("source_url")),
            raw_payload_hash=report.get(
                "raw_payload_hash", hashlib.sha256(raw.encode()).hexdigest()
            ),
            source_record_index=index,
            report_identity_sha256=hashlib.sha256(raw.strip().encode()).hexdigest(),
            source_receipt_time=next(
                (
                    parsed_time.isoformat()
                    for k in ("source_receipt_time", "provider_receipt_time", "receiptTime")
                    if (parsed_time := _clock(report.get(k)))
                ),
                None,
            ),
            source_view_at_cutoff=report.get("source_view_at_cutoff") is True,
        )
        if not parsed["eligible"] or event_time is None or not start <= event_time < end:
            if parsed["eligible"]:
                row.update(eligible=False, reason="INVALID_OR_OUTSIDE_DAY_EVENT_TIME")
            excluded.append(row)
            continue
        groups.setdefault(event_time.isoformat(), []).append(row)
    chosen = []
    unknown_versions = False
    for versions in groups.values():
        unique: dict[str, dict[str, Any]] = {}
        for version in versions:
            identity = version["report_identity_sha256"]
            if identity not in unique:
                unique[identity] = dict(
                    version, arrival_events=1, raw_payload_hashes=[version["raw_payload_hash"]]
                )
            else:
                earlier = unique[identity]
                earlier["arrival_events"] += 1
                earlier["raw_payload_hashes"].append(version["raw_payload_hash"])
                for clock_name in ("collector_receive_time", "source_receipt_time"):
                    clocks = [v for v in (earlier[clock_name], version[clock_name]) if v]
                    earlier[clock_name] = min(clocks) if clocks else None
        versions = list(unique.values())
        receipt_key = (
            "source_receipt_time"
            if evidence.get("provider_receipt_cutoff_verified") is True
            else "collector_receive_time"
        )
        known = [v for v in versions if _before(v[receipt_key], cutoff)]
        if cutoff and evidence.get("provider_receipt_cutoff_verified") is True and not known:
            excluded.extend(
                dict(v, eligible=False, reason="PROVIDER_RECEIPT_MISSING_OR_AFTER_CUTOFF")
                for v in versions
            )
            unknown_versions = True
            continue
        candidates = known or versions
        candidates.sort(key=lambda v: (v[receipt_key] or "", v["source_record_index"]))
        row = dict(
            candidates[-1],
            available_versions=len(versions),
            correction_cutoff_uncertain=bool(cutoff and not known),
        )
        if len(versions) > 1 and not known:
            unknown_versions = True
        chosen.append(row)
    chosen.sort(key=lambda v: v["observation_time_utc"])
    maximum = max((Decimal(v["temperature_decimal"]) for v in chosen), default=None)
    integer = (
        round_integer(maximum)
        if maximum is not None and rules.get("rounding") == "NEAREST_TIES_WARMER"
        else None
    )
    source_hash_verified = bool(
        re.fullmatch(r"[0-9a-f]{64}", str(evidence.get("source_snapshot_sha256", "")))
    )
    archival_certificate = bool(
        rules.get("verified")
        and evidence.get("official_source") is True
        and evidence.get("coverage_complete") is True
        and evidence.get("correction_cutoff_verified") is True
        and evidence.get("source_snapshot_at_cutoff_certified") is True
        and evidence.get("source_reference")
        and source_hash_verified
        and evidence.get("certification_basis")
        in {"ORIGINAL_CUTOFF_SNAPSHOT", "AUTHORITATIVE_VERSIONED_CUTOFF_ARCHIVE"}
        and not unknown_versions
    )
    archive_reproduction = bool(
        rules.get("verified")
        and evidence.get("official_source") is True
        and evidence.get("coverage_complete") is True
        and evidence.get("rule_eligibility_verified") is True
        and evidence.get("provider_receipt_cutoff_verified") is True
        and evidence.get("correction_versions_unambiguous") is True
        and evidence.get("source_reference")
        and source_hash_verified
        and evidence.get("certification_basis")
        == "CURRENT_OFFICIAL_ARCHIVE_REPRODUCTION_WITH_PROVIDER_RECEIPT_CUTOFF"
        and cutoff is not None
        and chosen
        and all(_before(v["source_receipt_time"], cutoff) for v in chosen)
        and not unknown_versions
    )
    certificate = archival_certificate or archive_reproduction
    confirmed = market_result.get("confirmed") is True
    outcome = market_result.get("winning_outcome")
    agrees = (
        outcome_wins(outcome, integer) if confirmed and outcome and integer is not None else None
    )
    if agrees is False:
        classification = "CONFLICT"
    elif confirmed and certificate and agrees is True:
        classification = "VERIFIED_SOURCE_AND_MARKET"
    elif confirmed:
        classification = "VERIFIED_MARKET_ONLY"
    elif maximum is not None:
        classification = "SOURCE_RECONSTRUCTED"
    else:
        classification = "INSUFFICIENT_EVIDENCE"
    return dict(
        version=VERSION,
        settlement_date=selected_day.isoformat(),
        timezone=ZONE.key,
        start_utc=start.isoformat(),
        end_utc=end.isoformat(),
        source_cutoff=cutoff.isoformat() if cutoff else None,
        classification=classification,
        qualifying_maximum_c=float(maximum) if maximum is not None else None,
        qualifying_maximum_decimal=str(maximum) if maximum is not None else None,
        integer_outcome=integer,
        winning_bracket=market_result.get("winning_label"),
        agreement=agrees,
        source_cutoff_certified=archival_certificate,
        source_reproduction_verified=certificate,
        historical_source_state_at_resolution="ORIGINAL_CUTOFF_VIEW_VERIFIED"
        if archival_certificate
        else "NOT_ARCHIVED",
        conflict_certified=agrees is False and certificate,
        selected_reports=chosen,
        excluded_reports=excluded,
        qualifying_observations=len(chosen),
        raw_report_count=len(reports),
        evidence=evidence,
        limitations=["CURRENT_BACKFILL_IS_NOT_A_HISTORICAL_CUTOFF_VIEW"]
        if not archival_certificate
        else [],
        market_result=market_result,
        report_versions=[v for group in groups.values() for v in group],
    )
