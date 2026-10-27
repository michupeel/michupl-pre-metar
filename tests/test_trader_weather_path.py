"""Never silently attach the historical standalone collector DB to live context."""

import json
from pathlib import Path

from premetar.research.trader_service import configuration, configured_weather_database


def test_default_is_continuous_not_legacy(tmp_path: Path) -> None:
    assert (
        configured_weather_database(tmp_path) == (tmp_path / "data/continuous-v1.sqlite3").resolve()
    )
    assert "premetar.sqlite3" not in configuration(tmp_path)["arguments"]


def test_task_and_cli_share_explicit_config_database(tmp_path: Path) -> None:
    folder = tmp_path / "configs/experiments"
    folder.mkdir(parents=True)
    (folder / "continuous-v1.json").write_text(
        json.dumps({"database_path": "data/real experiment.sqlite3"})
    )
    assert (
        configured_weather_database(tmp_path)
        == (tmp_path / "data/real experiment.sqlite3").resolve()
    )
    assert str(configured_weather_database(tmp_path)) in configuration(tmp_path)["arguments"]
