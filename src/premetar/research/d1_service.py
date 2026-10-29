"""Owned, least-privilege logon startup for EXP0016; never restarts a monitor.

Preview is default for mutations. The existing weather/trader/battle tasks are
not referenced by any mutating operation. No passwords or elevation are used.
"""

import argparse
import asyncio
import contextlib
import io
import json
import logging
import logging.handlers
import platform
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from premetar.continuous.locking import alive
from premetar.research.trader_service import _ps as quote_ps
from premetar.research.trader_service import _run_powershell as run_powershell
from premetar.research.trader_service import owns_task

TASK_NAME = "MichuplPreMetar-D1Research-v1"
DESCRIPTION = "michupl-pre-metar EXP0016 public-only D1 research observer"
ROOT = Path(__file__).resolve().parents[3]
NAMESPACE = "http://schemas.microsoft.com/windows/2004/02/mit/task"


def configuration(root: Path) -> dict[str, Any]:
    directory = root.resolve()
    return dict(
        task_name=TASK_NAME,
        description=DESCRIPTION,
        execute=str(directory / ".venv" / "Scripts" / "python.exe"),
        arguments="-m premetar.research.d1_service run",
        working_directory=str(directory),
        trigger="CURRENT_USER_LOGON",
        logon_type="Interactive",
        run_level="Limited",
        multiple_instances="IgnoreNew",
        restart_interval_seconds=60,
        restart_count=3,
        execution_time_limit_seconds=0,
        allow_battery=True,
        before_login_available=False,
        password_stored=False,
        starts_immediately_on_install=False,
        logs=str(directory / "logs" / "epwa-d1-service.log"),
    )


def render_xml(config: dict[str, Any], user_id: str = "CURRENT_USER_AT_INSTALL") -> str:
    """Auditable equivalent XML preview; registration uses native PS cmdlets."""
    ET.register_namespace("", NAMESPACE)

    def element(parent: ET.Element, name: str, text: str | None = None) -> ET.Element:
        child = ET.SubElement(parent, f"{{{NAMESPACE}}}{name}")
        child.text = text
        return child

    task = ET.Element(f"{{{NAMESPACE}}}Task", version="1.4")
    element(element(task, "RegistrationInfo"), "Description", str(config["description"]))
    trigger = element(element(task, "Triggers"), "LogonTrigger")
    element(trigger, "Enabled", "true")
    element(trigger, "UserId", user_id)
    principal = element(element(task, "Principals"), "Principal")
    principal.set("id", "Author")
    element(principal, "UserId", user_id)
    element(principal, "LogonType", "InteractiveToken")
    element(principal, "RunLevel", "LeastPrivilege")
    settings = element(task, "Settings")
    for key, value in (
        ("MultipleInstancesPolicy", "IgnoreNew"),
        ("DisallowStartIfOnBatteries", "false"),
        ("StopIfGoingOnBatteries", "false"),
        ("StartWhenAvailable", "true"),
        ("ExecutionTimeLimit", "PT0S"),
    ):
        element(settings, key, value)
    restart = element(settings, "RestartOnFailure")
    element(restart, "Interval", "PT1M")
    element(restart, "Count", "3")
    actions = element(task, "Actions")
    actions.set("Context", "Author")
    execution = element(actions, "Exec")
    element(execution, "Command", str(config["execute"]))
    element(execution, "Arguments", str(config["arguments"]))
    element(execution, "WorkingDirectory", str(config["working_directory"]))
    return ET.tostring(task, encoding="unicode")


def render_script(action: str, config: dict[str, Any]) -> str:
    if action not in {"install", "status", "remove"}:
        raise ValueError("Expected install, status or remove")
    header = "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            f"$taskName = {quote_ps(str(config['task_name']))}",
            f"$description = {quote_ps(str(config['description']))}",
            f"$execute = {quote_ps(str(config['execute']))}",
            f"$arguments = {quote_ps(str(config['arguments']))}",
            f"$workingDirectory = {quote_ps(str(config['working_directory']))}",
            "$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue",
        ]
    )
    if action == "status":
        return (
            header
            + """
if ($null -eq $existing) {
    @{exists=$false; task_name=$taskName} | ConvertTo-Json -Compress -Depth 8
} else {
    $actions = @($existing.Actions | ForEach-Object {
        @{execute=$_.Execute; arguments=$_.Arguments; working_directory=$_.WorkingDirectory}
    })
    $info = Get-ScheduledTaskInfo -TaskName $taskName
    @{exists=$true; task_name=$taskName; description=$existing.Description;
      actions=$actions; state=[string]$existing.State;
      run_level=[string]$existing.Principal.RunLevel;
      logon_type=[string]$existing.Principal.LogonType;
      user_id=[string]$existing.Principal.UserId;
      multiple_instances=[string]$existing.Settings.MultipleInstances;
      restart_count=[int]$existing.Settings.RestartCount;
      restart_interval=[string]$existing.Settings.RestartInterval;
      execution_time_limit=[string]$existing.Settings.ExecutionTimeLimit;
      trigger_types=@($existing.Triggers | ForEach-Object {$_.CimClass.CimClassName});
      last_run_result=[long]$info.LastTaskResult;
      last_run_time=[string]$info.LastRunTime} | ConvertTo-Json -Compress -Depth 8
}
"""
        )
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
if ($null -ne $existing) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false }
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
    @{status='INSTALLED'; task_name=$taskName; started=$false} | ConvertTo-Json -Compress
}
"""
    return header + guard + body


def verified_settings(task: dict[str, Any]) -> bool:
    return bool(
        task.get("run_level") == "Limited"
        and task.get("logon_type") == "Interactive"
        and task.get("multiple_instances") == "IgnoreNew"
        and task.get("restart_count") == 3
        and task.get("restart_interval") == "PT1M"
        and task.get("execution_time_limit") == "PT0S"
        and task.get("trigger_types") == ["MSFT_TaskLogonTrigger"]
    )


def service(action: str, root: Path = ROOT, preview: bool = True) -> dict[str, Any]:
    config = configuration(root)
    script = render_script(action, config)
    if preview:
        return dict(
            status="PREVIEW",
            action=action,
            configuration=config,
            powershell=script,
            equivalent_xml=render_xml(config),
        )
    if platform.system() != "Windows":
        raise RuntimeError("Windows Task Scheduler unavailable")
    existing = run_powershell(render_script("status", config))
    if action == "status":
        return dict(
            existing,
            owned=owns_task(existing, config) if existing.get("exists") else False,
            settings_verified=verified_settings(existing),
            configuration=config,
        )
    if existing.get("exists") and not owns_task(existing, config):
        raise ValueError("TASK_OWNERSHIP_MISMATCH_REFUSED")
    if action == "install" and not Path(config["execute"]).is_file():
        raise FileNotFoundError(config["execute"])
    result = run_powershell(script)
    checked = run_powershell(render_script("status", config))
    if action == "install" and not (
        checked.get("exists") and owns_task(checked, config) and verified_settings(checked)
    ):
        raise RuntimeError(
            "Registered task launch/settings verification failed; no task was started"
        )
    if action == "remove" and checked.get("exists"):
        raise RuntimeError("Task still registered after removal")
    return dict(result, verified=checked, configuration=config)


def lock_state(directory: Path) -> str:
    """Read only after the OS-locked byte; unknown ownership always fails closed."""
    path = directory / "monitor.lock"
    try:
        with path.open("r", encoding="utf-8") as handle:
            handle.seek(1)
            info = json.load(handle)
    except FileNotFoundError:
        return "ABSENT"
    except (OSError, ValueError, TypeError):
        return "UNKNOWN_LOCK"
    try:
        if (
            info.get("owner") != "michupl-pre-metar"
            or not isinstance(info["pid"], int)
            or info["pid"] <= 0
        ):
            return "UNKNOWN_LOCK"
        return "ALREADY_RUNNING" if alive(info["pid"]) else "RECOVERABLE_DEAD_OWNER"
    except (KeyError, TypeError, AttributeError):
        return "UNKNOWN_LOCK"


class _LogStream(io.TextIOBase):
    def __init__(self, logger: logging.Logger, level: int) -> None:
        self.logger, self.level = logger, level

    def write(self, text: str) -> int:
        if text.strip():
            self.logger.log(self.level, "%s", text.rstrip())
        return len(text)


def run_observer(root: Path = ROOT) -> dict[str, Any]:
    """Task entrypoint: existing owner is a successful no-op, never a restart."""
    directory = root.resolve() / "data" / "research" / "epwa_d1"
    if (directory / "stop.request").exists():
        return dict(status="STOP_REQUEST_RESPECTED", started=False)
    state = lock_state(directory)
    if state == "ALREADY_RUNNING":
        return dict(status=state, started=False)
    if state == "UNKNOWN_LOCK":
        raise RuntimeError("UNKNOWN_LOCK_REFUSED")
    # No temporary lock is released before watch: its existing OS lock closes
    # the startup race and performs the repository's conservative crash recovery.
    from premetar.research import d1_monitor

    if directory != d1_monitor.DIRECTORY.resolve():
        raise ValueError("Observer root differs from installed project")
    logs = root.resolve() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("premetar.d1_service")
    logger.setLevel(logging.INFO)
    handler = logging.handlers.RotatingFileHandler(
        logs / "epwa-d1-service.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    try:
        logger.info("Task launch; previous lock state=%s", state)
        with (
            contextlib.redirect_stdout(_LogStream(logger, logging.INFO)),
            contextlib.redirect_stderr(_LogStream(logger, logging.WARNING)),
        ):
            try:
                asyncio.run(d1_monitor.watch())
            except FileExistsError:
                if lock_state(directory) == "ALREADY_RUNNING":
                    return dict(status="ALREADY_RUNNING", started=False)
                raise RuntimeError("STARTUP_LOCK_RACE_UNVERIFIED") from None
        logger.info("Observer exited normally")
        return dict(status="OBSERVER_EXITED", started=True)
    except BaseException as error:
        logger.error("Observer failure; exception_class=%s", type(error).__name__)
        raise
    finally:
        logger.removeHandler(handler)
        handler.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["preview", "install", "status", "remove", "run"])
    parser.add_argument(
        "--apply", action="store_true", help="Apply install/remove; otherwise preview"
    )
    args = parser.parse_args()
    if args.action == "run":
        result = run_observer()
    elif args.action == "preview":
        result = service("install")
    else:
        result = service(args.action, preview=args.action != "status" and not args.apply)
    print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
