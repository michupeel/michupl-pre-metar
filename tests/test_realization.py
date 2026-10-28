"""Synthetic EXP0014 rules and causal clocks; these are not observed weather."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from premetar.pws.daily_time import local_day_bounds
from premetar.research.realization import VERSION, evaluate_realization, parse_metar_conditions

AT = datetime(2026, 10, 28, 11, 5, tzinfo=UTC)


def forecast(received: datetime | None = None, **extra: Any) -> dict[str, Any]:
    start, end = local_day_bounds(AT.date(), "Europe/Warsaw")
    points = []
    time = start
    while time < end:
        points.append(
            dict(
                valid_time=time.isoformat(),
                temperature_c=14 - abs(time.hour - 12) * 2,
                cloud_cover_low=10,
            )
        )
        time += timedelta(hours=1)
    return dict(
        snapshot_id="f1",
        model="icon_global",
        first_received=(received or AT.replace(hour=9, minute=0)).isoformat(),
        points=points,
        **extra,
    )


def report(minutes_ago: int, value: int = 7, **extra: Any) -> dict[str, Any]:
    event = AT - timedelta(minutes=minutes_ago + 5)
    return dict(
        report_identity=f"r{event.isoformat()}",
        observation_time_utc=event.isoformat(),
        first_received_utc=(event + timedelta(minutes=2)).isoformat(),
        temperature_c=value,
        report_type="METAR",
        raw_text=f"METAR EPWA 281100Z 25005KT 9999 OVC012 {value:02d}/06 Q1024",
        **extra,
    )


def three() -> list[dict[str, Any]]:
    return [report(60), report(30), report(0)]


def test_remaining_warming_does_not_reuse_a_past_daily_peak() -> None:
    at = AT + timedelta(hours=3)
    f = forecast(at - timedelta(hours=2))
    event = at.replace(minute=0)
    row = dict(
        report(0),
        observation_time_utc=event.isoformat(),
        first_received_utc=(event + timedelta(minutes=2)).isoformat(),
    )
    result = evaluate_realization([row], [f], [], at)
    assert result["evidence"]["hours_to_tmax"] < 0
    assert result["evidence"]["remaining_warming_c"] == 0


@pytest.mark.parametrize(
    "amount,oktas", [("FEW", [1, 2]), ("SCT", [3, 4]), ("BKN", [5, 7]), ("OVC", [8, 8])]
)
def test_cloud_categories_are_not_exact_percent(amount: str, oktas: list[int]) -> None:
    value = parse_metar_conditions(f"METAR EPWA 281100Z VRB02KT 9999 {amount}020 10/08")
    assert value["cloud_layers"][0] == dict(
        amount=amount, base_ft=2000, amount_okta_range=oktas, kind=None
    )
    assert "NO_EXACT_AREA" in value["cloud_uncertainty"]


@pytest.mark.parametrize("code", ["CAVOK", "NSC", "NCD"])
def test_clear_codes_do_not_mean_cloudless(code: str) -> None:
    value = parse_metar_conditions(f"METAR EPWA 281100Z VRB02KT {code} 10/08")
    assert value["cloud_status"] == "REPORTED"
    assert "NOT_CLOUDLESS" in value["cloud_uncertainty"]
    assert value["cloud_layers"] == []


def test_parser_weather_wind_precipitation_negative_temperature() -> None:
    value = parse_metar_conditions(
        "METAR EPWA 281100Z 25012G20KT 4000 -FZRA BKN005 M02/M04 Q1000 TEMPO OVC001"
    )
    assert value["temperature_c"] == -2
    assert value["dew_point_c"] == -4
    assert value["wind"]["gust"] == 20
    assert value["visibility"]["value"] == 4000
    assert value["significant_weather"] == ["-FZRA"]
    assert value["precipitation_indicated"]
    assert len(value["cloud_layers"]) == 1


@pytest.mark.parametrize(
    "clouds,status",
    [
        ("", "MISSING"),
        ("OVCXYY", "MALFORMED_OR_AMBIGUOUS"),
        ("CAVOK OVC010", "MALFORMED_OR_AMBIGUOUS"),
    ],
)
def test_missing_malformed_or_conflicting_clouds(clouds: str, status: str) -> None:
    assert parse_metar_conditions(f"METAR EPWA 281100Z 10/08 {clouds}")["cloud_status"] == status


def test_persistent_cold_risk_has_numeric_evidence_and_no_probability() -> None:
    result = evaluate_realization(three(), [forecast()], [], AT)
    assert result["state"] == "SIGNIFICANTLY COLDER"
    assert result["confidence"] == "FORECAST HIGH RISK"
    assert result["trend"] == "WARMING SLOWER"
    assert result["cloud"]["status"] == "UNEXPECTED OVERCAST"
    assert result["weather_gate"]
    assert result["validated_probability"] is None
    assert result["adaptive_tmax"]["status"] == "EXPERIMENTAL_NOT_VALIDATED"
    assert not result["adaptive_tmax"]["validated"]
    assert result["evidence"]["rates"]["actual_c_per_hour"] == 0
    assert result["evidence"]["rates"]["forecast_c_per_hour"] == 2


def test_half_hour_is_explicit_interpolation_and_quantized_error() -> None:
    result = evaluate_realization([report(30, 11)], [forecast()], [], AT)
    point = result["latest_metar"]
    assert point["forecast_temperature_c"] == 11
    assert point["alignment"] == "LINEAR_INTERPOLATION_NOT_DIRECT_MODEL_OUTPUT"
    assert point["signed_interval_residual_c"] == 0
    assert point["metar_interval_c"] == [10.5, 11.5]
    assert result["confidence"] == "INSUFFICIENT DATA"


def test_single_noisy_report_cannot_produce_confidence_or_adaptive_tmax() -> None:
    result = evaluate_realization([report(0, 2)], [forecast()], [], AT)
    assert result["confidence"] == "INSUFFICIENT DATA"
    assert result["adaptive_tmax"]["temperature_c"] is None
    assert not result["weather_gate"]


def test_forecast_must_precede_nominal_not_only_receipt() -> None:
    event = AT.replace(minute=0)
    result = evaluate_realization([report(0)], [forecast(event + timedelta(seconds=1))], [], AT)
    assert result["state"] == "INSUFFICIENT DATA"
    assert result["history"] == []


def test_equal_nominal_forecast_receipt_is_not_prior() -> None:
    result = evaluate_realization([report(0)], [forecast(AT.replace(minute=0))], [], AT)
    assert result["history"] == []


def test_future_report_and_future_receipt_excluded_even_when_nominal_early() -> None:
    future = {**report(0), "observation_time_utc": (AT + timedelta(minutes=1)).isoformat()}
    delayed = {**report(0), "first_received_utc": (AT + timedelta(seconds=1)).isoformat()}
    assert evaluate_realization([future, delayed], [forecast()], [], AT)["history"] == []


def test_correction_is_one_cycle_and_unavailable_correction_cannot_leak() -> None:
    correction = {
        **report(0, 20),
        "report_identity": "cor",
        "correction": True,
        "first_received_utc": (AT + timedelta(minutes=1)).isoformat(),
    }
    initial = report(0, 7)
    assert (
        evaluate_realization([initial, correction], [forecast()], [], AT)["latest_metar"][
            "temperature_c"
        ]
        == 7
    )
    later = evaluate_realization([initial, correction], [forecast()], [], AT + timedelta(minutes=2))
    assert later["latest_metar"]["temperature_c"] == 20
    assert len(later["history"]) == 1


def test_forecast_revision_is_not_observed_tendency() -> None:
    earlier = forecast()
    revision = {**forecast(AT.replace(hour=10, minute=15)), "snapshot_id": "f2"}
    revision["points"] = [
        {**p, "temperature_c": p["temperature_c"] + 10} for p in revision["points"]
    ]
    result = evaluate_realization(three(), [earlier, revision], [], AT)
    rates = result["evidence"]["rates"]
    assert rates["actual_c_per_hour"] == 0
    assert rates["forecast_c_per_hour"] == 2  # Frozen f1, not f2-f1 jump.
    assert rates["forecasts_may_differ"]
    assert rates["trajectory_forecast_received"] == earlier["first_received"]


def test_future_forecast_does_not_change_asof_view() -> None:
    later = forecast(AT + timedelta(seconds=1))
    later["points"] = []
    a = evaluate_realization(three(), [forecast()], [], AT)
    b = evaluate_realization(three(), [forecast(), later], [], AT)
    assert a == b


def test_stale_data_and_gapped_history_do_not_activate_gate() -> None:
    result = evaluate_realization(three(), [forecast()], [], AT + timedelta(hours=2))
    assert result["state"] == "STALE DATA"
    assert result["confidence"] == "INSUFFICIENT DATA"
    assert not result["weather_gate"]
    result = evaluate_realization(
        [report(180), report(30), report(0)], [forecast(AT - timedelta(hours=5))], [], AT
    )
    assert result["confidence"] == "INSUFFICIENT DATA"


def test_speci_excluded() -> None:
    result = evaluate_realization([{**report(0), "report_type": "SPECI"}], [forecast()], [], AT)
    assert result["history"] == []


def test_no_interpolation_over_missing_hour() -> None:
    value = forecast()
    value["points"] = [point for point in value["points"] if "T11:00" not in point["valid_time"]]
    assert evaluate_realization([report(30)], [value], [], AT)["history"] == []


def test_hysteresis_only_accepts_known_prior_version_and_time() -> None:
    row = report(0, 11)
    f = forecast()
    # At11 forecast12.0 -> signed interval residual-0.5; previous colder near .75.
    f["points"] = [{**p, "temperature_c": 12.2} for p in f["points"]]
    prior = dict(
        state="COLDER", rule_version=VERSION, created_at=(AT - timedelta(seconds=1)).isoformat()
    )
    assert evaluate_realization([row], [f], [], AT, prior)["state"] == "COLDER"
    prior["created_at"] = (AT + timedelta(seconds=1)).isoformat()
    assert evaluate_realization([row], [f], [], AT, prior)["state"] == "SLIGHTLY COLDER"


def test_dst_daily_peak_requires25_distinct_utc_hourly_points() -> None:
    at = datetime(2026, 10, 25, 10, 5, tzinfo=UTC)
    start, end = local_day_bounds(date(2026, 10, 25), "Europe/Warsaw")
    points = [
        dict(valid_time=(start + timedelta(hours=i)).isoformat(), temperature_c=12)
        for i in range(25)
    ]
    f = dict(
        snapshot_id="dst",
        model="icon_global",
        first_received=(at - timedelta(hours=2)).isoformat(),
        points=points,
    )
    row = {
        **report(0),
        "observation_time_utc": at.replace(minute=0).isoformat(),
        "first_received_utc": at.replace(minute=2).isoformat(),
    }
    result = evaluate_realization([row], [f], [], at)
    assert result["forecast_tmax"]["hours"] == 25
    assert result["forecast_tmax"]["complete"]
    assert end - start == timedelta(hours=25)


def test_naive_decision_rejected_empty_data_safe() -> None:
    with pytest.raises(ValueError, match="Timezone-aware"):
        evaluate_realization([], [], [], AT.replace(tzinfo=None))
    result = evaluate_realization([], [], [], AT)
    assert result["state"] == "INSUFFICIENT DATA"
    assert result["confidence"] == "INSUFFICIENT DATA"
    assert result["adaptive_tmax"]["temperature_c"] is None


def test_observed_maximum_does_not_require_prior_forecast() -> None:
    value = evaluate_realization([report(0, 15)], [], [], AT)
    assert value["observed_metar_maximum_c"] == 15
    assert value["forecast_at_metar"] is None
    assert value["confidence"] == "INSUFFICIENT DATA"


def test_unaligned_latest_report_does_not_reuse_old_classification() -> None:
    f = forecast()
    f["points"] = [p for p in f["points"] if "T11:00" not in p["valid_time"]]
    result = evaluate_realization([report(60), report(0)], [f], [], AT)
    assert len(result["history"]) == 1
    assert result["state"] == "INSUFFICIENT DATA"
    assert result["evidence"]["latest_reference_alignment_missing"]


def test_three_cycles_are_still_not_three_independent_days() -> None:
    result = evaluate_realization(three(), [forecast()], [], AT)
    assert result["evidence"]["independent_recent_cycles"] == 3
    assert result["empirical_predictive_confidence"] == "NOT_VALIDATED"


def test_cloud_disagreement_not_inferred_without_model_low_cloud() -> None:
    f = forecast()
    f["points"] = [{k: v for k, v in p.items() if k != "cloud_cover_low"} for p in f["points"]]
    result = evaluate_realization(three(), [f], [], AT)
    assert result["cloud"]["status"] == "INSUFFICIENT DATA"
    assert not result["weather_gate"]
