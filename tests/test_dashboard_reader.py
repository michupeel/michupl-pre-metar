"""Synthetic SQLite fixtures; no live writes or manufactured observed values."""

import hashlib
import json
import sqlite3
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from premetar.dashboard.reader import Reader


@pytest.fixture
def databases(tmp_path: Path) -> tuple[Path, Path, Path]:
    weather, research, trader = (
        tmp_path / name for name in ("weather.sqlite3", "research.sqlite3", "trader.sqlite3")
    )
    c = sqlite3.connect(weather)
    c.executescript("""
        CREATE TABLE observations(id,identity,event_time,temperature_c,raw_text,product_type,data_json,startup_censored,coverage_gap,source,station_icao);
        CREATE TABLE report_receipts(id,observation_id,collector_receive_time);
        CREATE TABLE pws_stations(station_id,provider,provider_station_id,first_discovered_at,data_json);
        CREATE TABLE pws_sensors(sensor_id,station_id,provider_sensor_id,data_json);
        CREATE TABLE pws_airport_stations(station_id,airport_icao,distance_km);
        CREATE TABLE pws_selections(id,station_id,airport_icao,created_at,selected,reason);
        CREATE TABLE pws_observations(id,sensor_id,observation_time,first_receive_time,temperature_c,data_json);
        CREATE TABLE pws_calibrations(id,station_id,airport_icao,created_at,trained_through,data_json);
        CREATE TABLE pws_quality_results(id,station_id,airport_icao,created_at,data_json);
        CREATE TABLE runs(id,started_at,ended_at,heartbeat,exit_reason);
        CREATE TABLE continuous_health(pid,updated_at,data_json);
        CREATE INDEX pws_sensor_time ON pws_observations(sensor_id,observation_time);
    """)
    for ident, source, received, cor, kind in [
        (1, "awc", "2026-10-25T00:33:00Z", False, "METAR"),
        (2, "alternate", "2026-10-25T00:32:00+00:00", False, "METAR"),
        (3, "awc", "2026-10-25T00:35:00Z", True, "METAR"),
        (4, "awc", "2026-10-25T00:40:00Z", False, "SPECI"),
    ]:
        c.execute(
            "INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                ident,
                "initial" if ident < 3 else str(ident),
                "2026-10-25T00:30:00Z",
                12,
                "FIXTURE TAC",
                kind,
                json.dumps({"cor": cor, "auto": True}),
                0,
                0,
                source,
                "EPWA",
            ),
        )
        c.execute("INSERT INTO report_receipts VALUES(?,?,?)", (ident, ident, received))
    c.execute(
        "INSERT INTO pws_stations VALUES('station','opensensemap','provider-station','2026-10-24T00:00:00Z',?)",
        (json.dumps(dict(station_name="Fixture", exposure="outdoor", latitude=52, longitude=21)),),
    )
    c.execute(
        "INSERT INTO pws_sensors VALUES('sensor','station','provider-sensor',?)",
        (json.dumps(dict(phenomenon="temperature", sensor_model="fixture model")),),
    )
    c.execute("INSERT INTO pws_airport_stations VALUES('station','EPWA',2.5)")
    c.execute(
        "INSERT INTO pws_selections VALUES(1,'station','EPWA','2026-10-24T01:00:00Z',1,'fixture selection')"
    )
    for identity, event, received in [
        ("prior", "2026-10-24T20:00:00Z", "2026-10-24T20:01:00Z"),
        ("valid", "2026-10-25T00:31:00Z", "2026-10-25T00:32:30Z"),
        ("untimed", None, "2026-10-25T00:33:00Z"),
    ]:
        c.execute(
            "INSERT INTO pws_observations VALUES(?,'sensor',?,?,12.34,?)",
            (
                identity,
                event,
                received,
                json.dumps(
                    dict(
                        timestamp_provenance="SENSOR_MEASUREMENT_TIME" if event else "UNKNOWN_TIME",
                        timestamp_semantics_verified=bool(event),
                        quality_flags=[],
                    )
                ),
            ),
        )
    c.execute(
        "INSERT INTO pws_calibrations VALUES(1,'station','EPWA','2026-10-25T00:00:00Z','2026-10-24T23:00:00Z','{\"bias\":0.5}')"
    )
    c.execute(
        "INSERT INTO runs VALUES('run','2026-10-24T00:00:00Z',NULL,'2026-10-25T00:35:00Z',NULL)"
    )
    c.execute("INSERT INTO continuous_health VALUES(123,'2026-10-25T00:35:00Z','{}')")
    c.commit()
    c.close()
    for path in (research, trader):
        c = sqlite3.connect(path)
        c.execute(
            "CREATE TABLE events(id INTEGER PRIMARY KEY,kind TEXT,received_at TEXT,payload TEXT)"
        )
        c.execute("CREATE INDEX event_kind ON events(kind,id)")
        c.commit()
        c.close()
    c = sqlite3.connect(research)

    def put(kind: str, received: str, payload: dict[str, Any]) -> None:
        c.execute(
            "INSERT INTO events(kind,received_at,payload) VALUES(?,?,?)",
            (kind, received, json.dumps(payload)),
        )

    put(
        "FORECAST",
        "2026-10-24T20:00:00Z",
        dict(airport="EPWA", first_received="2026-10-24T20:00:00Z", points=[]),
    )
    put(
        "FORECAST",
        "2026-10-25T01:00:00Z",
        dict(airport="EPWA", first_received="2026-10-25T01:00:00Z", points=[]),
    )
    put("FORECAST", "2026-10-26T01:00:00Z", dict(airport="EPWA", points=[]))
    put("FORECAST", "2026-10-25T02:00:00Z", dict(airport="EHAM", points=[]))
    identity = dict(
        airport="EPWA",
        local_date="2026-10-25",
        yes="yes",
        no="no",
        station="EPWA",
        station_match=True,
        condition_id="c",
    )
    put(
        "MARKET",
        "2026-10-25T00:00:00Z",
        dict(identity=identity, metadata={"description": "original rules"}),
    )
    view = dict(
        status="VALID",
        token_id="yes",
        market="c",
        best_bid="0.4",
        best_ask="0.5",
        bid_size="2",
        ask_size="3",
        received_at="2026-10-25T00:00:00Z",
        connection_id="epoch",
        bids=[{"price": ".4", "size": "2"}],
    )
    put(
        "BOOK_SAMPLE",
        "2026-10-25T00:00:00Z",
        dict(
            identity=identity,
            captured_at="2026-10-25T00:00:00Z",
            books={"yes": view, "no": {**view, "token_id": "no"}},
            fee_status="UNKNOWN",
        ),
    )
    put(
        "SIGNAL",
        "2026-10-25T00:01:00Z",
        dict(version="EXP0013-v1.1", created_at="2026-10-25T00:01:00Z", inputs={"airport": "EPWA"}),
    )
    put("STREAMHEALTH", "2026-10-25T00:00:00Z", dict(state="SUBSCRIBED", connection_id="epoch"))
    c.commit()
    c.close()
    return weather, research, trader


def test_missing_databases_are_not_created(tmp_path: Path) -> None:
    paths = tuple(tmp_path / name for name in ("w", "r", "t"))
    data = Reader(*paths).load_day(date(2026, 10, 25))
    assert data["metars"] == []
    assert data["forecasts"] == []
    assert data["limits"]["errors"]
    assert not any(path.exists() for path in paths)


def test_earliest_receipt_preserves_corrections_speci_and_sources(
    databases: tuple[Path, Path, Path],
) -> None:
    data = Reader(*databases).load_day(date(2026, 10, 25))
    assert len(data["metars"]) == 3
    initial = next(r for r in data["metars"] if r["report_identity"] == "initial")
    assert initial["first_received_utc"] == "2026-10-25T00:32:00+00:00"
    assert initial["providers"] == ["alternate", "awc"]
    assert any(r["correction"] for r in data["metars"])
    assert any(r["report_type"] == "SPECI" for r in data["metars"])


def test_provenance_untimed_inventory_and_prior_day_are_retained(
    databases: tuple[Path, Path, Path],
) -> None:
    data = Reader(*databases).load_day(date(2026, 10, 25))
    assert len(data["pws"]) == 2
    untimed = next(r for r in data["pws"] if r["id"] == "untimed")
    assert untimed["observation_time"] is None
    assert untimed["timestamp_provenance"] == "UNKNOWN_TIME"
    valid = next(r for r in data["pws"] if r["id"] == "valid")
    assert valid["temperature_c"] == 12.34
    assert valid["first_receive_time"] == "2026-10-25T00:32:30Z"
    assert data["stations"][0]["selected"]
    assert data["inventory_last"][0]["id"] == "prior"
    assert data["inventory_last"][0]["inventory_only_prior_day"]


def test_forecasts_keep_prior_snapshot_exclude_other_airport_and_future_day(
    databases: tuple[Path, Path, Path],
) -> None:
    data = Reader(*databases).load_day(date(2026, 10, 25))
    assert len(data["forecasts"]) == 2
    assert data["forecasts"][0]["first_received"] == "2026-10-24T20:00:00Z"
    assert all(r["airport"] == "EPWA" for r in data["forecasts"])


def test_small_book_projection_retains_real_quotes_without_full_depth(
    databases: tuple[Path, Path, Path],
) -> None:
    sample = Reader(*databases).load_day(date(2026, 10, 25))["book_samples"][0]
    assert sample["books"]["yes"]["best_bid"] == "0.4"
    assert sample["books"]["no"]["token_id"] == "no"
    assert "bids" not in sample["books"]["yes"]
    assert sample["books"]["yes"]["connection_id"] == "epoch"


def test_last_trade_retains_receipt_and_exact_token_mapping(
    databases: tuple[Path, Path, Path],
) -> None:
    conn = sqlite3.connect(databases[1])
    for token in ("yes", "unrelated"):
        conn.execute(
            "INSERT INTO events(kind,received_at,payload) VALUES('WS_TRADE',?,?)",
            (
                "2026-10-25T00:01:00Z",
                json.dumps(
                    dict(
                        token_id=token,
                        price=".45",
                        size="12",
                        side="BUY",
                        market="c",
                        source_timestamp="1792886460000",
                    )
                ),
            ),
        )
    conn.commit()
    conn.close()
    data = Reader(*databases).load_day(date(2026, 10, 25))
    assert len(data["trades"]) == 1
    assert data["trades"][0]["token_id"] == "yes"
    assert data["trades"][0]["received_at"] == "2026-10-25T00:01:00Z"
    assert data["trades"][0]["price"] == ".45"


def test_inventory_prior_day_does_not_apply_current_selection(
    databases: tuple[Path, Path, Path],
) -> None:
    conn = sqlite3.connect(databases[0])
    conn.execute(
        "INSERT INTO pws_selections VALUES(2,'station','EPWA','2026-10-25T02:00:00Z',0,'later exclusion')"
    )
    conn.commit()
    conn.close()
    data = Reader(*databases).load_day(date(2026, 10, 25))
    assert not data["stations"][0]["selected"]
    assert data["inventory_last"][0]["id"] == "prior"
    assert len(data["selections"]) == 2


def test_read_does_not_modify_database_bytes(databases: tuple[Path, Path, Path]) -> None:
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in databases]
    data = Reader(*databases).load_day(date(2026, 10, 25))
    assert data["limits"]["errors"] == {}
    assert before == [hashlib.sha256(p.read_bytes()).hexdigest() for p in databases]
    assert data["calibrations"][0]["parameters"]["bias"] == 0.5


@pytest.mark.parametrize("day,hours", [(date(2026, 10, 25), 25), (date(2026, 3, 29), 23)])
def test_calendar_day_boundaries_follow_warsaw_dst(tmp_path: Path, day: date, hours: int) -> None:
    data = Reader(tmp_path / "missing1", tmp_path / "missing2", tmp_path / "missing3").load_day(day)
    start = datetime.fromisoformat(data["start_utc"])
    end = datetime.fromisoformat(data["end_utc"])
    assert (end - start).total_seconds() == hours * 3600
    assert start.tzinfo == UTC


def test_readonly_connection_coexists_with_wal_writer(databases: tuple[Path, Path, Path]) -> None:
    weather = databases[0]
    writer = sqlite3.connect(weather)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("BEGIN IMMEDIATE")
    writer.execute(
        "INSERT INTO pws_selections VALUES(2,'station','EPWA','2026-10-25T02:00:00Z',0,'uncommitted')"
    )
    data = Reader(*databases).load_day(date(2026, 10, 25))
    assert data["stations"][0]["selected"]
    writer.rollback()
    writer.close()


def test_expensive_query_is_interrupted_with_bounded_error(
    databases: tuple[Path, Path, Path],
) -> None:
    reader = Reader(*databases)
    started = time.monotonic()
    result = reader._query(
        databases[0],
        "synthetic_budget",
        "WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL SELECT x+1 FROM n WHERE x<1000000000) SELECT SUM(x) FROM n",
    )
    assert result == []
    assert reader.errors["synthetic_budget"] == "QUERY_BUDGET_OR_BUSY"
    assert time.monotonic() - started < 2.5
