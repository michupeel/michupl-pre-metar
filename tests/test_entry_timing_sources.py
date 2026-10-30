"""Bounded public capture and nominal-time parsing; synthetic tests are labeled."""

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.research.entry_timing_sources import (  # noqa: E402
    Capture,
    fetch_markets,
    parse_archive,
    tokens,
)


def receipt() -> dict[str, str]:
    return {"sha256": "test-hash", "received_at": "2026-10-29T20:00:00+00:00"}


def test_recorded_iem_response_shape() -> None:
    # Actual raw CSV excerpt, SHA256 15b3d4cebe0db2f53fcb642ca24af8e8408a803f01e8f7cdee91b7f040c3eea2.
    body = (
        b"station,valid,metar\n"
        b"EPWA,2026-05-20 00:00,EPWA 200000Z 24002KT 9000 NSC 09/08 Q1020 NOSIG\n"
        b"ATL,2026-05-20 00:52,KATL 200052Z 14004KT 10SM FEW200 27/14 A3015 RMK AO2 SLP202 T02720144 $\n"
    )
    rows, errors = parse_archive(body, receipt(), {"EPWA", "KATL"}, "3")
    assert not errors
    assert [row["station_icao"] for row in rows] == ["EPWA", "KATL"]
    assert rows[0]["temperature_c"] == 9
    assert rows[1]["temperature_c"] == 27  # Body integer, no false precise T-group claim.
    assert all(row["collector_receive_time"] is None for row in rows)
    assert all(row["product_type"] == "UNKNOWN_ROUTINE_OR_SPECI" for row in rows)
    assert all(row["candidate_product_type"] == "METAR" for row in rows)


def test_archive_nominal_times_have_no_collector_receipt() -> None:
    body = (
        b"station,valid,metar\nEPWA,2026-10-25 00:30,METAR EPWA 250030Z 00000KT CAVOK 09/07 Q1018\n"
    )
    rows, errors = parse_archive(body, receipt(), {"EPWA"}, "3")
    assert not errors
    assert rows[0]["event_time"] == "2026-10-25T00:30:00+00:00"
    assert rows[0]["collector_receive_time"] is None
    assert rows[0]["archive_first_received_at"] == receipt()["received_at"]
    assert rows[0]["temperature_c"] == 9
    assert rows[0]["product_type"] == "METAR"


def test_archive_specials_corrections_and_offsets_preserved() -> None:
    body = (
        b"station,valid,metar\nEPWA,2026-10-25T02:30:00+02:00,SPECI EPWA 250030Z COR 00000KT CAVOK M02/M03 Q1018\n"
        b"EPWA,2026-10-25T02:30:00+01:00,SPECI EPWA 250130Z 00000KT CAVOK M01/M03 Q1018\n"
    )
    rows, errors = parse_archive(body, receipt(), {"EPWA"}, "4")
    assert not errors
    assert len(rows) == 2
    assert rows[0]["event_time"] != rows[1]["event_time"]
    assert rows[0]["correction_status"] == "COR"
    assert rows[0]["temperature_c"] == -2
    assert all(row["product_type"] == "SPECI" for row in rows)


@pytest.mark.parametrize("report_type", ["3", "4"])
def test_iem_hourly_classifier_is_not_icao_identity(report_type: str) -> None:
    # Synthetic half-hour TAC reproduces the actual class4 ambiguity. Without an
    # original METAR/SPECI prefix, preserve uncertainty for BOTH IEM classes.
    body = (
        b"station,valid,metar\nEPWA,2026-10-22 20:30,EPWA 222030Z 19008KT CAVOK 09/05 Q1020 NOSIG\n"
    )
    rows, errors = parse_archive(body, receipt(), {"EPWA"}, report_type)
    assert not errors
    assert rows[0]["product_type"] == "UNKNOWN_ROUTINE_OR_SPECI"
    assert rows[0]["candidate_product_type"] == "METAR"
    assert rows[0]["archive_report_type"] == report_type
    assert rows[0]["report_type_provenance"] == "IEM_HOURLY_CLASSIFIER_NOT_ICAO_REPORT_IDENTITY"
    assert rows[0]["classification_flags"] == ["ORIGINAL_METAR_SPECI_PREFIX_ABSENT"]


def test_explicit_metar_prefix_overrides_iem_nonhourly_class() -> None:
    body = b"station,valid,metar\nEPWA,2026-10-22 20:30,METAR EPWA 222030Z 19008KT CAVOK 09/05 Q1020 NOSIG\n"
    rows, errors = parse_archive(body, receipt(), {"EPWA"}, "4")
    assert not errors
    assert rows[0]["product_type"] == "METAR"
    assert rows[0]["archive_report_type"] == "4"
    assert rows[0]["report_type_provenance"] == "EXPLICIT_ORIGINAL_TAC_PREFIX"


def test_recorded_epwa_half_hour_is_not_automatically_speci() -> None:
    # Actual IEM type4 body, raw SHA256 3fa607f61378f7d79dca0fdb62d5585a56c6ae42fcecc2cf1375b13525a42a7b.
    body = b"station,valid,metar\nEPWA,2026-10-22 20:30,EPWA 222030Z 29013KT 9999 -RA BKN007 BKN020 09/09 Q1015 NOSIG\n"
    rows, errors = parse_archive(body, receipt(), {"EPWA"}, "4")
    assert not errors
    assert rows[0]["product_type"] == "UNKNOWN_ROUTINE_OR_SPECI"
    assert rows[0]["archive_hourly_class"] == "IEM_NONHOURLY"
    assert rows[0]["event_time"] == "2026-10-22T20:30:00+00:00"


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (b"bad,fields\n1,2\n", "UNEXPECTED_ARCHIVE_SCHEMA"),
        (
            b"station,valid,metar\nEGLL,2026-10-25 00:30,METAR EGLL 250030Z 09/07\n",
            "UNVERIFIED_ARCHIVE_STATION",
        ),
        (
            b"station,valid,metar\nEPWA,2026-10-25 00:30,METAR EPWA 250100Z 09/07\n",
            "ARCHIVE_TAC_TIME_MISMATCH",
        ),
    ],
)
def test_invalid_archive_rows_remain_errors(body: bytes, reason: str) -> None:
    rows, errors = parse_archive(body, receipt(), {"EPWA"}, "3")
    assert not rows
    assert errors[0]["reason"] == reason


def test_cached_raw_is_immutable_and_hash_checked(tmp_path: Path) -> None:
    calls = []

    def response(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=b"[]")

    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        capture = Capture(tmp_path, client, max_requests=1)
        body, metadata = capture.get("https://gamma-api.polymarket.com/markets", [("limit", "1")])
        assert body == b"[]"
        assert (
            capture.get("https://gamma-api.polymarket.com/markets", [("limit", "1")])[1] == metadata
        )
        assert len(calls) == 1
        (tmp_path / (metadata["sha256"] + ".raw")).write_bytes(b"{}")
        with pytest.raises(ValueError, match="hash"):
            capture.get("https://gamma-api.polymarket.com/markets", [("limit", "1")])


def test_source_allowlist_and_request_budget(tmp_path: Path) -> None:
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"[]"))
    ) as client:
        capture = Capture(tmp_path, client, max_requests=0)
        with pytest.raises(ValueError, match="allowlist"):
            capture.get("https://example.com/markets", [])
        with pytest.raises(RuntimeError, match="budget"):
            capture.get("https://gamma-api.polymarket.com/markets", [])


def test_http_error_raw_is_preserved_without_retry(tmp_path: Path) -> None:
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(429, content=b'{"error":"limited"}'))
    ) as client:
        capture = Capture(tmp_path, client)
        result = fetch_markets(capture, [{"condition_id": "0x123", "token_id": "123"}])
        assert result["errors"] == [{"batch": 0, "http_status": 429}]
        assert len(list(tmp_path.glob("*.raw"))) == 1
        assert result["markets"] == []


def test_condition_and_token_identity_are_both_required(tmp_path: Path) -> None:
    body = json.dumps([{"conditionId": "0x123", "clobTokenIds": '["123", "456"]'}]).encode()
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body))
    ) as client:
        result = fetch_markets(
            Capture(tmp_path, client),
            [
                {"condition_id": "0x123", "token_id": "123"},
                {"condition_id": "0x123", "token_id": "999"},
            ],
        )
        assert result["exact_condition_token_trade_rows"] == 1
    assert tokens({"clobTokenIds": "malformed"}) == set()


def test_unrelated_gamma_results_are_not_associated(tmp_path: Path) -> None:
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=[{"conditionId": "wrong"}])
        )
    ) as client:
        result = fetch_markets(
            Capture(tmp_path, client), [{"condition_id": "0x123", "token_id": "123"}]
        )
        assert result["markets"] == []
        assert result["errors"][0]["error_class"] == "ValueError"
