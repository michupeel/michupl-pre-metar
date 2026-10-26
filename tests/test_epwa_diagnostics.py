"""Synthetic tests for read-only evidence classification, never live data writes."""

import importlib.util
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "scripts/research/epwa_diagnostics.py"
SPEC = importlib.util.spec_from_file_location("epwa_diagnostics", SOURCE)
assert SPEC and SPEC.loader
diagnostics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnostics)


def test_readonly_refuses_writes(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.sqlite3"
    with sqlite3.connect(path) as writer:
        writer.execute("CREATE TABLE evidence(value TEXT)")
        writer.execute("INSERT INTO evidence VALUES('preserved')")
    before = path.read_bytes()
    conn = diagnostics.readonly(path)
    assert conn.execute("SELECT value FROM evidence").fetchone() == ("preserved",)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        conn.execute("DELETE FROM evidence")
    conn.close()
    assert path.read_bytes() == before


def test_missing_quality_is_distinct_from_missing_measurement() -> None:
    at = datetime(2026, 10, 25, 20, 45, tzinfo=UTC)
    stations = [{"selected_station_asof": True, "eligible_observation_id": "actual-reading"}]
    assert diagnostics.classify_evidence("quality_weighted", None, at, stations) == (
        "NO_POSITIVE_VISIBLE_QUALITY_SCORE_ASOF_RECONSTRUCTION"
    )
    assert diagnostics.classify_evidence("nearest", None, at, stations).startswith("NOT_EXPLAINED")
    assert diagnostics.classify_evidence("nearest", None, at, []).startswith("NO_ELIGIBLE")


def test_first_receipt_not_nominal_target_controls_known_target() -> None:
    at = datetime(2026, 10, 25, 20, 45, tzinfo=UTC)
    assert diagnostics.classify_evidence("nearest", at, at, []) == (
        "TARGET_ALREADY_RECEIVED_IN_STORED_EVIDENCE"
    )
    assert diagnostics.classify_evidence("nearest", at + timedelta(seconds=1), at, []).startswith(
        "NO_ELIGIBLE"
    )


def test_unselected_stuck_or_zero_score_are_not_qualified() -> None:
    at = datetime(2026, 10, 25, tzinfo=UTC)
    for station in (
        {"selected_station_asof": False, "eligible_observation_id": "x"},
        {
            "selected_station_asof": True,
            "eligible_observation_id": "x",
            "quality_flags": ["STUCK_SENSOR"],
        },
    ):
        assert diagnostics.classify_evidence("nearest", None, at, [station]).startswith(
            "NO_ELIGIBLE"
        )
    station = {
        "selected_station_asof": True,
        "eligible_observation_id": "x",
        "visible_quality_score": 0,
    }
    assert diagnostics.classify_evidence("quality_weighted", None, at, [station]).startswith(
        "NO_POSITIVE"
    )
    station["visible_quality_score"] = 65
    assert diagnostics.classify_evidence("quality_weighted", None, at, [station]).startswith(
        "NOT_EXPLAINED"
    )


def test_parameter_table_identifier_is_allowlisted() -> None:
    with sqlite3.connect(":memory:") as conn:
        with pytest.raises(ValueError, match="Unsupported parameter table"):
            diagnostics.visible_parameters(
                conn, "pws_stations; DROP TABLE x", "s", "EPWA", datetime.now(UTC)
            )


def test_deferred_quality_requires_commit_proof_and_past_training() -> None:
    import json

    with sqlite3.connect(":memory:") as conn:
        conn.execute("CREATE TABLE analytical_qc_publications(batch_id TEXT,committed_at TEXT)")
        conn.execute(
            "CREATE TABLE pws_calibrations(id INTEGER,station_id TEXT,airport_icao TEXT,created_at TEXT,trained_through TEXT,data_json TEXT)"
        )
        at = datetime(2026, 10, 25, 20, 45, tzinfo=UTC)
        data = json.dumps(
            {"timestamp_policy_version": diagnostics.policy().version, "qc_batch_id": "q"}
        )
        conn.execute(
            "INSERT INTO pws_calibrations VALUES(1,'s','EPWA',?,?,?)",
            (
                (at - timedelta(minutes=2)).isoformat(),
                (at - timedelta(minutes=5)).isoformat(),
                data,
            ),
        )
        assert diagnostics.visible_parameters(conn, "pws_calibrations", "s", "EPWA", at) == []
        conn.execute(
            "INSERT INTO analytical_qc_publications VALUES('q',?)",
            ((at + timedelta(seconds=1)).isoformat(),),
        )
        assert diagnostics.visible_parameters(conn, "pws_calibrations", "s", "EPWA", at) == []
        conn.execute(
            "UPDATE analytical_qc_publications SET committed_at=?",
            ((at - timedelta(seconds=1)).isoformat(),),
        )
        assert len(diagnostics.visible_parameters(conn, "pws_calibrations", "s", "EPWA", at)) == 1
        conn.execute("UPDATE pws_calibrations SET trained_through=?", (at.isoformat(),))
        assert diagnostics.visible_parameters(conn, "pws_calibrations", "s", "EPWA", at) == []
