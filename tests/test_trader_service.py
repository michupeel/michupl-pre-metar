"""Synthetic scheduler responses; these tests never register Windows tasks."""

from pathlib import Path
from typing import Any

import pytest

from premetar.research import trader_service as module
from premetar.research.trader_service import (
    DESCRIPTION,
    TASK_NAME,
    configuration,
    owns_task,
    render_script,
    service,
)


def owned(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "exists": True,
        "description": DESCRIPTION,
        "actions": [
            {
                "execute": config["execute"],
                "arguments": config["arguments"],
                "working_directory": config["working_directory"],
            }
        ],
    }


def test_preview_quotes_paths_and_has_independent_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(_: str) -> dict[str, Any]:
        raise AssertionError("Preview must not execute PowerShell")

    monkeypatch.setattr(module, "_run_powershell", forbidden)
    root = tmp_path / "research repo's space"
    result = service("install", root)
    config = result["configuration"]
    assert result["status"] == "PREVIEW"
    assert config["task_name"] == TASK_NAME
    assert "Continuous" not in TASK_NAME
    assert Path(config["execute"]).is_absolute()
    assert '"' in config["arguments"]
    assert "--weather-database" in config["arguments"]
    assert "--database" in config["arguments"]
    assert "repo''s space" in result["powershell"]
    assert root.resolve() == Path(config["working_directory"])


def test_settings_are_passwordless_limited_and_single_instance(tmp_path: Path) -> None:
    script = render_script("install", configuration(tmp_path))
    for expected in [
        "-AtLogOn",
        "-LogonType Interactive",
        "-RunLevel Limited",
        "-MultipleInstances IgnoreNew",
        "-RestartCount 3",
        "New-TimeSpan -Minutes 1",
        "[TimeSpan]::Zero",
        "-AllowStartIfOnBatteries",
        "-DontStopIfGoingOnBatteries",
    ]:
        assert expected in script
    assert "-Password" not in script
    assert "-Force" not in script
    assert "RunLevel Highest" not in script
    assert "Start-ScheduledTask" not in script
    assert "Stop-ScheduledTask" not in script


def test_ownership_requires_description_and_exact_single_action(tmp_path: Path) -> None:
    config = configuration(tmp_path)
    task = owned(config)
    assert owns_task(task, config)
    assert not owns_task({**task, "description": "someone else"}, config)
    assert not owns_task({**task, "actions": task["actions"] * 2}, config)
    for field in ["execute", "arguments", "working_directory"]:
        changed = owned(config)
        changed["actions"][0][field] = "unrelated"
        assert not owns_task(changed, config)


@pytest.mark.parametrize("action", ["install", "remove"])
def test_unrelated_task_refused_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    scripts: list[str] = []

    def fake(script: str) -> dict[str, Any]:
        scripts.append(script)
        return {"exists": True, "description": "other application", "actions": []}

    monkeypatch.setattr(module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(module, "_run_powershell", fake)
    with pytest.raises(ValueError, match="OWNERSHIP_MISMATCH"):
        service(action, tmp_path, preview=False)
    assert len(scripts) == 1
    assert "Register-ScheduledTask" not in scripts[0]
    assert "Unregister-ScheduledTask" not in scripts[0]


def test_install_checks_again_inside_powershell_and_verifies_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = configuration(tmp_path)
    executable = Path(config["execute"])
    executable.parent.mkdir(parents=True)
    executable.write_text("synthetic executable marker")
    responses = iter([{"exists": False}, {"status": "INSTALLED"}, owned(config)])
    scripts: list[str] = []

    def fake(script: str) -> dict[str, Any]:
        scripts.append(script)
        return next(responses)

    monkeypatch.setattr(module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(module, "_run_powershell", fake)
    assert service("install", tmp_path, preview=False)["status"] == "INSTALLED"
    assert len(scripts) == 3
    assert "TASK_OWNERSHIP_MISMATCH_REFUSED" in scripts[1]
    assert scripts[1].index("TASK_OWNERSHIP_MISMATCH_REFUSED") < scripts[1].index(
        "Register-ScheduledTask"
    )


def test_status_is_read_only_even_when_task_is_unrelated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scripts: list[str] = []

    def fake(script: str) -> dict[str, Any]:
        scripts.append(script)
        return {"exists": True, "description": "unrelated", "actions": []}

    monkeypatch.setattr(module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(module, "_run_powershell", fake)
    assert service("status", tmp_path, preview=False)["owned"] is False
    assert len(scripts) == 1
    assert "Register-ScheduledTask" not in scripts[0]
    assert "Unregister-ScheduledTask" not in scripts[0]


def test_remove_only_owned_task_and_does_not_stop_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = configuration(tmp_path)
    responses = iter([owned(config), {"status": "REMOVED_OR_ABSENT"}, {"exists": False}])
    scripts: list[str] = []

    def fake(script: str) -> dict[str, Any]:
        scripts.append(script)
        return next(responses)

    monkeypatch.setattr(module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(module, "_run_powershell", fake)
    assert service("remove", tmp_path, preview=False)["status"] == "REMOVED_OR_ABSENT"
    assert "Unregister-ScheduledTask" in scripts[1]
    assert "Stop-ScheduledTask" not in scripts[1]
    assert "Stop-Process" not in scripts[1]


def test_non_windows_actual_action_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module.platform, "system", lambda: "Linux")
    with pytest.raises(RuntimeError, match="unavailable"):
        service("install", tmp_path, preview=False)


def test_unknown_action_never_runs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Expected"):
        service("start-unrelated-task", tmp_path)
