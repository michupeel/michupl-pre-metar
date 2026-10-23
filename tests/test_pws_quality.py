import math
from datetime import UTC, datetime, timedelta

import pytest

from premetar.model import icao_round_temperature
from premetar.pws.analysis import correction, interval_residual, walk_forward
from premetar.pws.models import QCConfig, Sensor, Station
from premetar.pws.providers import reading
from premetar.pws.quality import (
    assess,
    eligible,
    peer_comparison,
    physical_flags,
    score,
    solar_suspicion,
)
from premetar.pws.temporal import temporal_metrics

NOW = datetime(2026, 11, 1, tzinfo=UTC)
CONFIG = QCConfig()


def station(key="x", lat=52, lon=4, **kwargs):
    return Station(
        provider="opensensemap",
        provider_station_id=key,
        latitude=lat,
        longitude=lon,
        sensors=[Sensor(provider_sensor_id="t", unit="°C")],
        **kwargs,
    )


def row(temp=18, event=None, receive=None, **kwargs):
    return {
        "temperature_c": temp,
        "relative_humidity": 60,
        "quality_flags": [],
        "observation_time": (event or NOW - timedelta(seconds=60)).isoformat(),
        "source_publish_time": None,
        "first_receive_time": (receive or NOW).isoformat(),
        "evidence_class": "REALTIME_CAPTURED",
        "provider_sensor_id": "t",
        **kwargs,
    }


def test_temporal_sort_dedup_and_age():
    samples = [(NOW - timedelta(minutes=n), 18 + n * 0.1) for n in [0, 5, 10, 5]]
    metrics = temporal_metrics(samples, NOW, 300)
    assert metrics["sample_count"] == 3
    assert metrics["observation_age"] == 0
    assert metrics["median_update_interval"] == 300
    assert metrics["availability"] == 1
    assert metrics["missing_intervals"] == 0


def test_stale_single_and_future():
    assert "STALE_DATA" in temporal_metrics([(NOW - timedelta(hours=2), 18)], NOW)["flags"]
    assert "CLOCK_ANOMALY" in temporal_metrics([(NOW + timedelta(seconds=1), 18)], NOW)["flags"]
    assert temporal_metrics([], NOW)["availability"] is None


def test_stuck_requires_duration_and_corroboration():
    short = [(NOW - timedelta(minutes=i), 18) for i in range(10)]
    assert "STUCK_SENSOR" not in temporal_metrics(short, NOW, peer_range_c=3)["flags"]
    long = [(NOW - timedelta(hours=i), 18) for i in range(8)]
    assert "STUCK_SUSPECT" in temporal_metrics(long, NOW)["flags"]
    assert "STUCK_SENSOR" in temporal_metrics(long, NOW, peer_range_c=3)["flags"]
    assert "STUCK_SENSOR" not in temporal_metrics(long, NOW, peer_range_c=0.5)["flags"]


def test_jumps_gaps_and_conflicts():
    samples = [
        (NOW - timedelta(minutes=30), 18),
        (NOW - timedelta(minutes=1), 18),
        (NOW, 21),
        (NOW, 22),
    ]
    metrics = temporal_metrics(samples, NOW, 300)
    assert {"TEMPERATURE_SPIKE", "MISSING_INTERVALS", "CONFLICTING_DUPLICATE"} <= set(
        metrics["flags"]
    )
    assert metrics["longest_gap"] == 1740


@pytest.mark.parametrize(
    "samples,now",
    [([(NOW, math.nan)], NOW), ([], datetime(2026, 1, 1)), ([(datetime(2026, 1, 1), 18)], NOW)],
)
def test_temporal_invalid(samples, now):
    with pytest.raises(ValueError):
        temporal_metrics(samples, now)


@pytest.mark.parametrize(
    "value,flag",
    [
        (100, "IMPOSSIBLE_TEMPERATURE"),
        (math.inf, "INVALID_TEMPERATURE"),
        (math.nan, "INVALID_TEMPERATURE"),
    ],
)
def test_physical(value, flag):
    assert flag in physical_flags(row(value), NOW, CONFIG)


def test_extremes_and_humidity():
    assert not physical_flags(row(-85), NOW, CONFIG)
    assert "INVALID_HUMIDITY" in physical_flags(row(relative_humidity=101), NOW, CONFIG)
    assert "INDOOR_SENSOR" in assess(station(exposure="indoor"), [], NOW, CONFIG)["flags"]
    assert assess(station(), [], NOW, CONFIG)["metadata_status"] == "UNKNOWN_METADATA"


def test_time_availability_month_rollover_and_timezone():
    assert eligible(row(event=NOW - timedelta(seconds=10)), NOW, CONFIG)
    assert not eligible(row(receive=NOW + timedelta(seconds=1)), NOW, CONFIG)
    assert not eligible(row(event=NOW + timedelta(seconds=1)), NOW, CONFIG)
    assert not eligible(row(evidence_class="HISTORICAL_EVENT_ONLY"), NOW, CONFIG)
    assert not eligible(row(event=NOW - timedelta(hours=2)), NOW, CONFIG)
    same = NOW.astimezone(__import__("datetime").timezone(timedelta(hours=2)))
    assert eligible(row(), same, CONFIG)


def test_unit_normalization_and_missing_clocks():
    assert reading("t", 68, "°F", None).temperature_c == 20
    assert reading("t", 293.15, "K", None).temperature_c == pytest.approx(20)
    r = reading("t", 18, "bananas", None)
    assert r.temperature_c is None and "UNKNOWN_UNIT" in r.quality_flags
    assert r.observation_time is None and r.source_publish_time is None
    assert "INVALID_TIMESTAMP" in reading("t", 18, "°C", "not-a-time").quality_flags
    assert "INVALID_TEMPERATURE" in reading("t", "nan", "°C", None).quality_flags


def test_spatial_microclimate_is_not_exclusion():
    peers = [(station(str(i), 52 + 0.005 * i, 4 + 0.005 * i), row(18)) for i in range(1, 5)]
    result = peer_comparison(station(), 23, NOW, peers, CONFIG)
    assert result["difference_c"] == 5
    assert "MICROCLIMATE_OR_SENSOR_BIAS" in result["flags"]
    assert eligible(row(23), NOW, CONFIG)
    assert peer_comparison(station(), 23, NOW, peers[:1], CONFIG)["difference_c"] is None


def test_solar_bias_requires_day_night_and_days():
    s = station(lat=52, lon=0)
    diffs = [
        (datetime(2026, 6, d, h, m, tzinfo=UTC), 4 if h == 12 else 0)
        for d in [1, 2, 3]
        for h in [0, 12]
        for m in range(10)
    ]
    assert solar_suspicion(s, diffs)["flags"] == ["SOLAR_HEATING_SUSPECT"]
    assert not solar_suspicion(s, [(t, 3) for t, _ in diffs])["flags"]
    assert not solar_suspicion(s, diffs[:4])["flags"]


@pytest.mark.parametrize(
    "value,integer", [(18.5, 19), (-18.5, -18), (-0.5, 0), (0.5, 1), (-0.51, -1)]
)
def test_interval_rounding(value, integer):
    assert icao_round_temperature(value) == integer
    assert interval_residual(value, integer) == 0


def test_quantization_not_exact_bias():
    assert interval_residual(18.4, 18) == 0
    assert interval_residual(19, 18) == 0.5
    assert interval_residual(17, 18) == -0.5
    assert interval_residual(18.5, 18) == 0  # infimum; integer mismatch still detected
    assert icao_round_temperature(18.5) != 18


def pairs():
    return [
        {
            "target_time": (NOW - timedelta(hours=30 - i)).isoformat(),
            "decision_time": (NOW - timedelta(hours=30 - i, minutes=10)).isoformat(),
            "label_available_at": (
                NOW - timedelta(hours=30 - i) + timedelta(minutes=2)
            ).isoformat(),
            "temperature_c": 20,
            "actual_integer": 18,
            "baseline_integer": 18,
        }
        for i in range(25)
    ]


def test_walk_forward_no_future_or_delayed_label():
    data = pairs()
    config = QCConfig(calibration_minimum=5)
    result = walk_forward(data, config)
    assert result["sample_count"] == 20
    assert result["raw_integer_match_rate"] == 0
    assert result["rows"][0]["bias"] == 1.5
    before = correction(data, NOW, config)
    data.append(
        {**data[-1], "target_time": (NOW + timedelta(hours=1)).isoformat(), "actual_integer": -99}
    )
    assert correction(data, NOW, config) == before
    for p in data:
        p["label_available_at"] = (NOW + timedelta(hours=1)).isoformat()
    assert correction(data, NOW, config) is None


def test_score_missing_evidence_unverified():
    components = dict.fromkeys(CONFIG.weights, 90)
    assert score(components, 5, 10, [], CONFIG)["status"] == "UNVERIFIED"
    assert score({**components, "predictive": None}, 200, 10, [], CONFIG)["score"] is None
    assert score(components, 200, 10, [], CONFIG)["status"] == "CANDIDATE"
    assert score(components, 200, 10, ["INDOOR_SENSOR"], CONFIG)["status"] == "UNRELIABLE"
    with pytest.raises(ValueError):
        score(components, 200, 10, [], QCConfig(weights={"x": 1}))
