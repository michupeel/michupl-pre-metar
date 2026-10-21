"""Synthetic fixtures test mechanics, never empirical latency/accuracy claims."""

import io
import json
import zipfile
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from premetar.analysis import match_candidates, source_race
from premetar.model import (
    Observation,
    distance_to_boundary,
    encode_metar_temperature,
    icao_round_temperature,
)
from premetar.parsers import parse_awc, parse_dwd, parse_knmi_metar, parse_metar, resolve_ddhhmm
from premetar.sources import STATIONS, configured_sources, next_report
from premetar.store import report_identity, safe_url

ANCHOR = datetime(2026, 10, 21, 12, 55, tzinfo=UTC)
TAC = "METAR EDDM 211250Z AUTO 24010KT 9999 FEW020 18/12 Q1013 NOSIG"


@pytest.mark.parametrize(
    ("value", "rounded", "code"),
    [
        ("20.49", 20, "20"),
        ("20.50", 21, "21"),
        ("20.51", 21, "21"),
        ("-0.49", 0, "M00"),
        ("-0.50", 0, "M00"),
        ("-0.51", -1, "M01"),
        ("-1.49", -1, "M01"),
        ("-1.50", -1, "M01"),
        ("-1.51", -2, "M02"),
        ("0.50", 1, "01"),
        ("-0", 0, "M00"),
        ("0", 0, "00"),
    ],
)
def test_rounding(value, rounded, code):
    assert icao_round_temperature(value) == rounded
    assert encode_metar_temperature(value) == code


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_temperature_rejected(value):
    with pytest.raises(ValueError):
        icao_round_temperature(value)


def test_boundary_distance():
    assert distance_to_boundary("17.62") == Decimal("0.12")
    assert distance_to_boundary("-0.5") == 0


@pytest.mark.parametrize(
    ("token", "anchor", "expected"),
    [
        ("312350", "2026-02-01T00:05:00+00:00", "2026-01-31T23:50:00+00:00"),
        ("010020", "2026-12-31T23:59:00+00:00", "2027-01-01T00:20:00+00:00"),
        ("312350", "2027-01-01T00:01:00+00:00", "2026-12-31T23:50:00+00:00"),
        ("292350", "2024-03-01T00:10:00+00:00", "2024-02-29T23:50:00+00:00"),
    ],
)
def test_timestamp_rollover(token, anchor, expected):
    assert resolve_ddhhmm(token, datetime.fromisoformat(anchor)) == datetime.fromisoformat(expected)


def test_utc_and_naive_validation():
    with pytest.raises(ValidationError):
        Observation(
            station_icao="EDDM",
            source="test",
            product_type="OTHER",
            event_time=datetime(2026, 1, 1),
            raw_text="synthetic",
        )
    obs = Observation(
        station_icao="EDDM",
        source="test",
        product_type="OTHER",
        event_time=datetime(2026, 1, 1, 3, tzinfo=timezone(timedelta(hours=3))),
        raw_text="synthetic",
    )
    assert obs.event_time.hour == 0 and obs.event_time.tzinfo == UTC
    assert obs.source_publish_time is None and obs.collector_receive_time is None


def test_parser_full_identity_and_negative_zero():
    obs = parse_metar("SPECI COR EDDM 211250Z AUTO 24010KT 9999 M00/M01 Q1013=", ANCHOR, "test")
    assert obs.cor and obs.auto and obs.product_type == "SPECI"
    assert obs.temperature_c.is_signed()
    assert obs.metadata_json["temperature_token"] == "M00"
    assert obs.report_time == datetime(2026, 10, 21, 12, 50, tzinfo=UTC)
    base = parse_metar(TAC, ANCHOR, "a")
    duplicate = parse_metar(TAC + "=", ANCHOR, "b")
    assert report_identity(base) == report_identity(duplicate)
    assert report_identity(base) != report_identity(
        parse_metar(TAC.replace("AUTO", "COR AUTO"), ANCHOR, "a")
    )


def test_awc_clock_does_not_substitute_nominal_or_publish():
    obs = parse_awc(
        json.dumps(
            [
                {
                    "icaoId": "EDDM",
                    "rawOb": TAC,
                    "receiptTime": "2026-10-21T12:51:01.123Z",
                    "reportTime": "2026-10-21T13:00:00Z",
                }
            ]
        ).encode(),
        ANCHOR,
    )[0]
    assert obs.report_time.minute == 50
    assert obs.source_receipt_time.microsecond == 123000
    assert obs.source_publish_time is None
    assert obs.metadata_json["awc_report_time"].endswith("13:00:00Z")


def test_knmi_bulletin_and_tac_comment():
    tac = TAC.replace("EDDM", "EHAM").replace("211250Z", "211255Z")
    payload = f'WMO HEADER\n<?xml version="1.0"?><METAR translatedBulletinReceptionTime="2026-10-21T12:52:00Z"><!-- {tac}= --></METAR>'.encode()
    obs = parse_knmi_metar(payload, ANCHOR)[0]
    assert obs.station_icao == "EHAM" and obs.report_time.minute == 55
    assert obs.source_receipt_time.minute == 52
    assert obs.source_publish_time is None


def test_dwd_zip_schema_and_missing():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "produkt_zehn_now_tu_20261021_20261021_01262.txt",
            "STATIONS_ID;MESS_DATUM;QN;PP_10;TT_10;TM5_10;RF_10;TD_10;eor\n1262;202610211240;2;950.0;17.6;15;80;12.4;eor\n1262;202610211250;2;-999;-999;-999;-999;-999;eor\n",
        )
    obs = parse_dwd(buffer.getvalue(), ANCHOR)
    assert len(obs) == 1 and obs[0].temperature_c == Decimal("17.6")
    assert obs[0].event_time.minute == 40 and obs[0].report_time is None


def candidate(**updates):
    result = Observation(
        station_icao="EDDM",
        source="dwd_10min",
        product_type="DWD_10MIN",
        event_time=ANCHOR.replace(minute=40),
        temperature_c=Decimal("17.62"),
        raw_text="synthetic candidate",
        collector_receive_time=ANCHOR - timedelta(seconds=200),
        run_id="r1",
        receive_monotonic_ns=100_000_000_000,
        request_start_monotonic_ns=99_000_000_000,
        startup_censored=False,
    )
    return result.model_copy(update=updates)


def target(**updates):
    result = parse_metar(TAC, ANCHOR, "awc")
    result = result.model_copy(
        update={
            "run_id": "r1",
            "startup_censored": False,
            "collector_receive_time": ANCHOR,
            "receive_monotonic_ns": 263_320_000_000,
            "request_start_monotonic_ns": 260_000_000_000,
        }
    )
    return result.model_copy(update=updates)


def test_actionable_lead_not_nominal_delay():
    rows, _ = match_candidates([candidate(), target()])
    assert rows[0]["actionable_lead_sec"] == pytest.approx(163.320)
    assert rows[0]["target_request_start_lead_sec"] == 160
    assert rows[0]["candidate_delay_from_nominal_sec"] == 100
    assert rows[0]["exact"] and rows[0]["distance_to_boundary_c"] == 0.12


@pytest.mark.parametrize(
    "update",
    [
        {"evidence_class": "HISTORICAL_EVENT_ONLY"},
        {"collector_receive_time": None},
        {"startup_censored": True},
        {"coverage_gap": True},
        {"run_id": "different"},
        {"station_icao": "EHAM"},
        {"receive_monotonic_ns": 300_000_000_000},
    ],
)
def test_no_leakage_or_wrong_station_run(update):
    assert match_candidates([candidate(**update), target()])[0] == []


def test_never_skip_already_received_next_report():
    early = target(receive_monotonic_ns=90_000_000_000)
    later = target(
        event_time=ANCHOR.replace(hour=13, minute=20),
        report_time=ANCHOR.replace(hour=13, minute=20),
    )
    assert match_candidates([candidate(), early, later])[0] == []


def test_speci_separate_and_ambiguous_corrections():
    assert match_candidates([candidate(), target(product_type="SPECI")])[0] == []
    assert match_candidates([candidate(), target(cor=True)])[0] == []
    other = target(raw_text=TAC.replace("18/12", "19/12"), temperature_c=Decimal(19))
    assert match_candidates([candidate(), target(), other])[0] == []


def test_latest_per_bucket_does_not_select_correct_only():
    wrong = candidate(temperature_c=Decimal("19.4"), receive_monotonic_ns=110_000_000_000)
    rows, _ = match_candidates([candidate(), wrong, target()])
    assert len(rows) == 1 and not rows[0]["exact"]


def test_race_has_two_receipts():
    rows = source_race(
        [target(), target(source="knmi_metar", receive_monotonic_ns=260_320_000_000)]
    )
    assert len(rows) == 2 and sum(r["win"] for r in rows) == 1
    assert sorted(r["delay_sec"] for r in rows) == [0, 3]


def test_source_race_rejects_missing_clock():
    assert source_race([target(), target(source="other", receive_monotonic_ns=None)]) == []


def test_next_report_selection_sorts_unsorted_input():
    later = target(
        event_time=ANCHOR.replace(hour=13, minute=20),
        report_time=ANCHOR.replace(hour=13, minute=20),
        raw_text=TAC.replace("211250Z", "211320Z"),
    )
    rows, _ = match_candidates([later, candidate(), target()])
    assert rows[0]["report_time"] == ANCHOR.replace(minute=50).isoformat()


def test_url_secret_redaction():
    value = safe_url(
        "https://user:password@example.com/path?api_key=secret&ids=EHAM&X-Amz-Signature=signature#token"
    )
    assert "secret" not in value and "signature" not in value and "password" not in value
    assert "ids=EHAM" in value


def test_source_and_schedule_configuration():
    assert len(configured_sources(set(STATIONS), {"awc", "dwd_10min", "knmi_metar"}, 60)) == 3
    assert next_report(STATIONS["EDDM"], ANCHOR).hour == 13
    with pytest.raises(ValueError):
        configured_sources(set(STATIONS), {"awc"}, 1)
    with pytest.raises(ValueError):
        configured_sources(set(STATIONS), {"metar_ws"}, 60)
