"""Recorded public schemas, isolated mock requests; no external traffic in tests."""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from premetar.research.battle_store import read_battle
from premetar.research.settlement_rules import parse_rules
from premetar.research.settlement_truth import (
    Evidence,
    audit_day,
    canonical,
    export_truth,
    normalize_archived_hourly,
    source_evidence,
)

FIXTURE = Path(__file__).parent / "fixtures/settlement"


def test_official_reproduction_idempotent_and_backfilled_receipts(tmp_path):
    market = json.loads((FIXTURE / "epwa_20261023_market.json").read_text())
    reports = json.loads((FIXTURE / "epwa_20261023_awc.json").read_bytes())
    requests = []

    def handler(request):
        requests.append(str(request.url))
        if request.url.host == "gamma-api.polymarket.com":
            return httpx.Response(200, json=[market])
        if request.url.params.get("format") == "json":
            return httpx.Response(200, json=reports)
        return httpx.Response(200, text="\n".join(r["rawOb"] for r in reports))

    evidence = Evidence(tmp_path)
    evidence.last_request = -100
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        target = audit_day(evidence, client, date(2026, 10, 23))
        assert target["classification"] == "VERIFIED_SOURCE_AND_MARKET"
        assert target["integer_outcome"] == 14 and target["qualifying_maximum_c"] == 14
        assert target["historical_source_state_at_resolution"] == "NOT_ARCHIVED"
        assert not target["source_cutoff_certified"]
        before = len(read_battle(tmp_path / "journal"))
        assert audit_day(evidence, client, date(2026, 10, 23)) == target
        assert len(read_battle(tmp_path / "journal")) == before and len(requests) == 3
    assert evidence.store.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    evidence.close()


def test_gap_in_expected_schedule_prevents_full_verification():
    rules = parse_rules(json.loads((FIXTURE / "epwa_20261023_market.json").read_text()))
    rows = json.loads((FIXTURE / "epwa_20261023_awc.json").read_bytes())
    removed = next(r for r in rows if r["rawOb"].startswith("METAR EPWA 231200Z"))
    _, certificate = source_evidence(
        date(2026, 10, 23),
        rules,
        [r for r in rows if r != removed],
        dict(url="https://aviationweather.gov/api/data/metar?ids=EPWA", sha256="a" * 64),
    )
    assert not certificate["coverage_complete"]
    assert "2026-10-23T12:00:00+00:00" in certificate["missing_nominal_times"]


@pytest.mark.parametrize(
    "url",
    [
        "http://aviationweather.gov/api/data/metar",
        "https://evil.test/a",
        "https://aviationweather.gov.evil.test/api/data/metar",
        "https://u:p@aviationweather.gov/api/data/metar",
        "https://aviationweather.gov/private",
    ],
)
def test_source_allowlist(url):
    with pytest.raises(ValueError):
        canonical(url)


def test_raw_error_cached_and_hash_checked(tmp_path):
    e = Evidence(tmp_path)
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(429, json={"error": "rate"}))
    ) as c:
        with pytest.raises(ValueError, match="429"):
            e.get(c, "https://aviationweather.gov/api/data/metar", {"ids": "EPWA"})
    assert read_battle(tmp_path / "journal")[0]["kind"] == "HTTP_CAPTURE"
    capture = next(iter(e.state["captures"].values()))
    (e.raw / capture["raw_file"]).write_text("corrupt")
    with httpx.Client() as c:
        with pytest.raises(ValueError, match="hash"):
            e.get(c, capture["url"])
    e.close()


def test_hourly_archives_never_invent_daily_tmax_or_publication():
    r = dict(
        hourly_units={"time": "unixtime", "temperature_2m_icon_global": "°C"},
        hourly={"time": [1792627200, 1792630800], "temperature_2m_icon_global": [11.1, 11.2]},
    )
    result = normalize_archived_hourly(r, "icon_global", "2026-10-29T12:00:00Z")
    assert result["days"] == [] and result["points"][1]["temperature_c"] == 11.2
    assert "initialization_time" not in result and "publication_time" not in result


def test_fixed_export_reproducible(tmp_path):
    r = dict(
        published_at="2026-10-29T12:00:00Z",
        scope="RETROSPECTIVE",
        targets=[],
        classification_counts={},
    )
    export_truth(r, tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    export_truth(r, tmp_path)
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}
