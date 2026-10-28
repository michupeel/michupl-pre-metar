"""Synthetic offline report fixtures; no real book, forecast or fill is invented."""

import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.research import forecast_integrated_report as module  # noqa: E402

START = datetime(2026, 10, 28, 12, tzinfo=UTC)


def test_repricing_identity_never_uses_future_watchlist() -> None:
    event = dict(
        kind="SIGNAL", received_at=START.isoformat(), payload={"inputs": {"token_id": "token"}}
    )
    coverage = dict(
        kind="COVERAGE",
        received_at=(START + timedelta(seconds=1)).isoformat(),
        payload={"identities": [dict(yes="token", no="other", airport="EPWA", station_match=True)]},
    )
    assert module.signal_identity(event, [coverage, event])["airport"] == "UNKNOWN"
    coverage["received_at"] = (START - timedelta(seconds=1)).isoformat()
    assert module.signal_identity(event, [coverage, event])["airport"] == "EPWA"


def test_reaction_window_separates_before_receipt_and_wrong_contract_day() -> None:
    identity = dict(
        yes="token",
        no="other",
        airport="EPWA",
        station_match=True,
        condition_id="c",
        local_date="2026-10-28",
    )
    coverage = dict(
        kind="COVERAGE",
        received_at=(START - timedelta(minutes=1)).isoformat(),
        payload={"identities": [identity]},
    )
    event = dict(
        kind="SIGNAL",
        received_at=START.isoformat(),
        payload=dict(
            version="EXP0013-v1.1",
            kind="ORDERBOOK_REPRICING_DETECTED",
            created_at=START.isoformat(),
            inputs=dict(token_id="token", before={"midpoint": ".4"}, after={"midpoint": ".5"}),
        ),
    )
    history = {
        "EPWA": {
            "reports": [
                dict(
                    observation_time_utc=START.isoformat(),
                    first_received_utc=(START + timedelta(seconds=60)).isoformat(),
                    report_identity="r",
                    report_type="METAR",
                    correction=False,
                )
            ]
        }
    }
    result = module.reaction_timeline([coverage, event], history)
    assert result[0]["seconds_relative_to_metar_receipt"] == -60
    assert result[0]["direction"] == "BEFORE_OUR_RECEIPT"
    identity["local_date"] = "2026-10-29"
    assert not module.reaction_timeline([coverage, event], history)


def sample(at: datetime, midpoint: str = "0.5", connection: str = "epoch") -> dict[str, Any]:
    identity = dict(
        airport="EPWA",
        station="EPWA",
        station_match=True,
        yes="1",
        no="2",
        condition_id="condition",
        local_date="2026-10-28",
        slug="fixture-only",
    )
    return dict(
        identity=identity,
        captured_at=at.isoformat(),
        books={
            side: dict(
                status="VALID",
                midpoint=midpoint,
                token_id=token,
                market="condition",
                connection_id=connection,
                received_at=at.isoformat(),
            )
            for side, token in (("yes", "1"), ("no", "2"))
        },
    )


def event(kind: str, payload: dict[str, Any], received: datetime = START) -> dict[str, Any]:
    return dict(kind=kind, payload=payload, received_at=received.isoformat())


def bin_events(start: datetime, first: str = "0.5", last: str = "0.6") -> list[dict[str, Any]]:
    return [
        event(
            "BOOK_SAMPLE",
            sample(start + timedelta(seconds=seconds), last if seconds == 290 else first),
        )
        for seconds in range(0, 300, 10)
    ]


def window(start: datetime, created: datetime) -> dict[str, Any]:
    return event(
        "WINDOW",
        dict(
            airport="EPWA",
            kind="FORECAST_TRANSITION",
            start=start.isoformat(),
            end=(start + timedelta(minutes=5)).isoformat(),
            created_at=created.isoformat(),
            forecast_received=created.isoformat(),
        ),
        created,
    )


def test_matched_bins_use_same_token_day_without_reusing_controls() -> None:
    events = (
        [window(START, START - timedelta(minutes=1))]
        + bin_events(START)
        + bin_events(START + timedelta(minutes=5), last="0.51")
    )
    result = module.window_bins(events)
    assert len(result["bins"]) == 4
    assert result["matched_token_bin_pairs"] == 2
    assert result["matched_condition_bin_pairs"] == 1
    assert result["matched_market_days"] == 1
    assert result["status"] == "INSUFFICIENT_DATA"
    assert result["mean_matched_difference"] == pytest.approx(0.09)


def test_late_declared_window_never_becomes_prospective_window() -> None:
    result = module.window_bins([window(START, START)] + bin_events(START))
    assert all(row["period"] == "CONTROL" for row in result["bins"])
    assert result["matched"] == []


@pytest.mark.parametrize("failure", ["stale", "wrong_station", "wrong_day", "wrong_token", "nan"])
def test_invalid_pair_is_not_a_valid_execution_opportunity(failure: str) -> None:
    row = sample(START)
    if failure == "stale":
        row["books"]["yes"]["received_at"] = (START - timedelta(seconds=11)).isoformat()
    elif failure == "wrong_station":
        row["identity"]["station"] = "EGLC"
    elif failure == "wrong_day":
        row["identity"]["local_date"] = "2026-10-29"
    elif failure == "wrong_token":
        row["books"]["no"]["token_id"] = "1"
    else:
        row["books"]["yes"]["midpoint"] = "NaN"
    assert not module.valid_pair(row)


def test_reconnect_and_missing_samples_invalidate_bin() -> None:
    events = bin_events(START)
    events[-1]["payload"]["books"]["yes"]["connection_id"] = "another"
    assert module.window_bins(events)["bins"] == []
    events = bin_events(START)
    del events[10:15]
    result = module.window_bins(events)
    assert result["excluded_bins"] == {"DISCONTINUOUS_CAPTURE": 1}


def test_missing_endpoint_cannot_be_forward_filled() -> None:
    assert module.window_bins(bin_events(START)[2:])["excluded_bins"] == {
        "INCOMPLETE_BIN_ENDPOINTS": 1
    }


def test_forecast_cannot_be_backdated_or_used_before_receipt() -> None:
    forecast = dict(
        airport="EPWA",
        first_received=(START + timedelta(minutes=5)).isoformat(),
        points=[
            dict(valid_time=START.isoformat(), temperature_c=10),
            dict(valid_time=(START + timedelta(hours=1)).isoformat(), temperature_c=11),
        ],
    )
    assert module.causal_forecast([forecast], "EPWA", START, START) is None
    assert module.causal_forecast([forecast], "EPWA", START, START + timedelta(minutes=10)) is None
    point = module.causal_forecast(
        [forecast], "EPWA", START + timedelta(hours=1), START + timedelta(minutes=10)
    )
    assert point and point["temperature_c"] == 11


def test_unknown_research_path_not_created(tmp_path: Path) -> None:
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(sqlite3.OperationalError):
        module.read_research(missing)
    assert not missing.exists()


def confirmation(version: str = "EXP0013-v1.1", count: int = 12) -> dict[str, Any]:
    return dict(
        id=42,
        **event(
            "SIGNAL",
            dict(
                version=version,
                kind="PWS_CONFIRMS_UPWARD_TRANSITION",
                created_at=START.isoformat(),
                inputs=dict(
                    airport="EPWA",
                    target=(START + timedelta(minutes=30)).isoformat(),
                    sensor_id="sensor",
                    calibrated_temperature_c=11.7,
                    predicted_metar_integer=12,
                    calibration=dict(
                        calibration_n=count,
                        calibration_reference_ids=[str(n) for n in range(count)],
                        history_available_by=(START - timedelta(minutes=2)).isoformat(),
                    ),
                    reading=dict(
                        observation_time=(START - timedelta(seconds=30)).isoformat(),
                        first_receive_time=(START - timedelta(seconds=10)).isoformat(),
                    ),
                ),
            ),
        ),
    )


def test_prototype_signal_is_retained_but_excluded_from_analysis() -> None:
    prototype, current = confirmation("EXP0013-v1"), confirmation()
    events = [prototype, current]
    assert len(events) == 2
    assert module.analysis_signals(events) == [current]
    assert module.live_calibrated_signals(events) == [current]


def test_live_cal2_requires_actual_minimum_independent_history() -> None:
    insufficient = confirmation(count=11)
    duplicates = confirmation()
    duplicates["payload"]["inputs"]["calibration"]["calibration_reference_ids"] = ["same"] * 12
    context_only = confirmation()
    context_only["payload"]["kind"] = "PWS_MEASUREMENT_RECEIVED"
    assert module.live_calibrated_signals([insufficient, duplicates, context_only]) == []


def test_outcomes_exclude_after_receipt_and_do_not_count_disagreement_twice() -> None:
    confirmed = confirmation()
    duplicate = confirmation()
    duplicate["payload"]["kind"] = "PWS_DISAGREES_WITH_FORECAST"
    result = dict(
        signal_id=42,
        correction=False,
        report_first_received=(START + timedelta(minutes=32)).isoformat(),
        target_first_received=(START + timedelta(minutes=32)).isoformat(),
        prospective_valid=True,
        exact_match=True,
        persistence_match=False,
        experiment="EXP_A",
    )
    settled = event("OUTCOME", result)
    summary = module.outcome_summary([confirmed, duplicate, settled])
    assert summary["validated_cal2_signals"] == 1
    assert summary["independent_target_cycles"] == 1
    assert summary["counts"]["incremental_correct"] == 1
    result["target_first_received"] = START.isoformat()
    summary = module.outcome_summary([confirmed, settled])
    assert summary["counts"]["excluded_after_first_receipt"] == 1
    assert "matched_initial_outcomes" not in summary["counts"]


def test_report_empty_weather_real_db_schema_and_immutable_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    research = tmp_path / "research.sqlite3"
    conn = sqlite3.connect(research)
    conn.execute("CREATE TABLE events(id INTEGER,kind TEXT,received_at TEXT,payload TEXT)")
    conn.execute(
        "INSERT INTO events VALUES(1,'HEALTH',?,?)",
        (START.isoformat(), json.dumps({"state": "FIXTURE"})),
    )
    conn.commit()
    conn.close()
    weather = tmp_path / "weather.sqlite3"
    weather.write_bytes(b"labeled synthetic unused snapshot")
    before = research.read_bytes()
    dataset = {
        airport: dict(reports=[], references=[], sensors={}, reference_exclusions={})
        for airport in ("EDDM", "EHAM", "EPWA", "EGLL")
    }
    monkeypatch.setattr(module, "load_snapshot", lambda *_: dataset)
    result = module.run(weather, research, tmp_path / "report")
    assert result["valid_book_pair_samples"] == 0
    assert result["actual_economic_fills"] == 0
    assert result["bins"]["status"] == "INSUFFICIENT_DATA"
    assert research.read_bytes() == before
    text = (tmp_path / "report" / "epwa_forecast_pws_metar_orderbook.md").read_text(
        encoding="utf-8"
    )
    assert "INSUFFICIENT_DATA" in text
    assert (tmp_path / "report" / "epwa_forecast_pws_metar_orderbook.png").stat().st_size > 1000
