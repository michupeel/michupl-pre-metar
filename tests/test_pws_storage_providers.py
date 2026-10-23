"""Synthetic fixtures following the verified API schemas; no live unit requests."""

import base64
import json
import sqlite3
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from typer.testing import CliRunner

from premetar.cli import app
from premetar.pws.analysis import latest_station_reading, predict
from premetar.pws.models import Airport, QCConfig, Reading, Sensor, Station
from premetar.pws.netatmo_auth import NetatmoAuth
from premetar.pws.providers import Netatmo, OpenSenseMap, ProviderError, SensorCommunity, Transport
from premetar.pws.repository import PWSStore, inventory, readings
from premetar.pws.service import settings, write_reports

NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)
AIRPORT = Airport(
    icao="EDDM", name="Synthetic", latitude=48.348, longitude=11.813, reference="fixture"
)
STATION = Station(
    provider="opensensemap",
    provider_station_id="box",
    latitude=48.35,
    longitude=11.81,
    sensors=[Sensor(provider_sensor_id="t", unit="°C")],
)
BOX = {
    "_id": "box",
    "name": "Synthetic",
    "currentLocation": {"coordinates": [11.81, 48.35]},
    "exposure": "outdoor",
    "sensors": [
        {
            "_id": "t",
            "title": "Temperatur",
            "unit": "°C",
            "lastMeasurement": {"value": "18.2", "createdAt": "2026-10-24T11:59:00Z"},
        }
    ],
}
SC = {
    "id": 1,
    "timestamp": "2026-10-24 11:59:00",
    "location": {"id": 10, "latitude": "48.35", "longitude": "11.81", "indoor": 0},
    "sensor": {"id": 123, "sensor_type": {"name": "BME280"}},
    "sensordatavalues": [
        {"value_type": "temperature", "value": "18.2"},
        {"value_type": "humidity", "value": "60"},
    ],
}


@pytest_asyncio.fixture
async def store(tmp_path):
    s = PWSStore(tmp_path / "test.db", tmp_path / "raw", "test-run")
    await s.open({"test": True}, {"pws_opensensemap": 300, "pws_sensor_community": 300})
    await s._call(s.register, [AIRPORT], [OpenSenseMap, SensorCommunity, Netatmo])
    yield s
    await s.close("test")


async def captured(store, when=NOW, body=b"original synthetic bytes"):
    return await store.capture(
        {
            "source": "pws_opensensemap",
            "request_url": "https://example.test?token=secret",
            "http_status": 200,
            "headers": {},
            "request_start": (when - timedelta(seconds=1)).isoformat(),
            "request_end": when.isoformat(),
            "received_at": when.isoformat(),
            "monotonic_ns": time.perf_counter_ns(),
            "request_start_monotonic_ns": time.perf_counter_ns() - 1000,
        },
        body,
    )


def make_reading(value=18, event=NOW - timedelta(minutes=1)):
    return Reading(
        provider_sensor_id="t",
        observation_time=event,
        temperature_c=value,
        raw_unit="°C",
        raw_temperature=str(value),
    )


async def client_for(store, payload, status=200):
    def respond(request):
        return httpx.Response(status, json=payload, headers={"Retry-After": "600"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    return client, Transport(client, store)


async def test_migration_repeat_discovery_arrivals_and_raw(store):
    first = await captured(store)
    await store._call(store.discover, AIRPORT, STATION, first)
    await store._call(store.discover, AIRPORT, STATION, first)
    await store._call(store.register, [AIRPORT], [OpenSenseMap, SensorCommunity])
    later = await captured(store, NOW + timedelta(minutes=5))
    await store._call(
        store.discover, AIRPORT, STATION.model_copy(update={"station_name": "changed"}), later
    )
    for p in [first, first, later]:
        await store._call(store.ingest, STATION, make_reading(), p, False)

    def check():
        c = store.connection
        assert c.execute("SELECT count(*) FROM pws_stations").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM pws_discoveries").fetchone()[0] == 2
        assert c.execute("SELECT count(*) FROM pws_observations").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM pws_arrivals").fetchone()[0] == 2
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
        assert (
            c.execute("SELECT first_receive_time FROM pws_observations").fetchone()[0]
            == NOW.isoformat()
        )
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO pws_sensors VALUES('bad','absent','x','{}')")
        assert len(inventory(c, "EDDM")) == 1

    await store._call(check)
    envelope = json.loads(__import__("pathlib").Path(first["path"]).read_text())
    assert base64.b64decode(envelope["body_base64"]) == b"original synthetic bytes"
    assert "secret" not in json.dumps(envelope)


@pytest.mark.parametrize("payload,expected", [([BOX], 1), ([], 0), ([{"_id": "bad"}], 0)])
async def test_opensense_discovery(store, payload, expected):
    client, http = await client_for(store, payload)
    async with client:
        found = await OpenSenseMap(http).discover(48.348, 11.813, 20)
        assert len(found) == expected
        if found:
            assert found[0][0].sensors[0].provider_sensor_id == "t"


async def test_radius_filter_and_duplicate_boxes(store):
    far = {**BOX, "_id": "far", "currentLocation": {"coordinates": [0, 0]}}
    client, http = await client_for(store, [BOX, BOX, far])
    async with client:
        assert len(await OpenSenseMap(http).discover(48.348, 11.813, 20)) == 1


@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_http_failures_raw_preserved(store, status):
    client, http = await client_for(store, {}, status)
    async with client:
        with pytest.raises(ProviderError) as error:
            await OpenSenseMap(http).discover(48.348, 11.813, 20)
        if status == 429:
            assert error.value.retry_seconds == 600
        if status in [401, 403]:
            assert "opensensemap" in http.disabled
    assert (
        await store._call(
            lambda: store.connection.execute("SELECT count(*) FROM raw_payloads").fetchone()[0]
        )
        >= 1
    )


async def test_timeout_bounded(store):
    calls = 0

    def timeout(request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("synthetic timeout")

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        http = Transport(client, store)
        with pytest.raises(ProviderError, match="TRANSPORT_FAILURE"):
            await OpenSenseMap(http).discover(48.348, 11.813, 20)
    assert calls == 3


@pytest.mark.parametrize(
    "measurement", [{"value": "18.2", "createdAt": "2026-10-24T11:59:00Z"}, {}, {"value": "NaN"}]
)
async def test_latest_missing_values_and_timestamps(store, measurement):
    client, http = await client_for(
        store, {"sensors": [{**BOX["sensors"][0], "lastMeasurement": measurement}]}
    )
    async with client:
        result = await OpenSenseMap(http).fetch_latest(STATION)
        assert len(result) == 1
        assert result[0][0].source_publish_time is None
        if not measurement.get("createdAt"):
            assert result[0][0].observation_time is None


@pytest.mark.parametrize("payload", [{}, None, "bad"])
async def test_malformed_schema(store, payload):
    client, http = await client_for(store, payload)
    async with client:
        with pytest.raises(ProviderError):
            await OpenSenseMap(http).discover(48.348, 11.813, 20)


async def test_sensor_community_server_timestamp_not_observation(store):
    client, http = await client_for(store, [SC])
    async with client:
        adapter = SensorCommunity(http)
        stations = await adapter.discover(48.348, 11.813, 20)
        assert len(stations) == 1
        latest = await adapter.fetch_latest(stations[0][0])
        value = latest[0][0]
        assert value.observation_time is None
        assert value.source_publish_time is None
        assert value.provider_timestamp == datetime(2026, 10, 24, 11, 59, tzinfo=UTC)
        assert "SERVER_TIMESTAMP_ONLY" in value.quality_flags
        assert value.relative_humidity == 60
        assert not adapter.capabilities.historical_observations


async def test_delayed_historical_conflict_and_prediction_immutable(store):
    p = await captured(store, NOW - timedelta(minutes=2))
    await store._call(store.discover, AIRPORT, STATION, p)
    delayed = await captured(store, NOW + timedelta(minutes=1))
    await store._call(store.ingest, STATION, make_reading(19), delayed, False)
    await store._call(store.ingest, STATION, make_reading(30), p, False, True)
    assert await store._call(readings, store.connection, STATION.station_id, NOW) == []
    await store._call(store.ingest, STATION, make_reading(), p, False)

    def prediction():
        c = store.connection
        with c:
            c.execute(
                "INSERT INTO pws_selections VALUES(NULL,?,?,?,?,?)",
                (STATION.station_id, "EDDM", p["received_at"], 1, "fixture"),
            )
            result = predict(c, "EDDM", NOW + timedelta(minutes=10), QCConfig(), created=NOW)
        assert result["integer_temperature"] == 18
        assert result["contributions"][0]["temperature_c"] == 18
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("UPDATE pws_predictions SET data_json='{}'")
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("DELETE FROM pws_predictions")
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT OR REPLACE INTO pws_predictions SELECT * FROM pws_predictions")
        return result

    result = await store._call(prediction)
    assert result["created_at"] == NOW.isoformat()
    # Distinct revision at the same event must not silently win by receipt order.
    await store._call(store.ingest, STATION, make_reading(17), p, False)
    assert (
        await store._call(latest_station_reading, store.connection, STATION, NOW, QCConfig())
        is None
    )


async def test_report_empty_and_restart_compatible(store, tmp_path):
    result = await store._call(write_reports, store, {"EDDM"}, settings(), tmp_path / "reports")
    assert result["conclusion"] == "INSUFFICIENT DATA"
    assert (tmp_path / "reports/station_rankings.parquet").exists()
    assert (
        await store._call(
            lambda: store.connection.execute("SELECT max(version) FROM schema_version").fetchone()[
                0
            ]
        )
        == 1
    )


async def test_netatmo_auth_failure_never_logs_token(monkeypatch):
    monkeypatch.setenv("NETATMO_REFRESH_TOKEN", "private-refresh")
    monkeypatch.setenv("NETATMO_CLIENT_ID", "id")
    monkeypatch.setenv("NETATMO_CLIENT_SECRET", "private-secret")
    auth = NetatmoAuth()

    def response(request):
        assert request.url == "https://api.netatmo.com/oauth2/token"
        return httpx.Response(401, json={"error": "private-secret"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        with pytest.raises(ProviderError) as error:
            await auth.refresh(client)
    assert auth.disabled
    assert "private" not in str(error.value)


def test_cli_sources_and_bounds():
    runner = CliRunner()
    assert runner.invoke(app, ["pws", "sources"]).exit_code == 0
    assert runner.invoke(app, ["pws", "collect", "--duration", "0"]).exit_code != 0
    assert runner.invoke(app, ["pws", "select", "--exclude"]).exit_code != 0


async def test_combined_collector_isolates_bad_provider(tmp_path, monkeypatch):
    from premetar.collector import collect
    from premetar.parsers import parse_awc
    from premetar.sources import HttpSource

    monkeypatch.setattr("premetar.collector.clock_status", lambda: {"warning": "synthetic"})
    calls = []

    def respond(request):
        calls.append(str(request.url))
        if request.url.host == "metar.test":
            return httpx.Response(
                200,
                json=[
                    {"icaoId": "EDDM", "rawOb": "METAR EDDM 241150Z AUTO 00000KT 9999 18/12 Q1013"}
                ],
            )
        if request.url.host == "api.opensensemap.org":
            return httpx.Response(401, json={"error": "fixture"})
        return httpx.Response(200, json=[SC])

    config = settings().model_copy(update={"airports": [AIRPORT]})
    database = tmp_path / "combined.db"
    await collect(
        [HttpSource("awc", "https://metar.test", frozenset({"EDDM"}), parse_awc)],
        {"EDDM"},
        database,
        tmp_path / "raw",
        0.2,
        False,
        transport=httpx.MockTransport(respond),
        pws_settings=config,
        pws_airports={"EDDM"},
    )
    with sqlite3.connect(database) as c:
        assert c.execute("SELECT count(*) FROM observations").fetchone()[0] == 1
        assert (
            c.execute(
                "SELECT count(*) FROM pws_stations WHERE provider='sensor_community'"
            ).fetchone()[0]
            == 1
        )
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    assert not database.with_suffix(".db.lock").exists()
    assert len(calls) == 3


@pytest.mark.parametrize(
    "method,expected",
    [("equal_weights", 19), ("quality_weighted", 18.4), ("inverse_historical_error", 18.4)],
)
async def test_prediction_weights_only_prior_quality_and_calibration(store, method, expected):
    packet = await captured(store, NOW - timedelta(seconds=1))
    other = STATION.model_copy(update={"provider_station_id": "other", "latitude": 48.37})
    for s, temp in [(STATION, 18), (other, 20)]:
        await store._call(store.discover, AIRPORT, s, packet)
        await store._call(store.ingest, s, make_reading(temp), packet, False)

    def evaluate():
        c = store.connection
        with c:
            for s, quality, error in [(STATION, 80, 0.5), (other, 20, 2)]:
                c.execute(
                    "INSERT INTO pws_selections VALUES(NULL,?,?,?,?,?)",
                    (s.station_id, "EDDM", packet["received_at"], 1, "fixture"),
                )
                c.execute(
                    "INSERT INTO pws_quality_results VALUES(NULL,?,?,?,?,?)",
                    (
                        s.station_id,
                        "EDDM",
                        packet["received_at"],
                        "fixture",
                        json.dumps(
                            {
                                "score": quality,
                                "predictive": {
                                    "interval_aware_error": error,
                                    "sample_count": 200,
                                    "evaluation_days": 10,
                                },
                            }
                        ),
                    ),
                )
                # Future correction is attractive-looking but unavailable at decision time.
                c.execute(
                    "INSERT INTO pws_quality_results VALUES(NULL,?,?,?,?,?)",
                    (
                        s.station_id,
                        "EDDM",
                        (NOW + timedelta(seconds=1)).isoformat(),
                        "future",
                        json.dumps(
                            {
                                "score": 100 - quality,
                                "predictive": {
                                    "interval_aware_error": 1 / error,
                                    "sample_count": 200,
                                    "evaluation_days": 10,
                                },
                            }
                        ),
                    ),
                )
                c.execute(
                    "INSERT INTO pws_calibrations VALUES(NULL,?,?,?,?,?)",
                    (
                        s.station_id,
                        "EDDM",
                        (NOW + timedelta(seconds=1)).isoformat(),
                        (NOW - timedelta(hours=1)).isoformat(),
                        '{"bias":100}',
                    ),
                )
            result = predict(
                c, "EDDM", NOW + timedelta(minutes=10), QCConfig(), method, created=NOW
            )
            assert all(r["correction_c"] == 0 for r in result["contributions"])
            assert result["estimate_c"] == pytest.approx(expected)

    await store._call(evaluate)


async def test_prediction_inverse_distance_and_future_selection(store):
    packet = await captured(store, NOW - timedelta(seconds=1))
    other = STATION.model_copy(update={"provider_station_id": "far", "latitude": 48.40})
    for s, temp in [(STATION, 18), (other, 20)]:
        await store._call(store.discover, AIRPORT, s, packet)
        await store._call(store.ingest, s, make_reading(temp), packet, False)

    def evaluate():
        c = store.connection
        with c:
            c.execute(
                "INSERT INTO pws_selections VALUES(NULL,?,?,?,?,?)",
                (STATION.station_id, "EDDM", packet["received_at"], 1, "fixture"),
            )
            c.execute(
                "INSERT INTO pws_selections VALUES(NULL,?,?,?,?,?)",
                (other.station_id, "EDDM", (NOW + timedelta(seconds=1)).isoformat(), 1, "future"),
            )
            result = predict(
                c, "EDDM", NOW + timedelta(minutes=10), QCConfig(), "inverse_distance", created=NOW
            )
            assert len(result["contributions"]) == 1
            assert result["estimate_c"] == 18

    await store._call(evaluate)


async def test_history_is_explicitly_event_only(store):
    client, http = await client_for(store, [{"createdAt": "2026-10-23T12:00:00Z", "value": "18.4"}])
    async with client:
        data = await OpenSenseMap(http).fetch_history(STATION, NOW - timedelta(days=2), NOW)
    assert data[0][0].evidence_class == "HISTORICAL_EVENT_ONLY"
    await store._call(store.discover, AIRPORT, STATION, data[0][1])
    await store._call(store.ingest, STATION, data[0][0], data[0][1])
    assert (
        await store._call(readings, store.connection, STATION.station_id, NOW + timedelta(days=100))
        == []
    )


async def test_report_handles_late_nonnull_values(store, tmp_path):
    packet = await captured(store)
    for index in range(105):
        s = STATION.model_copy(
            update={
                "provider_station_id": str(index),
                "station_name": "late nonnull" if index == 104 else None,
            }
        )
        await store._call(store.discover, AIRPORT, s, packet)
    await store._call(write_reports, store, {"EDDM"}, settings(), tmp_path / "reports")
    import polars as pl

    assert (
        pl.read_parquet(tmp_path / "reports/station_inventory.parquet")["station_name"].null_count()
        == 104
    )


async def test_pws_restart_then_legacy_metar_store(tmp_path):
    from premetar.store import Store

    db, raw = tmp_path / "restart.db", tmp_path / "raw"
    for index in [1, 2]:
        s = PWSStore(db, raw, f"pws-{index}")
        await s.open({"fixture": True}, {})
        await s._call(s.register, [AIRPORT], [OpenSenseMap])
        packet = await captured(s, NOW + timedelta(seconds=index))
        await s._call(s.discover, AIRPORT, STATION, packet)
        await s._call(s.ingest, STATION, make_reading(), packet)
        await s.close("test")
    legacy = Store(db, raw, "legacy")
    await legacy.open({"fixture": True}, {})
    await legacy.close("test")
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT count(*) FROM pws_stations").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM pws_observations").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM pws_arrivals").fetchone()[0] == 2
        assert c.execute("SELECT count(*) FROM runs").fetchone()[0] == 3


async def test_persisted_forecast_evaluation_separates_accuracy_and_lead(store):
    from premetar.parsers import parse_awc
    from premetar.pws.analysis import evaluate_predictions

    packet = await captured(store, NOW - timedelta(seconds=1))
    await store._call(store.discover, AIRPORT, STATION, packet)
    await store._call(store.ingest, STATION, make_reading(), packet, False)

    def make_forecast():
        with store.connection:
            store.connection.execute(
                "INSERT INTO pws_selections VALUES(NULL,?,?,?,?,?)",
                (STATION.station_id, "EDDM", packet["received_at"], 1, "fixture"),
            )
            predict(
                store.connection,
                "EDDM",
                NOW + timedelta(minutes=10),
                QCConfig(),
                created=NOW,
                run_id=store.run_id,
            )

    await store._call(make_forecast)
    assert (await store._call(evaluate_predictions, store.connection, "EDDM", NOW))[0][
        "status"
    ] == "PENDING"
    body = json.dumps(
        [{"icaoId": "EDDM", "rawOb": "METAR EDDM 241210Z AUTO 00000KT 9999 18/12 Q1013"}]
    ).encode()
    ref = await captured(store, NOW + timedelta(minutes=11), body)
    await store.parse_and_save(ref, body, parse_awc, {"EDDM"}, False, False)
    result = await store._call(
        evaluate_predictions, store.connection, "EDDM", NOW + timedelta(minutes=12)
    )
    assert result[0]["integer_match"] is True
    assert result[0]["utc_receive_difference_seconds"] == 660
    assert result[0]["measured_information_lead_seconds"] is None
    assert result[0]["status"] == "OBSERVED_ACCURACY_ONLY"


async def test_metar_z_clocks_join_pws_offset_clocks_without_submillisecond_leakage(store):
    from premetar.parsers import parse_awc
    from premetar.pws.analysis import make_pairs

    packet = await captured(store, NOW - timedelta(minutes=30))
    await store._call(store.discover, AIRPORT, STATION, packet)
    observation = await captured(store, NOW - timedelta(seconds=1))
    await store._call(store.ingest, STATION, make_reading(), observation, False)
    for nominal, received, temperature, cor in [
        ("241140", NOW - timedelta(minutes=15), 17, ""),
        ("241140", NOW - timedelta(minutes=10), 18, "COR "),
        ("241210", NOW + timedelta(minutes=11), 18, ""),
    ]:
        body = json.dumps(
            [
                {
                    "icaoId": "EDDM",
                    "rawOb": f"METAR EDDM {nominal}Z {cor}AUTO 00000KT 9999 {temperature}/12 Q1013",
                }
            ]
        ).encode()
        ref = await captured(store, received, body)
        await store.parse_and_save(ref, body, parse_awc, {"EDDM"}, False, False)
    cutoff = NOW + timedelta(minutes=11)
    assert (
        await store._call(
            make_pairs,
            store.connection,
            "EDDM",
            STATION.station_id,
            QCConfig(),
            cutoff - timedelta(microseconds=1),
        )
        == []
    )
    pairs = await store._call(
        make_pairs, store.connection, "EDDM", STATION.station_id, QCConfig(), cutoff
    )
    assert len(pairs) == 1
    assert pairs[0]["baseline_integer"] == 18
    assert datetime.fromisoformat(pairs[0]["label_available_at"]) == cutoff


async def test_stop_prevents_new_airport_requests(store):
    import asyncio

    from premetar.pws.service import collect

    stop = asyncio.Event()
    calls = []

    class StoppingProvider:
        name = "opensensemap"

        async def discover(self, latitude, longitude, radius):
            calls.append((latitude, longitude))
            stop.set()
            return []

    await collect(
        store, [StoppingProvider()], settings(), {"EDDM", "EHAM", "EPWA", "EGLL"}, 60, stop
    )
    assert len(calls) == 1


@pytest.mark.parametrize("method", ["median", "mean"])
async def test_precise_dwd_reference_separate_from_quantized_metar(store, method):
    from decimal import Decimal

    from premetar.model import Observation
    from premetar.pws.analysis import precise_reference_comparison

    packet = await captured(store, NOW - timedelta(hours=12))
    await store._call(store.discover, AIRPORT, STATION, packet)
    for index in range(10):
        event = NOW - timedelta(hours=10 - index)
        pws = await captured(store, event - timedelta(seconds=5))
        await store._call(
            store.ingest, STATION, make_reading(19.3, event - timedelta(seconds=30)), pws, False
        )
        official = await captured(store, event + timedelta(minutes=10))
        ref = Observation(
            station_icao="EDDM",
            source="dwd_10min",
            product_type="DWD_10MIN",
            event_time=event,
            temperature_c=Decimal("18.3"),
            temperature_precision=Decimal(".1"),
            raw_text="synthetic DWD reference",
        )
        await store.parse_and_save(
            official,
            b"original synthetic bytes",
            lambda body, anchor, reference=ref: [reference],
            {"EDDM"},
            False,
            False,
        )
    result = await store._call(
        precise_reference_comparison,
        store.connection,
        "EDDM",
        STATION.station_id,
        QCConfig(calibration_minimum=5, calibration_method=method),
        NOW,
    )
    assert result["reference_kind"] == "DWD_10MIN_APPROXIMATE_0.1C"
    assert result["sample_count"] == 10
    assert result["raw_bias_estimate_c"] == pytest.approx(1)
    assert result["calibrated_oos_sample_count"] == 5
    assert result["calibrated_oos_mae_c"] == pytest.approx(0)
    assert result["sensor_parity"] == "UNVERIFIED"
