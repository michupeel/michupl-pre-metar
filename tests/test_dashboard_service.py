"""Synthetic dashboard causality/semantics tests; no live captures fabricated."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from premetar.dashboard.app import create_app
from premetar.dashboard.service import (
    DashboardService,
    build_view,
    calibration_at,
    forecast_calibration,
    forecast_view,
    hour_slots,
    market_views,
    qualifying_temperature,
    quote_view,
)

DAY = date(2026, 10, 28)
AT = datetime(2026, 10, 28, 12, tzinfo=UTC)


def metar(hour: int, temp: float, receipt: datetime | None = None, **extra: Any) -> dict[str, Any]:
    event = AT.replace(hour=hour)
    return dict(
        report_identity=f"r{hour}{temp}",
        observation_time_utc=event.isoformat(),
        first_received_utc=(receipt or event + timedelta(minutes=2)).isoformat(),
        temperature_c=temp,
        report_type="METAR",
        correction=False,
        raw_text="METAR EPWA 281200Z 10/08",
        **extra,
    )


def reading(
    receipt: datetime = AT, measured: datetime | None = None, **extra: Any
) -> dict[str, Any]:
    return dict(
        id="obs",
        station_id="s",
        sensor_id="sensor",
        provider="opensensemap",
        temperature_c=10.25,
        observation_time=(measured or receipt - timedelta(seconds=60)).isoformat(),
        first_receive_time=receipt.isoformat(),
        raw_unit="C",
        evidence_class="REALTIME_CAPTURED",
        quality_flags=[],
        **extra,
    )


def raw() -> dict[str, Any]:
    return dict(
        metars=[],
        pws=[],
        stations=[
            dict(
                station_id="s", sensor_id="sensor", station_name="Synthetic station", distance_km=3
            )
        ],
        selections=[],
        forecasts=[],
        markets=[],
        book_samples=[],
        calibrations=[],
    )


@pytest.mark.parametrize(
    ("day", "expected"), [(date(2026, 3, 29), 23), (date(2026, 10, 25), 25), (DAY, 24)]
)
def test_local_hours_keep_dst_fold_and_offset(day: date, expected: int) -> None:
    slots = hour_slots(day)
    assert len(slots) == expected
    assert len({s["start"] for s in slots}) == expected
    if expected == 25:
        assert [s["label"] for s in slots if s["label"].startswith("02:")] == [
            "02:00 +0200",
            "02:00 +0100",
        ]


def test_tmax_complete_hourly_points_not_hourly_maximum() -> None:
    points = [
        dict(valid_time=s["start"], temperature_c=12.4 if i == 14 else 10)
        for i, s in enumerate(hour_slots(DAY))
    ]
    f = dict(
        model="icon_global", first_received=(AT - timedelta(hours=1)).isoformat(), points=points
    )
    view = forecast_view([f], DAY, AT)
    assert view["tmax"]["temperature_c"] == 12.4
    assert view["hourly_maximum"] is None
    assert view["run_time"] is None
    assert not forecast_view([f], DAY, AT - timedelta(hours=2))["points"]
    f["points"] = points[:-1]
    assert forecast_view([f], DAY, AT)["tmax"]["temperature_c"] is None


def test_asof_excludes_delayed_pws_future_metar_and_future_calibration() -> None:
    data = raw()
    data["metars"] = [metar(10, 10), metar(11, 11, AT + timedelta(seconds=1))]
    data["pws"] = [reading(AT + timedelta(seconds=1))]
    data["calibrations"] = [
        dict(
            id=1,
            station_id="s",
            created_at=(AT + timedelta(seconds=1)).isoformat(),
            trained_through=(AT - timedelta(hours=1)).isoformat(),
            parameters={"bias": 2},
        )
    ]
    view = build_view(data, DAY, AT, AT)
    assert view["observed"]["latest"]["temperature_c"] == 10
    assert not view["pws_series"]
    assert view["stations"][0]["bias_c"] is None


def test_two_reports_per_hour_preserved_and_speci_not_counted_in_integer_max() -> None:
    data = raw()
    data["metars"] = [
        metar(10, 10),
        {**metar(10, 11), "observation_time_utc": AT.replace(hour=10, minute=30).isoformat()},
        {**metar(10, 20), "report_type": "SPECI"},
    ]
    view = build_view(data, DAY, AT, AT)
    assert len(view["metars"]) == 3
    assert view["observed"]["max_temperature_c"] == 11
    assert view["observed"]["routine_count"] == 2


def test_correction_changes_current_max_without_erasing_original() -> None:
    data = raw()
    original = metar(10, 11)
    correction = {
        **original,
        "report_identity": "cor",
        "temperature_c": 9,
        "correction": True,
        "first_received_utc": AT.replace(hour=11).isoformat(),
    }
    data["metars"] = [original, correction]
    early = build_view(data, DAY, AT.replace(hour=10, minute=30), AT)
    late = build_view(data, DAY, AT, AT)
    assert early["observed"]["max_temperature_c"] == 11
    assert late["observed"]["max_temperature_c"] == 9
    assert len(late["metars"]) == 2


@pytest.mark.parametrize("problem", ["missing", "future", "stale", "unknown"])
def test_bad_pws_never_enters_analytical_chart(problem: str) -> None:
    data = raw()
    r = reading()
    if problem == "missing":
        r["observation_time"] = None
    if problem == "future":
        r["observation_time"] = (AT + timedelta(seconds=1)).isoformat()
    if problem == "stale":
        r["observation_time"] = (AT - timedelta(hours=1)).isoformat()
    if problem == "unknown":
        r["provider"] = "sensor_community"
    data["pws"] = [r]
    view = build_view(data, DAY, AT, AT)
    assert not view["pws_series"]
    assert view["stations"][0]["status"] != "VALID"


def test_chart_calibration_is_available_at_receipt_not_later_displaytime() -> None:
    data = raw()
    data["pws"] = [reading(receipt=AT - timedelta(minutes=2))]
    data["calibrations"] = [
        dict(
            id=1,
            station_id="s",
            created_at=(AT - timedelta(minutes=1)).isoformat(),
            trained_through=(AT - timedelta(hours=1)).isoformat(),
            parameters={"bias": 2},
        )
    ]
    point = build_view(data, DAY, AT, AT)["pws_series"][0]["points"][0]
    assert point["calibrated_temperature_c"] is None
    assert calibration_at(data["calibrations"], "s", AT, "sensor")["id"] == 1
    assert calibration_at(data["calibrations"], "s", AT, "sensor", 2) is None


def test_historical_selection_uses_recorded_version_only() -> None:
    data = raw()
    data["selections"] = [
        dict(
            station_id="s",
            created_at=(AT - timedelta(hours=2)).isoformat(),
            selected=1,
            reason="old",
        ),
        dict(
            station_id="s",
            created_at=(AT + timedelta(hours=1)).isoformat(),
            selected=0,
            reason="future",
        ),
    ]
    assert build_view(data, DAY, AT, AT)["stations"][0]["selected"]


def test_book_stale_invalid_and_future_never_executable() -> None:
    base = dict(best_bid=".4", best_ask=".5", received_at=AT.isoformat(), status="VALID")
    assert quote_view(base, AT, AT.isoformat())["bid"] == 0.4
    assert not quote_view(base, AT + timedelta(seconds=11), AT.isoformat())["executable"]
    assert not quote_view(base, AT - timedelta(seconds=1), AT.isoformat())["executable"]
    assert quote_view({**base, "best_bid": "bad"}, AT, AT.isoformat())["status"] == "INVALID_BOOK"


def test_exact_binary_mapping_is_required() -> None:
    identity = dict(
        airport="EPWA",
        station="EPWA",
        station_match=True,
        local_date=str(DAY),
        condition_id="c",
        yes="yes",
        no="no",
        slug="fixture",
    )
    data = dict(
        markets=[
            dict(
                identity=identity,
                metadata={"active": True, "acceptingOrders": True},
                received_at=(AT - timedelta(seconds=1)).isoformat(),
            )
        ],
        book_samples=[
            dict(
                identity=identity,
                captured_at=AT.isoformat(),
                books={
                    side: dict(
                        token_id="WRONG",
                        market="c",
                        best_bid=".4",
                        best_ask=".5",
                        status="VALID",
                        received_at=AT.isoformat(),
                    )
                    for side in ("yes", "no")
                },
            )
        ],
    )
    markets, history = market_views(data, DAY, AT)
    assert markets[0]["yes"]["status"] == "UNVERIFIED_MAPPING"
    assert markets[0]["yes"]["bid"] is None
    assert not history


def test_t_group_qualification_not_blind_integer_max() -> None:
    report = {**metar(10, 14), "raw_text": "METAR EPWA 281000Z 14/13 RMK T01390133"}
    assert qualifying_temperature(report) == (13.9, "PRECISE_HOURLY_T_REMARK")
    report["raw_text"] = "METAR EPWA 281000Z M02/M03 RMK T10171022"
    assert qualifying_temperature(report)[0] == -1.7
    report["report_type"] = "SPECI"
    assert qualifying_temperature(report)[0] is None


def test_pending_calibration_does_not_copy_raw_or_leak_later_audit() -> None:
    result = forecast_calibration(
        {
            "forecast_calibration": {
                "published_at": (AT + timedelta(seconds=1)).isoformat(),
                "summary": [{"mae": 0.1}],
            }
        },
        AT,
    )
    assert result["status"] == "CALIBRATION_PENDING"
    assert result["temperature_c"] is None
    assert result["model_results"] == []


def test_empty_or_zero_size_ask_is_not_executable() -> None:
    base = dict(status="VALID", received_at=AT.isoformat(), best_bid=".4")
    assert not quote_view(base, AT, AT.isoformat())["executable"]
    assert not quote_view({**base, "best_ask": ".5", "ask_size": 0}, AT, AT.isoformat())[
        "executable"
    ]
    assert quote_view({**base, "best_ask": ".5", "ask_size": 10}, AT, AT.isoformat())["executable"]


class EmptyReader:
    def load_day(self, day: date) -> dict[str, Any]:
        return raw()


def test_historical_day_defaults_to_that_days_end() -> None:
    service = DashboardService(EmptyReader())
    data = service.day(date(2026, 10, 25))
    assert data["cutoff"].startswith("2026-10-25T22:59:59")
    assert len(data["hours"]) == 25


@pytest.mark.asyncio
async def test_web_api_empty_data_and_validation_readonly() -> None:
    import httpx

    application = create_app(EmptyReader())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/day?date=2026-10-25")
        assert response.status_code == 200
        assert len(response.json()["hours"]) == 25
        assert response.headers["x-frame-options"] == "DENY"
        assert (
            await client.get("/api/asof?date=2026-10-28&at=2026-10-28T11:00:00")
        ).status_code == 422
        assert (await client.get("/api/day?date=bad")).status_code == 422
        assert (await client.post("/api/day")).status_code == 405
        assert (await client.get("/api/day", headers={"host": "evil.example"})).status_code == 403
        assert (
            await client.get("/api/day", headers={"origin": "https://evil.example"})
        ).status_code == 403
