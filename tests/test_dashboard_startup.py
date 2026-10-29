"""Dashboard startup must work with pythonw's absent console streams."""

from pathlib import Path
from typing import Any

import pytest
import uvicorn

from premetar.dashboard import app


@pytest.mark.parametrize("console", [True, False])
def test_dashboard_logging_without_console(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, console: bool
) -> None:
    captured: dict[str, Any] = {}

    def capture(application: Any, **options: Any) -> None:
        captured.update(options)

    monkeypatch.setattr(app, "ROOT", tmp_path)
    monkeypatch.setattr(uvicorn, "run", capture)
    if not console:
        monkeypatch.setattr(app.sys, "stderr", None)
    app.run(8766)
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8766
    assert captured["access_log"] is False
    if console:
        assert "log_config" not in captured
    else:
        handler = captured["log_config"]["handlers"]["file"]
        assert handler["class"] == "logging.handlers.RotatingFileHandler"
        assert handler["maxBytes"] == 2_000_000
        assert handler["backupCount"] == 2
        assert handler["filename"] == str(tmp_path / "logs" / "dashboard.log")
