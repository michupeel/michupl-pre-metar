"""Synthetic segment paths and collector-lock safety; no live processes touched."""

import json
from pathlib import Path

import pytest

from premetar.dashboard.segments import SegmentReader
from premetar.research import forecast_monitor


def test_segments_cannot_escape_research_directory(tmp_path: Path) -> None:
    base = tmp_path / "observations.sqlite3"
    base.touch()
    next_file = tmp_path / "next.sqlite3"
    next_file.touch()
    (tmp_path / "segments.json").write_text(
        json.dumps({"segments": ["../outside.sqlite3", "next.sqlite3", "next.sqlite3"]}),
        encoding="utf-8",
    )
    reader = SegmentReader(tmp_path / "weather", base, tmp_path / "trader")
    assert reader.paths() == [base.resolve(), next_file.resolve()]


@pytest.mark.asyncio
async def test_research_segment_validation_keeps_single_global_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "exp0013"
    root.mkdir()
    monkeypatch.setattr(forecast_monitor, "DATA", root)
    with pytest.raises(ValueError, match="inside EXP0013"):
        await forecast_monitor.watch(1, tmp_path / "outside.sqlite3")
    assert not (tmp_path / "outside.sqlite3").exists()
    assert not (root / "observer.lock").exists()
