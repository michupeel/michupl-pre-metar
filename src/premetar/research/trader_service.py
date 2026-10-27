"""Least-privilege, separately owned Windows logon task for public shadow research.

Preview is the default. No passwords, elevation or weather-task changes exist.
Registration and removal recheck ownership inside PowerShell immediately before
mutation, in addition to the Python preflight. Removing a task does not terminate
an already running monitor; its process lifecycle remains separately observable.
"""

import json
import platform
import subprocess
from pathlib import Path
from typing import Any

TASK_NAME = "MichuplPreMetar-TraderShadow-v1"
DESCRIPTION = "michupl-pre-metar EXP0011 public-only shadow monitor"


def configured_weather_database(root: Path) -> Path:
    config = root / "configs" / "experiments" / "continuous-v1.json"
    value = (
        json.loads(config.read_text(encoding="utf-8"))["database_path"]
        if config.is_file()
        else "data/continuous-v1.sqlite3"
    )
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Invalid continuous database configuration")
    path = Path(value)
    return (path if path.is_absolute() else root / path).resolve()


def configuration(root: Path) -> dict[str, Any]:
    directory = root.resolve()
    executable = directory / ".venv" / "Scripts" / "python.exe"
    arguments = subprocess.list2cmdline(
        [
            "-m",
            "premetar",
            "trader",
            "start",
            "--database",
            str(directory / "data" / "trader" / "monitor.sqlite3"),
            "--weather-database",
            str(configured_weather_database(directory)),
            "--poll-interval",
            "3",
        ]
    )
    return {
        "task_name": TASK_NAME,
        "description": DESCRIPTION,
        "execute": str(executable),
        "arguments": arguments,
        "working_directory": str(directory),
        "trigger": "CURRENT_USER_LOGON",
        "logon_type": "Interactive",
        "run_level": "Limited",
        "multiple_instances": "IgnoreNew",
        "restart_interval_seconds": 60,
        "restart_count": 3,
        "execution_time_limit_seconds": 0,
        "allow_battery": True,
        "before_login_available": False,
        "password_stored": False,
    }


def _ps(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def owns_task(task: dict[str, Any], config: dict[str, Any]) -> bool:
    """Exact project description and one matching launch action, no name-only trust."""
    actions = task.get("actions")
    if (
        task.get("description") != config["description"]
        or not isinstance(actions, list)
        or len(actions) != 1
    ):
        return False
    action = actions[0]
    if not isinstance(action, dict):
        return False
    return (
        str(action.get("execute", "")).casefold() == str(config["execute"]).casefold()
        and action.get("arguments") == config["arguments"]
        and str(action.get("working_directory", "")).casefold()
        == str(config["working_directory"]).casefold()
    )


def render_script(action: str, config: dict[str, Any]) -> str:
    if action not in {"install", "status", "remove"}:
        raise ValueError("Expected install, status or remove")
    header = "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            f"$taskName = {_ps(TASK_NAME)}",
            f"$description = {_ps(DESCRIPTION)}",
            f"$execute = {_ps(str(config['execute']))}",
            f"$arguments = {_ps(str(config['arguments']))}",
            f"$workingDirectory = {_ps(str(config['working_directory']))}",
            "$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue",
        ]
    )
    inspect = """
if ($null -eq $existing) {
    @{exists=$false; task_name=$taskName} | ConvertTo-Json -Compress -Depth 6
} else {
    $actions = @($existing.Actions | ForEach-Object {
        @{execute=$_.Execute; arguments=$_.Arguments; working_directory=$_.WorkingDirectory}
    })
    @{exists=$true; task_name=$taskName; description=$existing.Description;
      actions=$actions; state=[string]$existing.State;
      run_level=[string]$existing.Principal.RunLevel;
      logon_type=[string]$existing.Principal.LogonType} | ConvertTo-Json -Compress -Depth 6
}
"""
    if action == "status":
        return header + inspect
    guard = """
if ($null -ne $existing) {
    if (@($existing).Count -ne 1 -or $existing.Description -cne $description -or
        @($existing.Actions).Count -ne 1 -or
        $existing.Actions[0].Execute -ine $execute -or
        $existing.Actions[0].Arguments -cne $arguments -or
        $existing.Actions[0].WorkingDirectory -ine $workingDirectory) {
        throw 'TASK_OWNERSHIP_MISMATCH_REFUSED'
    }
}
"""
    if action == "remove":
        body = """
if ($null -ne $existing) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}
@{status='REMOVED_OR_ABSENT'; task_name=$taskName;
  running_process_not_terminated=$true} | ConvertTo-Json -Compress
"""
    else:
        body = """
if ($null -ne $existing) {
    @{status='ALREADY_INSTALLED'; task_name=$taskName} | ConvertTo-Json -Compress
} else {
    $currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $action = New-ScheduledTaskAction -Execute $execute -Argument $arguments -WorkingDirectory $workingDirectory
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
    $principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    $definition = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal `
        -Settings $settings -Description $description
    Register-ScheduledTask -TaskName $taskName -InputObject $definition | Out-Null
    @{status='INSTALLED'; task_name=$taskName} | ConvertTo-Json -Compress
}
"""
    return header + guard + body


def _run_powershell(script: str) -> dict[str, Any]:
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"Task Scheduler command failed (exit {result.returncode})")
    payload: Any = json.loads(result.stdout.strip())
    if not isinstance(payload, dict):
        raise RuntimeError("Invalid Task Scheduler response")
    return payload


def service(action: str, root: Path, preview: bool = True) -> dict[str, Any]:
    """Return reviewable configuration, or perform a guarded project-only task action.

    Installation registers a current-user logon trigger; it does not start a
    second monitor. Existing owned tasks are preserved without replacement.
    """
    config = configuration(root)
    script = render_script(action, config)
    if preview:
        return {
            "status": "PREVIEW",
            "action": action,
            "configuration": config,
            "powershell": script,
        }
    if platform.system() != "Windows":
        raise RuntimeError("Windows Task Scheduler is unavailable on this platform")
    existing = _run_powershell(render_script("status", config))
    if action == "status":
        return {
            **existing,
            "owned": owns_task(existing, config) if existing.get("exists") else False,
            "configuration": config,
        }
    if existing.get("exists") and not owns_task(existing, config):
        raise ValueError("TASK_OWNERSHIP_MISMATCH_REFUSED")
    if action == "install" and not Path(str(config["execute"])).is_file():
        raise FileNotFoundError(config["execute"])
    result = _run_powershell(script)
    verified = _run_powershell(render_script("status", config))
    if action == "install" and not (verified.get("exists") and owns_task(verified, config)):
        raise RuntimeError("Registered task launch configuration could not be verified")
    if action == "remove" and verified.get("exists"):
        raise RuntimeError("Task still registered after removal")
    return {**result, "verified": verified, "configuration": config}
