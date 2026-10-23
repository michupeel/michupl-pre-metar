"""No inference request or credential access in these development-client tests."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def worker():
    spec = importlib.util.spec_from_file_location(
        "qwen_worker", Path(__file__).parents[1] / "scripts/dev/qwen_worker.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_qwen_disabled_failure_log_has_no_secret(monkeypatch, tmp_path, capsys):
    module = worker()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setenv("LOCAL_LLM_ENABLED", "false")
    monkeypatch.setenv("LOCAL_LLM_API_KEY", "never-log-this-key")
    monkeypatch.setattr(sys, "argv", ["qwen_worker", "health"])
    assert module.main() == 1
    text = (tmp_path / "reports/dev/qwen_delegation.jsonl").read_text()
    assert "never-log-this-key" not in text + capsys.readouterr().out
    assert json.loads(text)["status"] == "error"


def test_qwen_only_private_endpoint(monkeypatch):
    module = worker()
    monkeypatch.setattr(
        module.socket, "getaddrinfo", lambda *args: [(None, None, None, None, ("8.8.8.8", 80))]
    )
    with pytest.raises(ValueError):
        module.private_endpoint("http://example.test/v1")
    with pytest.raises(ValueError):
        module.private_endpoint("http://user:secret@localhost/v1")
    monkeypatch.setattr(
        module.socket, "getaddrinfo", lambda *args: [(None, None, None, None, ("127.0.0.1", 8888))]
    )
    assert module.private_endpoint("http://localhost:8888/v1/") == "http://localhost:8888/v1"
