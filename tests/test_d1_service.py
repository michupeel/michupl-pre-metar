"""Synthetic scheduler/lock tests; never registers or stops a Windows task."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from premetar.research import d1_service as module
from premetar.research.battle_store import BattleStore, read_battle


def task(config):
    return dict(
        exists=True,
        description=config["description"],
        actions=[
            dict(
                execute=config["execute"],
                arguments=config["arguments"],
                working_directory=config["working_directory"],
            )
        ],
        run_level="Limited",
        logon_type="Interactive",
        multiple_instances="IgnoreNew",
        restart_count=3,
        restart_interval="PT1M",
        execution_time_limit="PT0S",
        trigger_types=["MSFT_TaskLogonTrigger"],
    )


def lock(directory: Path, payload):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "monitor.lock").write_text(" " + json.dumps(payload), encoding="utf-8")


def test_preview_is_default_and_has_no_side_effect(tmp_path, monkeypatch):
    monkeypatch.setattr(
        module, "run_powershell", lambda _: pytest.fail("No registration in preview")
    )
    result = module.service("install", tmp_path)
    assert result["status"] == "PREVIEW"
    assert result["configuration"]["task_name"] == "MichuplPreMetar-D1Research-v1"
    assert result["configuration"]["starts_immediately_on_install"] is False
    assert result["configuration"]["password_stored"] is False
    assert not list(tmp_path.iterdir())


def test_paths_spaces_apostrophes_xml_escape_and_no_shell_wrapping(tmp_path):
    config = module.configuration(tmp_path / "A & B's folder")
    document = ET.fromstring(module.render_xml(config, "DOMAIN\\User & Name"))
    ns = {"t": module.NAMESPACE}
    assert document.find("t:Actions/t:Exec/t:Command", ns).text == config["execute"]
    assert (
        document.find("t:Actions/t:Exec/t:WorkingDirectory", ns).text == config["working_directory"]
    )
    assert (
        document.find("t:Actions/t:Exec/t:Arguments", ns).text
        == "-m premetar.research.d1_service run"
    )
    script = module.render_script("install", config)
    assert "B''s folder" in script
    assert "powershell.exe" not in config["execute"]
    assert "ExecutionPolicy" not in script and "-Password" not in script


def test_definition_least_privilege_restart_and_ignore_new(tmp_path):
    config = module.configuration(tmp_path)
    xml = ET.fromstring(module.render_xml(config))
    ns = {"t": module.NAMESPACE}
    assert xml.find("t:Settings/t:MultipleInstancesPolicy", ns).text == "IgnoreNew"
    assert xml.find("t:Settings/t:RestartOnFailure/t:Count", ns).text == "3"
    assert xml.find("t:Settings/t:RestartOnFailure/t:Interval", ns).text == "PT1M"
    assert xml.find("t:Principals/t:Principal/t:RunLevel", ns).text == "LeastPrivilege"
    assert xml.find("t:Triggers/t:LogonTrigger", ns) is not None
    assert xml.find("t:Triggers/t:BootTrigger", ns) is None
    assert module.verified_settings(task(config))


@pytest.mark.parametrize("changed", ["description", "execute", "arguments", "working_directory"])
def test_unrelated_task_never_overwritten_or_removed(tmp_path, monkeypatch, changed):
    config = module.configuration(tmp_path)
    existing = task(config)
    if changed == "description":
        existing[changed] = "somebody else"
    else:
        existing["actions"][0][changed] = "somebody else"
    calls = []
    monkeypatch.setattr(module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(module, "run_powershell", lambda script: calls.append(script) or existing)
    for operation in ("install", "remove"):
        with pytest.raises(ValueError, match="OWNERSHIP"):
            module.service(operation, tmp_path, preview=False)
    assert len(calls) == 2
    assert all(
        "Unregister-ScheduledTask" not in script
        and "Register-ScheduledTask -TaskName" not in script
        for script in calls
    )


def test_install_registers_and_verifies_without_start(tmp_path, monkeypatch):
    config = module.configuration(tmp_path)
    executable = Path(config["execute"])
    executable.parent.mkdir(parents=True)
    executable.touch()
    responses = iter([dict(exists=False), dict(status="INSTALLED"), task(config)])
    calls = []
    monkeypatch.setattr(module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(module, "run_powershell", lambda s: calls.append(s) or next(responses))
    result = module.service("install", tmp_path, preview=False)
    assert result["status"] == "INSTALLED" and result["verified"]["exists"]
    assert all("Start-ScheduledTask" not in s and "Stop-ScheduledTask" not in s for s in calls)
    assert "-Force" not in calls[1]


def test_wrong_settings_are_not_silently_promoted(tmp_path, monkeypatch):
    config = module.configuration(tmp_path)
    executable = Path(config["execute"])
    executable.parent.mkdir(parents=True)
    executable.touch()
    bad = task(config)
    bad["run_level"] = "Highest"
    responses = iter([dict(exists=False), dict(status="INSTALLED"), bad])
    monkeypatch.setattr(module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(module, "run_powershell", lambda _: next(responses))
    with pytest.raises(RuntimeError, match="verification failed"):
        module.service("install", tmp_path, preview=False)


def test_safe_remove_does_not_stop_process(tmp_path, monkeypatch):
    config = module.configuration(tmp_path)
    responses = iter([task(config), dict(status="REMOVED_OR_ABSENT"), dict(exists=False)])
    monkeypatch.setattr(module.platform, "system", lambda: "Windows")
    calls = []
    monkeypatch.setattr(module, "run_powershell", lambda s: calls.append(s) or next(responses))
    assert module.service("remove", tmp_path, preview=False)["verified"]["exists"] is False
    assert "Unregister-ScheduledTask" in calls[1]
    assert "Stop-Process" not in calls[1] and "Stop-ScheduledTask" not in calls[1]


def test_existing_observer_is_successful_noop(tmp_path, monkeypatch):
    directory = tmp_path / "data/research/epwa_d1"
    lock(directory, dict(owner="michupl-pre-metar", pid=123))
    monkeypatch.setattr(module, "alive", lambda pid: True)
    assert module.run_observer(tmp_path) == dict(status="ALREADY_RUNNING", started=False)
    assert not (tmp_path / "logs").exists()


def test_stop_request_is_respected(tmp_path):
    directory = tmp_path / "data/research/epwa_d1"
    directory.mkdir(parents=True)
    (directory / "stop.request").write_text("stop")
    assert module.run_observer(tmp_path) == dict(status="STOP_REQUEST_RESPECTED", started=False)


@pytest.mark.parametrize(
    "payload",
    [{"owner": "other", "pid": 1}, {"owner": "michupl-pre-metar", "pid": 0}, [], {"pid": 1}],
)
def test_unknown_lock_blocks_without_modification(tmp_path, payload):
    directory = tmp_path / "data/research/epwa_d1"
    lock(directory, payload)
    before = (directory / "monitor.lock").read_bytes()
    with pytest.raises(RuntimeError, match="UNKNOWN_LOCK"):
        module.run_observer(tmp_path)
    assert (directory / "monitor.lock").read_bytes() == before


def test_dead_owner_recovery_preserves_history(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from premetar.continuous import locking
    from premetar.research import d1_monitor

    directory = tmp_path / "data/research/epwa_d1"
    store = BattleStore(directory, min_free_bytes=0)
    store.commit([dict(kind="PRIOR_EVIDENCE", payload=dict(kept=True))], {}, {}, datetime.now(UTC))
    store.close()
    lock(directory, dict(owner="michupl-pre-metar", pid=99999999))
    monkeypatch.setattr(module, "alive", lambda pid: False)
    monkeypatch.setattr(locking, "alive", lambda pid: False)
    monkeypatch.setattr(d1_monitor, "DIRECTORY", directory)

    async def bounded(self, seconds):
        return None

    monkeypatch.setattr(d1_monitor.D1Monitor, "run", bounded)
    result = module.run_observer(tmp_path)
    assert result == dict(status="OBSERVER_EXITED", started=True)
    assert sum(e["kind"] == "PRIOR_EVIDENCE" for e in read_battle(directory)) == 1
    assert not (directory / "monitor.lock").exists()
    assert (tmp_path / "logs/epwa-d1-service.log").exists()


def test_race_existing_owner_does_not_trigger_restart(tmp_path, monkeypatch):
    from premetar.research import d1_monitor

    directory = tmp_path / "data/research/epwa_d1"
    directory.mkdir(parents=True)
    monkeypatch.setattr(d1_monitor, "DIRECTORY", directory)
    monkeypatch.setattr(module, "alive", lambda pid: True)

    async def competing_watch():
        lock(directory, dict(owner="michupl-pre-metar", pid=123))
        raise FileExistsError("race")

    monkeypatch.setattr(d1_monitor, "watch", competing_watch)
    assert module.run_observer(tmp_path) == dict(status="ALREADY_RUNNING", started=False)
