"""Synthetic clocks over the audited OSM box/sensors/lastMeasurement response shape."""

import asyncio
import json
import sqlite3
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio

from premetar.continuous.config import Config
from premetar.continuous.data import migrate as continuous_migrate
from premetar.pws.availability import (
    candidates,
    classify,
    measurement_clocks,
    migrate,
    reconcile,
    record_check,
    selection_at,
)
from premetar.pws.availability_loop import (
    poll_station,
    preflight_airport,
    selected_stations,
    station_schedule,
)
from premetar.pws.models import Sensor, Station
from premetar.pws.providers import OpenSenseMap, Transport, reading
from premetar.pws.recovery_state import transition
from premetar.pws.repository import PWSStore, sensor_key
from premetar.pws.service import settings

AT = datetime(2026, 10, 25, 12, tzinfo=UTC)
AIRPORT = next(a for a in settings().airports if a.icao == "EPWA")


@pytest_asyncio.fixture
async def store(tmp_path):
    s = PWSStore(tmp_path / "test.db", tmp_path / "raw", "synthetic")
    await s.open({"synthetic": True}, {})
    await s._call(s.register, settings().airports, [OpenSenseMap])
    await s._call(continuous_migrate, s.connection)
    yield s
    await s.close("test")


def station(name="box", offset=0, sensors=("t",)):
    return Station(
        provider="opensensemap",
        provider_station_id=name,
        exposure="outdoor",
        latitude=AIRPORT.latitude + offset,
        longitude=AIRPORT.longitude,
        sensors=[Sensor(provider_sensor_id=s, unit="C") for s in sensors],
    )


async def capture(store, at=AT, body=b"{}", status=200):
    return await store.capture(
        dict(
            source="pws_opensensemap",
            request_url="https://example.test/boxes/box/sensors",
            http_status=status,
            headers={},
            request_start=(at - timedelta(seconds=1)).isoformat(),
            request_end=at.isoformat(),
            received_at=at.isoformat(),
            monotonic_ns=1,
            request_start_monotonic_ns=0,
        ),
        body,
    )


async def discovered(store, s):
    packet = await capture(store)
    await store._call(store.discover, AIRPORT, s, packet)
    return packet


async def check(store, s, r, at=AT, error=None):
    packet = await capture(store, at)
    return await store._call(
        record_check,
        store.connection,
        store.run_id,
        "EPWA",
        s,
        sensor_key(s.station_id, r.provider_sensor_id if r else "t"),
        r,
        packet,
        "SYNTHETIC",
        None,
        False,
        error,
        at,
    )


@pytest.mark.parametrize("last", [None, {}, {"createdAt": AT.isoformat()}])
async def test_empty_shapes_preserve_raw_not_observations(store, monkeypatch, last):
    s = station()
    await discovered(store, s)
    monkeypatch.setattr("premetar.pws.availability.utc_now", lambda: AT)
    body = dict(sensors=[dict(_id="t", unit="C", lastMeasurement=last)])
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _, body=body: httpx.Response(200, json=body))
    ) as client:
        provider = OpenSenseMap(Transport(client, store))
        for _ in range(2):
            result = await poll_station(store, provider, s, "EPWA", "TEST")
            assert result[0]["outcome"] == "NO_MEASUREMENT"

    def verify():
        c = store.connection
        assert c.execute("SELECT count(*) FROM pws_observations").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM pws_sensor_checks").fetchone()[0] == 2
        assert c.execute("SELECT count(*) FROM raw_payloads").fetchone()[0] == 3
        assert (
            c.execute(
                "SELECT count(*) FROM continuous_polls WHERE error_class IS NOT NULL"
            ).fetchone()[0]
            == 0
        )

    await store._call(verify)


async def test_absent_sensor_and_missing_lastmeasurement(store):
    s = station()
    await discovered(store, s)
    for body in ({"sensors": []}, {"sensors": [{"_id": "t", "unit": "C"}]}):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _, body=body: httpx.Response(200, json=body))
        ) as client:
            result = await poll_station(
                store, OpenSenseMap(Transport(client, store)), s, "EPWA", "TEST"
            )
            assert result[0]["outcome"] == "NO_MEASUREMENT"
    assert (
        await store._call(
            lambda: store.connection.execute("SELECT count(*) FROM pws_observations").fetchone()[0]
        )
        == 0
    )


async def test_same_measurement_different_packet_preserves_first_receipt(store, monkeypatch):
    s = station()
    await discovered(store, s)
    monkeypatch.setattr("premetar.pws.availability.utc_now", lambda: AT)
    first = await capture(store, AT)
    r = reading("t", "18.20", "C", AT - timedelta(seconds=30))
    ident = await store._call(store.ingest, s, r, first)
    monkeypatch.setattr("premetar.pws.availability.utc_now", lambda: AT + timedelta(seconds=60))
    second = await capture(store, AT + timedelta(seconds=60))
    same = await store._call(
        store.ingest, s, r.model_copy(update={"raw_temperature": "18.2"}), second
    )
    assert same == ident

    def verify():
        assert store.connection.execute("SELECT count(*) FROM pws_observations").fetchone()[0] == 1
        assert store.connection.execute("SELECT count(*) FROM pws_arrivals").fetchone()[0] == 2
        assert (
            store.connection.execute("SELECT first_receive_time FROM pws_observations").fetchone()[
                0
            ]
            == first["received_at"]
        )
        assert store.connection.execute(
            "SELECT outcome FROM pws_sensor_checks ORDER BY id"
        ).fetchall() == [("SUCCESS_NEW_MEASUREMENT",), ("SUCCESS_UNCHANGED_MEASUREMENT",)]
        assert store.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not store.connection.execute("PRAGMA foreign_key_check").fetchall()

    await store._call(verify)


@pytest.mark.parametrize(
    "offset,value,expected",
    [(-30, 18, "ACTIVE"), (-301, 18, "STALE"), (1, 18, "INVALID"), (-30, 100, "INVALID")],
)
def test_strict_freshness_and_physical_limits(offset, value, expected):
    assert (
        classify(station(), reading("t", value, "C", AT + timedelta(seconds=offset)), AT)[0]
        == expected
    )


def test_ingest_time_and_untimed_values_never_eligible():
    r = reading("t", 18, "C", AT - timedelta(seconds=30))
    assert (
        classify(
            station(),
            r.model_copy(
                update={
                    "timestamp_provenance": "PROVIDER_INGEST_TIME",
                    "timestamp_semantics_verified": False,
                }
            ),
            AT,
        )[0]
        == "UNVERIFIED"
    )
    assert classify(station(), reading("t", 18, "C", None), AT)[0] == "UNVERIFIED"


def test_hysteresis_failure_isolation_and_recovery():
    state = transition(None, "ACTIVE", AT)
    for i in range(2):
        state = transition(state, "NO_MEASUREMENT", AT + timedelta(minutes=i + 1))
        assert state["mode"] == "ACTIVE"
    state = transition(state, "STALE", AT + timedelta(minutes=3))
    assert state["mode"] == "INACTIVE"
    state = transition(state, "UNVERIFIED", AT + timedelta(minutes=4))
    assert state["fail_streak"] == 3
    state = transition(state, "ACTIVE", AT + timedelta(minutes=5))
    assert state["mode"] == "INACTIVE"
    assert transition(state, "ACTIVE", AT + timedelta(minutes=10))["mode"] == "ACTIVE"
    with pytest.raises(ValueError):
        transition(None, "ACTIVE", AT.replace(tzinfo=None))


async def test_actual_sensor_selection_replacement_versioning_and_asof(store, monkeypatch):
    monkeypatch.setattr("premetar.pws.availability_loop.utc_now", lambda: AT)
    a, b = station("a", sensors=("empty", "t")), station("b", 0.01)
    for s in (a, b):
        await discovered(store, s)
        await check(store, s, reading("t", 18, "C", AT - timedelta(seconds=10)))
    first = await store._call(reconcile, store.connection, "EPWA", AT)
    chosen = await store._call(selected_stations, store, "EPWA")
    assert len(chosen) == 2
    assert chosen[0].sensors[0].provider_sensor_id == "t"
    assert await store._call(reconcile, store.connection, "EPWA", AT) == first
    for i in range(3):
        await check(store, a, None, AT + timedelta(seconds=i + 1))
    second = await store._call(reconcile, store.connection, "EPWA", AT + timedelta(seconds=4))
    assert second != first

    def verify():
        old = selection_at(store.connection, "EPWA", "opensensemap", AT)
        new = selection_at(store.connection, "EPWA", "opensensemap", AT + timedelta(seconds=4))
        assert old["id"] == first and new["id"] == second
        assert len(json.loads(new["data_json"])["selected_sensor_ids"]) == 1
        # Later failure must not hide an earlier valid check in as-of queries.
        assert next(
            r for r in candidates(store.connection, "EPWA", AT) if r["station_id"] == a.station_id
        )["eligible"]
        with pytest.raises(sqlite3.IntegrityError):
            store.connection.execute("UPDATE pws_selection_versions SET reason='changed'")

    await store._call(verify)


async def test_spaced_recovery_and_repeated_packet_does_not_advance_streak(store):
    s = station()
    packet = await discovered(store, s)
    await check(store, s, None)
    fresh = reading("t", 18, "C", AT + timedelta(minutes=30) - timedelta(seconds=10))
    first = await check(store, s, fresh, AT + timedelta(minutes=30))
    assert first["mode"] == "INACTIVE" and first["good_streak"] == 1
    too_soon = await check(store, s, fresh, AT + timedelta(minutes=30, seconds=2))
    assert too_soon["mode"] == "INACTIVE" and too_soon["good_streak"] == 1
    restored = await check(
        store,
        s,
        reading("t", 18, "C", AT + timedelta(minutes=35, seconds=3)),
        AT + timedelta(minutes=35, seconds=3),
    )
    assert restored["mode"] == "ACTIVE"

    async def repeat():
        return await store._call(
            record_check,
            store.connection,
            store.run_id,
            "EPWA",
            s,
            sensor_key(s.station_id, "t"),
            None,
            packet,
            "TEST",
            None,
            False,
            None,
            AT + timedelta(hours=1),
        )

    one, two = await repeat(), await repeat()
    assert one == two


async def test_restart_poll_deadline_and_cadence_ignore_invalid_events(store, monkeypatch):
    s = station()
    await discovered(store, s)
    for i in range(4):
        at = AT - timedelta(minutes=15 - i * 5)
        packet = await capture(store, at)
        await store._call(
            store.ingest, s, reading("t", 18, "C", at - timedelta(seconds=10)), packet
        )
    packet = await capture(store, AT)
    await store._call(store.ingest, s, reading("t", 18, "C", AT + timedelta(hours=1)), packet)
    monkeypatch.setattr("premetar.pws.availability_loop.utc_now", lambda: AT)
    clocks = await store._call(
        measurement_clocks, store.connection, sensor_key(s.station_id, "t"), AT
    )
    assert len(clocks) == 4 and max(clocks) < AT
    interval, delay = await store._call(station_schedule, store, s, Config())
    assert interval >= 300 and delay > 0
    # Additive schema upgrade is repeatable and retains immutable data.
    await store._call(migrate, store.connection)
    assert (
        await store._call(
            lambda: store.connection.execute("SELECT count(*) FROM pws_observations").fetchone()[0]
        )
        == 5
    )


async def test_preflight_uses_live_measurement_not_discovery_id(store, monkeypatch):
    s = station("live", sensors=("empty", "t"))
    packet = await capture(store, AT)
    monkeypatch.setattr("premetar.pws.availability.utc_now", lambda: AT)
    monkeypatch.setattr("premetar.pws.availability_loop.utc_now", lambda: AT)

    class FakeProvider:
        name = "opensensemap"
        last_packet = packet

        async def discover(self, *args):
            return [(s, packet)]

        async def fetch_latest(self, station):
            return [(reading("t", 18, "C", AT - timedelta(seconds=20)), packet)]

    result = await preflight_airport(store, FakeProvider(), "EPWA", asyncio.Event())
    assert result["temperature_sensors"] == 2
    assert result["checked_stations"] == 1
    selected = await store._call(selected_stations, store, "EPWA")
    assert [t.provider_sensor_id for t in selected[0].sensors] == ["t"]


async def test_candidate_submillisecond_asof_and_manual_exclusion(store):
    s = station()
    await discovered(store, s)
    await check(store, s, reading("t", 18, "C", AT - timedelta(seconds=10)), AT)
    await check(store, s, None, AT + timedelta(microseconds=100))

    def verify():
        assert candidates(store.connection, "EPWA", AT)[0]["eligible"]
        with store.connection:
            store.connection.execute(
                "INSERT INTO pws_selections VALUES(NULL,?,?,?,?,?)",
                (s.station_id, "EPWA", AT.isoformat(), 0, "manual exclusion"),
            )
        assert not candidates(store.connection, "EPWA", AT)[0]["eligible"]
        reconcile(store.connection, "EPWA", AT)
        v = selection_at(store.connection, "EPWA", "opensensemap", AT)
        assert json.loads(v["data_json"])["selected_sensor_ids"] == []

    await store._call(verify)


async def test_diversity_caps_avoid_multiple_station_votes(store):
    for i in range(6):
        s = station(str(i), 0.01 * i, ("a", "b"))
        await discovered(store, s)
        for t in ("a", "b"):
            await check(store, s, reading(t, 18, "C", AT - timedelta(seconds=10)))

    def verify():
        reconcile(store.connection, "EPWA", AT)
        v = selection_at(store.connection, "EPWA", "opensensemap", AT)
        d = json.loads(v["data_json"])
        assert len(d["selected_sensor_ids"]) == 4
        assert len(d["selected_station_ids"]) == 4

    await store._call(verify)


@pytest.mark.parametrize("failure", ["rate", "timeout", "malformed", "auth"])
async def test_provider_errors_are_not_empty_sensor_failures(store, failure):
    s = station()
    await discovered(store, s)

    def respond(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic", request=request)
        if failure == "malformed":
            return httpx.Response(200, content=b"invalid json")
        return httpx.Response(429 if failure == "rate" else 401)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        p = OpenSenseMap(Transport(client, store, max_attempts=1))
        result = await poll_station(store, p, s, "EPWA", "TEST")
        assert result[0]["outcome"] == "PROVIDER_ERROR"
        assert result[0]["status"] == "UNVERIFIED"
        assert result[0]["fail_streak"] == 0

    def verify():
        assert store.connection.execute("SELECT count(*) FROM pws_observations").fetchone()[0] == 0
        assert (
            store.connection.execute(
                "SELECT count(*) FROM continuous_polls WHERE error_class IS NOT NULL"
            ).fetchone()[0]
            == 1
        )

    await store._call(verify)
