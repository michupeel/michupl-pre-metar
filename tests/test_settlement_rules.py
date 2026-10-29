"""Synthetic, explicit settlement clauses and original TAC-shaped regression cases."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from premetar.research.settlement_rules import (
    local_day_bounds,
    parse_rules,
    parse_temperature,
    reconstruct_day,
    resolved_market,
    round_integer,
)

DESCRIPTION = """Warsaw Chopin Airport (EPWA), degrees Celsius. The highest
temperature in the hourly temperature remark, eight digits. A routine observation
that does not carry the hourly temperature remark uses the body temperature.
SPECI does not count. Every other report is routine. Timestamp in local time.
Exactly half rounded up to the next higher whole degree. A correction counts until
the first datapoint for the following date, after which alterations do not count.
First next-day METAR or11:59 PM ET on the day following observation date.
Weather Underground Daily Observations table fallback when no AWC temperatures.
If neither source suffices, lowest bracket. Seven (7) days error/clarification.
"""


def rules():
    return parse_rules(
        dict(
            description=DESCRIPTION,
            resolutionSource="https://aviationweather.gov/api/data/metar?ids=EPWA",
        )
    )


def test_legacy_noaa_wrh_is_not_awc_or_wunderground_primary():
    r = parse_rules(
        dict(
            description="NOAA Warsaw Chopin whole degrees Celsius; Weather Underground fallback",
            resolutionSource="https://www.weather.gov/wrh/timeseries?site=epwa",
        )
    )
    assert r["family"] == "NOAA_WRH_WHOLE_C_TABLE" and r["source_family"] == "NOAA_WRH"
    assert not r["verified"] and not r["use_t_remark"]


def market(integer=14):
    return resolved_market(
        dict(
            markets=[
                dict(
                    conditionId="one",
                    closed=True,
                    umaResolutionStatus="resolved",
                    outcomes='["Yes","No"]',
                    outcomePrices='["1","0"]',
                    groupItemTitle=f"{integer}°C",
                ),
                dict(
                    conditionId="two",
                    closed=True,
                    umaResolutionStatus="resolved",
                    outcomes=["Yes", "No"],
                    outcomePrices=[0, 1],
                    groupItemTitle="20°C or higher",
                ),
            ]
        )
    )


def report(raw="METAR EPWA 231230Z 00000KT CAVOK 14/08 Q1020", **kw):
    return dict(
        raw_text=raw,
        observation_time_utc="2026-10-23T12:30:00Z",
        collector_receive_time="2026-10-29T12:00:00Z",
        source_receipt_time="2026-10-23T12:32:00Z",
        **kw,
    )


def evidence():
    return dict(
        official_source=True,
        coverage_complete=True,
        rule_eligibility_verified=True,
        provider_receipt_cutoff_verified=True,
        correction_versions_unambiguous=True,
        source_reference="https://aviationweather.gov/official-synthetic",
        source_snapshot_sha256="a" * 64,
        certification_basis="CURRENT_OFFICIAL_ARCHIVE_REPRODUCTION_WITH_PROVIDER_RECEIPT_CUTOFF",
    )


def test_captured_current_rules_are_separate_from_wu():
    r = rules()
    assert r["verified"] and r["family"] == "AWC_ROUTINE_T_REMARK_BODY_FALLBACK"
    wu = parse_rules(
        dict(
            description="Highest temperature at Warsaw Chopin Airport (EPWA) in whole degrees Celsius local time",
            resolutionSource="https://www.wunderground.com/history/daily/pl/warsaw/EPWA",
        )
    )
    assert wu["family"] == "WUNDERGROUND_DAILY_TABLE" and not wu["verified"]
    assert parse_temperature("METAR EPWA 231230Z 14/08", wu)["eligible"] is False
    assert wu["rounding"] == "UNKNOWN"


@pytest.mark.parametrize(
    "source",
    [
        "https://aviationweather.gov.evil.test/api/data/metar?ids=EPWA",
        "https://evil.test/?next=https://aviationweather.gov/api/data/metar?ids=EPWA",
        "https://aviationweather.gov/api/data/metar?ids=EPWA,EGLL",
        "http://aviationweather.gov/api/data/metar?ids=EPWA",
    ],
)
def test_reference_host_and_station_are_not_substring_certificates(source):
    assert not parse_rules(dict(description=DESCRIPTION, resolutionSource=source))["verified"]


@pytest.mark.parametrize(
    "raw,value,semantics",
    [
        ("METAR EPWA 231230Z 13/10 RMK T01390133", 13.9, "PRECISE_T_REMARK_TENTHS"),
        ("METAR EPWA 231230Z 13/10 RMK T01399999", 13.9, "PRECISE_T_REMARK_TENTHS"),
        ("EPWA 231211Z AUTO 02/M01 RMK T10171022", -1.7, "PRECISE_T_REMARK_TENTHS"),
        ("METAR EPWA 231230Z M11/M17", -11.0, "BODY_WHOLE_CELSIUS_FALLBACK"),
        ("METAR EPWA 231230Z 18/12", 18.0, "BODY_WHOLE_CELSIUS_FALLBACK"),
        ("METAR EPWA 231230Z 03///", 3.0, "BODY_WHOLE_CELSIUS_FALLBACK"),
        ("METAR EPWA 231230Z 03/02 RMK Tbad", 3.0, "BODY_WHOLE_CELSIUS_FALLBACK"),
    ],
)
def test_temperature_sources(raw, value, semantics):
    result = parse_temperature(raw, rules())
    assert result["eligible"] and result["temperature_c"] == value
    assert result["semantics"] == semantics


@pytest.mark.parametrize(
    "value,integer",
    [
        ("16.5", 17),
        ("-8.5", -8),
        ("-0.5", 0),
        ("0.5", 1),
        ("13.9", 14),
        ("17.4", 17),
        ("-1.7", -2),
        ("-8.5001", -9),
    ],
)
def test_market_rounding_warmer_not_python_bankers(value, integer):
    assert round_integer(Decimal(value)) == integer


@pytest.mark.parametrize(
    "raw,reason",
    [
        ("SPECI EPWA 231230Z 20/12", "SPECI_EXCLUDED"),
        ("METAR EPWA 231230Z /////", "NO_TEMPERATURE"),
        ("METAR EGLL 231230Z 20/12", "MISSING_OR_WRONG_STATION_REPORT_IDENTITY"),
        ("METAR EPWA 231230Z 20/12 RMK T02000100 T02100100", "CONFLICTING_T_REMARKS"),
    ],
)
def test_ineligible_reports(raw, reason):
    result = parse_temperature(raw, rules())
    assert not result["eligible"] and result["reason"] == reason


def test_off_hour_unlabelled_routine_qualifies():
    result = reconstruct_day("2026-10-23", rules(), [dict(raw_text="EPWA 231211Z AUTO 14/08")])
    assert result["qualifying_observations"] == 1 and result["qualifying_maximum_c"] == 14


def test_source_backfill_agreement_without_certificate_is_market_only():
    result = reconstruct_day("2026-10-23", rules(), [report()], market_result=market())
    assert result["agreement"] and result["classification"] == "VERIFIED_MARKET_ONLY"
    assert not result["source_cutoff_certified"]


def test_independently_reproduced_source_is_separate_from_archived_cutoff():
    result = reconstruct_day(
        "2026-10-23",
        rules(),
        [report()],
        cutoff=datetime(2026, 10, 23, 22, 3, tzinfo=UTC),
        evidence=evidence(),
        market_result=market(),
    )
    assert result["classification"] == "VERIFIED_SOURCE_AND_MARKET"
    assert result["source_reproduction_verified"]
    assert not result["source_cutoff_certified"]
    assert result["historical_source_state_at_resolution"] == "NOT_ARCHIVED"
    assert result["selected_reports"][0]["collector_receive_time"].startswith("2026-10-29")


def test_source_reconstruction_without_market_is_not_resolved_label():
    result = reconstruct_day("2026-10-23", rules(), [report()])
    assert result["classification"] == "SOURCE_RECONSTRUCTED"
    assert result["winning_bracket"] is None


def test_source_market_disagreement_is_explicit_uncertainty():
    result = reconstruct_day("2026-10-23", rules(), [report()], market_result=market(15))
    assert result["classification"] == "CONFLICT" and result["agreement"] is False
    assert result["conflict_certified"] is False


def test_correction_after_cutoff_cannot_replace_eligible_version():
    original = report()
    corrected = report("METAR EPWA 231230Z COR 15/08")
    corrected["source_receipt_time"] = "2026-10-24T02:00:00Z"
    result = reconstruct_day(
        "2026-10-23",
        rules(),
        [original, corrected],
        cutoff=datetime(2026, 10, 23, 22, 3, tzinfo=UTC),
        evidence=evidence(),
        market_result=market(),
    )
    assert result["qualifying_maximum_c"] == 14 and result["agreement"] is True
    assert result["selected_reports"][0]["available_versions"] == 2


def test_correction_before_cutoff_is_applied():
    corrected = report("METAR EPWA 231230Z COR 15/08")
    corrected["source_receipt_time"] = "2026-10-23T13:00:00Z"
    result = reconstruct_day(
        "2026-10-23",
        rules(),
        [report(), corrected],
        cutoff=datetime(2026, 10, 23, 22, 3, tzinfo=UTC),
        evidence=evidence(),
        market_result=market(15),
    )
    assert result["qualifying_maximum_c"] == 15 and result["agreement"] is True


def test_missing_original_after_cutoff_correction_is_not_verified():
    corrected = report("METAR EPWA 231230Z COR 15/08")
    corrected["source_receipt_time"] = "2026-10-24T02:00:00Z"
    result = reconstruct_day(
        "2026-10-23",
        rules(),
        [corrected],
        cutoff=datetime(2026, 10, 23, 22, 3, tzinfo=UTC),
        evidence=evidence(),
        market_result=market(),
    )
    assert result["classification"] == "VERIFIED_MARKET_ONLY"
    assert result["qualifying_maximum_c"] is None


def test_no_data_never_fabricates_lowest_bracket():
    result = reconstruct_day("2026-10-23", rules(), [])
    assert result["classification"] == "INSUFFICIENT_EVIDENCE"
    assert result["integer_outcome"] is None


def test_dst_25h_and_23h_and_repeated_local_hour():
    start, end = local_day_bounds(date(2026, 10, 25))
    assert start.isoformat() == "2026-10-24T22:00:00+00:00"
    assert end.isoformat() == "2026-10-25T23:00:00+00:00"
    assert end - start == timedelta(hours=25)
    assert local_day_bounds("2026-03-29")[1] - local_day_bounds("2026-03-29")[0] == timedelta(
        hours=23
    )
    reports = [
        dict(raw_text="EPWA 250230Z 12/08", observation_time_utc="2026-10-25T00:30:00Z"),
        dict(raw_text="EPWA 250230Z 13/08", observation_time_utc="2026-10-25T01:30:00Z"),
    ]
    result = reconstruct_day("2026-10-25", rules(), reports)
    assert result["qualifying_observations"] == 2


def test_day_boundary_end_exclusive_and_month_rollover():
    reports = [
        dict(raw_text="EPWA 312330Z 12/08"),
        dict(raw_text="EPWA 012300Z 15/08", observation_time_utc="2026-11-01T23:00:00Z"),
    ]
    result = reconstruct_day("2026-11-01", rules(), reports)
    assert result["qualifying_observations"] == 1 and result["qualifying_maximum_c"] == 12


def test_duplicate_reports_do_not_inflate_cycles():
    result = reconstruct_day("2026-10-23", rules(), [report(), report(), report()])
    assert result["raw_report_count"] == 3 and result["qualifying_observations"] == 1


def test_near_one_price_or_last_trade_is_not_resolution():
    raw = dict(
        conditionId="c",
        closed=True,
        umaResolutionStatus="proposed",
        outcomes=["Yes", "No"],
        outcomePrices=[1, 0],
        lastTradePrice=1,
        groupItemTitle="14°C",
    )
    assert not resolved_market(raw)["confirmed"]
    raw["umaResolutionStatus"] = "resolved"
    raw["outcomePrices"] = [0.999, 0.001]
    assert not resolved_market(raw)["confirmed"]


def test_two_winning_yes_outcomes_are_conflict():
    rows = [
        dict(
            conditionId=str(i),
            closed=True,
            umaResolutionStatus="resolved",
            outcomes=["Yes", "No"],
            outcomePrices=[1, 0],
            groupItemTitle=f"{i}°C",
        )
        for i in [14, 15]
    ]
    assert resolved_market(rows)["status"] == "CONFLICT"


def test_tail_winner_does_not_invent_exact_tmax():
    result = resolved_market(
        dict(
            closed=True,
            umaResolutionStatus="resolved",
            outcomes=["No", "Yes"],
            outcomePrices=[0, 1],
            groupItemTitle="14°C or higher",
        )
    )
    assert result["confirmed"] and result["integer_outcome"] is None


def test_original_cutoff_snapshot_certificate_is_stricter_axis():
    e = evidence()
    e.update(
        source_snapshot_at_cutoff_certified=True,
        correction_cutoff_verified=True,
        certification_basis="ORIGINAL_CUTOFF_SNAPSHOT",
    )
    result = reconstruct_day(
        "2026-10-23",
        rules(),
        [report()],
        cutoff=datetime(2026, 10, 23, 22, 3, tzinfo=UTC),
        evidence=e,
        market_result=market(),
    )
    assert (
        result["source_cutoff_certified"]
        and result["historical_source_state_at_resolution"] == "ORIGINAL_CUTOFF_VIEW_VERIFIED"
    )
