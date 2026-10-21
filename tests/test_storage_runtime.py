import base64
import hashlib
import json
import sqlite3
import time
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from premetar.analysis import analyze
from premetar.cli import app
from premetar.collector import collect, retry_after
from premetar.model import utc_now
from premetar.parsers import parse_awc, parse_metar
from premetar.sources import HttpSource
from premetar.store import Store

TAC = "METAR EDDM 211250Z AUTO 24010KT 9999 FEW020 18/12 Q1013 NOSIG"


def packet(source="awc"):
    now = utc_now().isoformat()
    return {
        "source": source,
        "request_url": "https://example.test/?token=secret",
        "http_status": 200,
        "headers": {"Set-Cookie": "secret", "ETag": "abc"},
        "request_start": now,
        "request_end": now,
        "received_at": now,
        "monotonic_ns": time.monotonic_ns(),
        "request_start_monotonic_ns": time.monotonic_ns() - 100,
    }


@pytest.mark.asyncio
async def test_raw_first_receipts_restart_and_parser_failure(tmp_path):
    db, raw = tmp_path / "test.db", tmp_path / "raw"
    store = Store(db, raw, "r1")
    await store.open({"test": True}, {"awc": 60, "knmi_metar": 60})
    body = b"original synthetic body"
    captured = await store.capture(packet(), body)

    def parser(data, anchor):
        assert data == body
        envelope = json.loads(Path(captured["path"]).read_text())
        assert base64.b64decode(envelope["body_base64"]) == body
        assert envelope["sha256"] == hashlib.sha256(body).hexdigest()
        assert "secret" not in Path(captured["path"]).read_text()
        return [parse_metar(TAC, anchor, "awc")]

    await store.parse_and_save(captured, body, parser, {"EDDM"}, True, False)
    repeat = await store.capture(packet(), body)
    await store.parse_and_save(repeat, body, parser, {"EDDM"}, False, False)
    other = await store.capture(packet("knmi_metar"), body)
    await store.parse_and_save(
        other,
        body,
        lambda _, anchor: [parse_metar(TAC + "=", anchor, "knmi_metar")],
        {"EDDM"},
        True,
        False,
    )
    broken = await store.capture(packet(), b"unparseable original")

    def fail(_, __):
        raise ValueError("synthetic parser failure")

    with pytest.raises(ValueError):
        await store.parse_and_save(broken, b"unparseable original", fail, {"EDDM"}, False, False)
    await store.error("awc", "ValueError", broken["id"])
    await store.close("test")
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT count(*) FROM observations").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM report_receipts").fetchone()[0] == 3
        assert connection.execute("SELECT count(*) FROM canonical_reports").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM raw_payloads").fetchone()[0] == 4
        assert (
            connection.execute(
                "SELECT startup_censored FROM observations WHERE source='awc'"
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute("SELECT source_publish_time FROM observations LIMIT 1").fetchone()[0]
            is None
        )
    restarted = Store(db, raw, "r2")
    await restarted.open({"test": "restart"}, {"awc": 60})
    await restarted.close("test")
    result = analyze(db, tmp_path / "reports")
    assert result["paired_rows"] == 0
    assert (tmp_path / "reports/pairs.parquet").is_file()
    status = CliRunner().invoke(app, ["status", "--database", str(db), "--as-json"])
    assert status.exit_code == 0, status.output
    assert json.loads(status.output)["counts"]["report_receipts"] == 3


@pytest.mark.asyncio
async def test_one_failed_source_does_not_kill_others(tmp_path, monkeypatch):
    monkeypatch.setattr("premetar.collector.clock_status", lambda: {"warning": "synthetic test"})

    def handler(request):
        if request.url.host == "bad.test":
            return httpx.Response(403, content=b"disabled test source")
        return httpx.Response(200, json=[{"icaoId": "EDDM", "rawOb": TAC}])

    sources = [
        HttpSource("bad", "https://bad.test/", frozenset({"EDDM"}), parse_awc),
        HttpSource("awc", "https://good.test/", frozenset({"EDDM"}), parse_awc),
    ]
    await collect(
        sources,
        {"EDDM"},
        tmp_path / "db",
        tmp_path / "raw",
        0.1,
        False,
        httpx.MockTransport(handler),
    )
    with sqlite3.connect(tmp_path / "db") as connection:
        assert (
            connection.execute("SELECT count(*) FROM observations WHERE source='awc'").fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT last_error FROM source_health WHERE source='bad'"
            ).fetchone()[0]
            == "HTTP_403_adapter_disabled"
        )
        assert (
            connection.execute("SELECT exit_reason FROM runs").fetchone()[0] == "duration_complete"
        )
    assert not (tmp_path / "db.lock").exists()


def test_rate_limit_retry_after():
    now = utc_now()
    assert retry_after("120", now) == 120
    assert retry_after("invalid", now) == 0


def test_cli_disabled_source_is_explicit():
    result = CliRunner().invoke(app, ["collect", "--sources", "metar_ws", "--duration", "1"])
    assert result.exit_code != 0 and "disabled" in result.output


@pytest.mark.asyncio
async def test_existing_lock_does_not_write_phantom_run(tmp_path, monkeypatch):
    monkeypatch.setattr("premetar.collector.clock_status", lambda: {"warning": "synthetic test"})
    database = tmp_path / "db"
    lock = tmp_path / "db.lock"
    lock.write_text("existing test owner")
    source = HttpSource("awc", "https://example.test/", frozenset({"EDDM"}), parse_awc)
    with pytest.raises(FileExistsError):
        await collect([source], {"EDDM"}, database, tmp_path / "raw", 0.1, False)
    assert lock.read_text() == "existing test owner"
    assert not database.exists()
