"""Synthetic fixtures only: causal EXP0013 weather projections, no live writes."""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.research.forecast_weather_context import (  # noqa: E402
    build_context,
    context_from_dataset,
    history_from_dataset,
)


def report(event: str, received: str, temperature: int, **kwargs: Any) -> dict[str, Any]:
    return dict(
        report_identity=event + received,
        observation_time_utc=event,
        first_received_utc=received,
        temperature_c=temperature,
        report_type="METAR",
        correction=False,
        startup_censored=False,
        coverage_gap=False,
        _event=datetime.fromisoformat(event),
        _received=datetime.fromisoformat(received),
        _closure=datetime.fromisoformat(received),
        _closure_censored=False,
        _ambiguous_from=None,
        **kwargs,
    )


def data() -> dict[str, Any]:
    previous = report("2026-10-28T11:30:00+00:00", "2026-10-28T11:32:00+00:00", 10)
    target = report("2026-10-28T12:00:00+00:00", "2026-10-28T12:02:00+00:00", 11)
    measurement = datetime(2026, 10, 28, 11, 58, tzinfo=UTC)
    received = measurement + timedelta(seconds=20)
    reading = dict(
        id="reading",
        station_id="station",
        sensor_id="sensor",
        temperature_c=11.6,
        observation_time=measurement.isoformat(),
        first_receive_time=received.isoformat(),
        evidence_class="REALTIME_CAPTURED",
        provider="opensensemap",
        raw_unit="C",
        raw_temperature=11.6,
        quality_flags=[],
        _event=measurement,
        _received=received,
        timestamp_provenance="SENSOR_MEASUREMENT_TIME",
        timestamp_semantics_verified=True,
        qc_status="VALID",
        age_seconds=20,
        startup_censored=False,
        coverage_gap=False,
    )
    location = dict(latitude=52.165, longitude=20.967, exposure="outdoor", mobile=False)
    sensor = dict(
        station_id="station",
        provider="opensensemap",
        distance_km=1,
        conflicts={},
        airport_metadata=location,
        metadata=[location],
        metadata_times=[datetime(2026, 10, 27, tzinfo=UTC)],
        readings=[reading],
        event_times=[measurement],
        pairs=[
            dict(
                _event=datetime(2026, 10, 28, 6, tzinfo=UTC) + timedelta(minutes=30 * i),
                _received=datetime(2026, 10, 28, 6, 2, tzinfo=UTC) + timedelta(minutes=30 * i),
                offset_midpoint_c=1,
                report_identity=str(i),
            )
            for i in range(12)
        ],
    )
    result = {
        airport: dict(reports=[], references=[], sensors={}, reference_exclusions={})
        for airport in ("EDDM", "EHAM", "EPWA", "EGLL")
    }
    result["EPWA"] = dict(
        reports=[previous, target],
        references=[previous, target],
        sensors={"sensor": sensor},
        reference_exclusions={},
    )
    return result


def test_context_has_no_future_reference_and_calibrates_causally() -> None:
    result = context_from_dataset(data(), datetime(2026, 10, 28, 11, 59, tzinfo=UTC))["EPWA"]
    assert result["latest_metar"]["temperature_c"] == 10
    reading = result["pws"][0]
    assert reading["calibration_n"] == 12
    assert reading["offset_c"] == 1
    assert reading["predicted_metar_integer"] == 11
    assert reading["expected_change"] == 1
    assert reading["prediction_eligible"] is True
    assert reading["distance_to_integer_boundary"] == pytest.approx(0.1)
    assert result["received_daily_metar_max"] == 10
    json.dumps(result, allow_nan=False)


def test_delayed_reading_not_available_before_receipt() -> None:
    dataset = data()
    dataset["EPWA"]["sensors"]["sensor"]["readings"][0]["_received"] += timedelta(minutes=2)
    result = context_from_dataset(dataset, datetime(2026, 10, 28, 11, 59, tzinfo=UTC))
    assert result["EPWA"]["pws"] == []


def test_stale_reading_excluded_not_forward_filled() -> None:
    result = context_from_dataset(data(), datetime(2026, 10, 28, 12, 4, tzinfo=UTC))
    assert result["EPWA"]["pws"] == []


def test_early_target_closes_opportunity() -> None:
    dataset = data()
    dataset["EPWA"]["references"][1]["_closure"] = datetime(2026, 10, 28, 11, 58, tzinfo=UTC)
    result = context_from_dataset(dataset, datetime(2026, 10, 28, 11, 59, tzinfo=UTC))["EPWA"]
    assert result["next_target_already_received"] is True
    assert result["pws"][0]["prediction_eligible"] is False
    assert result["pws"][0]["status"] == "TARGET_ALREADY_RECEIVED"


def test_insufficient_history_does_not_substitute_raw_as_calibrated() -> None:
    dataset = data()
    dataset["EPWA"]["sensors"]["sensor"]["pairs"].pop()
    result = context_from_dataset(dataset, datetime(2026, 10, 28, 11, 59, tzinfo=UTC))["EPWA"]
    assert result["pws"][0]["predicted_metar_integer"] is None
    assert result["pws"][0]["status"] == "INSUFFICIENT_CALIBRATION_HISTORY"


def test_matched_history_preserves_baseline_and_exploratory_label() -> None:
    result = history_from_dataset(data(), datetime(2026, 10, 28, 13, tzinfo=UTC))["EPWA"]
    ranking = result["sensor_ranking"][0]
    assert ranking["counts"]["eligible_cycles"] == 1
    assert ranking["counts"]["calibrated_correct"] == 1
    assert ranking["counts"]["persistence_correct_same_cycles"] == 0
    assert ranking["net_improvement"] == 1
    assert result["matched_examples"][0]["evidence_class"] == "RETROSPECTIVE_AS_OF_RECONSTRUCTION"
    assert result["matched_examples"][0]["lead_seconds"] == 180


def test_history_early_target_excluded() -> None:
    dataset = data()
    dataset["EPWA"]["references"][1]["_closure"] = datetime(2026, 10, 28, 11, 58, tzinfo=UTC)
    result = history_from_dataset(dataset, datetime(2026, 10, 28, 13, tzinfo=UTC))["EPWA"]
    assert result["sensor_ranking"][0]["counts"]["EARLY_REFERENCE_CLOSED_WINDOW"] == 1
    assert result["matched_examples"] == []


def test_history_preserves_speci_and_corrections_without_counting_extra_cycles() -> None:
    dataset = data()
    dataset["EPWA"]["reports"].append(
        {**dataset["EPWA"]["reports"][0], "correction": True, "report_type": "SPECI"}
    )
    result = history_from_dataset(dataset, datetime(2026, 10, 28, 13, tzinfo=UTC))["EPWA"]
    assert len(result["reports"]) == 3
    assert result["independent_routine_cycles"] == 2


def test_fallback_day_has_25_hours_and_results_are_serializable() -> None:
    dataset = {airport: {**items, "sensors": {}} for airport, items in data().items()}
    result = history_from_dataset(dataset, datetime(2026, 10, 25, 12, tzinfo=UTC))["EPWA"]
    start = datetime.fromisoformat(result["day_start"])
    end = datetime.fromisoformat(result["day_end_exclusive"])
    assert end - start == timedelta(hours=25)
    json.dumps(result)


def test_naive_decision_rejected_before_any_database_access(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="aware"):
        build_context(tmp_path / "missing.sqlite3", datetime(2026, 10, 28))


def test_missing_snapshot_cannot_be_created(tmp_path: Path) -> None:
    snapshot = tmp_path / "missing.sqlite3"
    with pytest.raises(Exception, match="unable to open"):
        build_context(snapshot, datetime(2026, 10, 28, tzinfo=UTC))
    assert not snapshot.exists()
