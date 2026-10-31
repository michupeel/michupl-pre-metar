"""Reproducible empty research reports, synthetic immutable source only."""

import runpy
from pathlib import Path

from premetar.research.trader_store import TraderStore


def test_empty_fixed_cutoff_regeneration_is_deterministic(tmp_path):
    root = Path(__file__).resolve().parents[1]
    analyze = runpy.run_path(str(root / "scripts/research/hightemptation_entry_reconstruction.py"))[
        "analyze"
    ]
    source = tmp_path / "source.sqlite3"
    store = TraderStore(source)
    store.append("RAW", dict(test="SYNTHETIC_ONLY"), "2026-10-31T00:00:00Z")
    store.close()
    a = analyze(1000, source, tmp_path / "absent", tmp_path / "a", maximum_id=1)
    b = analyze(1000, source, tmp_path / "absent", tmp_path / "b", maximum_id=1)
    assert a["summary"] == b["summary"]
    assert a["summary"]["entries"] == 0
    assert a["source_cutoff"] == b["source_cutoff"]
    assert (tmp_path / "a/exp0018_entry_features.csv").read_bytes() == (
        tmp_path / "b/exp0018_entry_features.csv"
    ).read_bytes()
