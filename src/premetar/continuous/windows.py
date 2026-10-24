"""Least-privilege, project-owned Windows logon task (no stored password)."""

import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

from defusedxml.ElementTree import fromstring

NAME = "MichuplPreMetar-Continuous-v1"
OWNER = "michupl-pre-metar continuous-v1"
NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"


def task_xml(python: str, root: str, config: str, sid: str) -> str:
    ET.register_namespace("", NS)

    def node(parent: ET.Element, name: str, value: str | None = None, **attrs: str) -> ET.Element:
        child = ET.SubElement(parent, "{" + NS + "}" + name, attrs)
        child.text = value
        return child

    task = ET.Element("{" + NS + "}Task", version="1.4")
    reg = node(task, "RegistrationInfo")
    node(reg, "Author", "michupl-pre-metar")
    node(reg, "Description", OWNER)
    triggers = node(task, "Triggers")
    trigger = node(triggers, "LogonTrigger")
    node(trigger, "Enabled", "true")
    node(trigger, "UserId", sid)
    principals = node(task, "Principals")
    principal = node(principals, "Principal", id="Author")
    node(principal, "UserId", sid)
    node(principal, "LogonType", "InteractiveToken")
    node(principal, "RunLevel", "LeastPrivilege")
    settings = node(task, "Settings")
    for name, value in {
        "MultipleInstancesPolicy": "IgnoreNew",
        "DisallowStartIfOnBatteries": "false",
        "StopIfGoingOnBatteries": "false",
        "AllowHardTerminate": "true",
        "StartWhenAvailable": "true",
        "Enabled": "true",
        "Hidden": "false",
        "ExecutionTimeLimit": "PT0S",
    }.items():
        node(settings, name, value)
    restart = node(settings, "RestartOnFailure")
    node(restart, "Interval", "PT1M")
    node(restart, "Count", "3")
    actions = node(task, "Actions", Context="Author")
    action = node(actions, "Exec")
    node(action, "Command", python)
    node(
        action,
        "Arguments",
        subprocess.list2cmdline(["-m", "premetar", "continuous", "start", "--config", config]),
    )
    node(action, "WorkingDirectory", root)
    return ET.tostring(task, encoding="unicode")


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=30, check=False)


def query() -> str | None:
    result = run(["schtasks", "/Query", "/TN", NAME, "/XML"])
    if result.returncode:
        # Only a verified absent task may be replaced by a fresh registration.
        check = run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "if (Get-ScheduledTask -ErrorAction Stop | Where-Object TaskName -eq '"
                + NAME
                + "') { exit 2 } else { exit 0 }",
            ]
        )
        if check.returncode:
            raise RuntimeError("Cannot verify scheduled task absence")
        return None
    return result.stdout


def owned(xml: str, python: str, root: str, config: str) -> bool:
    tree = fromstring(xml)

    def text(path: str) -> str | None:
        return tree.findtext(path, namespaces={"t": NS})

    expected = fromstring(task_xml(python, root, config, "unused"))
    return text("t:RegistrationInfo/t:Description") == OWNER and all(
        tree.findtext(path, namespaces={"t": NS}) == expected.findtext(path, namespaces={"t": NS})
        for path in (
            "t:Actions/t:Exec/t:Command",
            "t:Actions/t:Exec/t:Arguments",
            "t:Actions/t:Exec/t:WorkingDirectory",
        )
    )


def verified(
    xml: str,
    python: str,
    root: str,
    config: str,
    sid: str,
    *,
    account_name: str | None = None,
    effective_run_level: str | None = None,
) -> bool:
    tree = fromstring(xml)
    if not owned(xml, python, root, config):
        return False
    expected = {
        "t:Principals/t:Principal/t:UserId": sid,
        "t:Principals/t:Principal/t:LogonType": "InteractiveToken",
        "t:Settings/t:MultipleInstancesPolicy": "IgnoreNew",
        "t:Settings/t:ExecutionTimeLimit": "PT0S",
        "t:Settings/t:RestartOnFailure/t:Interval": "PT1M",
        "t:Settings/t:RestartOnFailure/t:Count": "3",
    }
    level = tree.findtext("t:Principals/t:Principal/t:RunLevel", namespaces={"t": NS})
    if level != "LeastPrivilege" and not (level is None and effective_run_level == "Limited"):
        return False
    trigger = tree.findtext("t:Triggers/t:LogonTrigger/t:UserId", namespaces={"t": NS})
    allowed = {sid.casefold()}
    if account_name:
        allowed.add(account_name.casefold())
    return bool(trigger and trigger.casefold() in allowed) and all(
        tree.findtext(path, namespaces={"t": NS}) == value for path, value in expected.items()
    )


def verify_registered(xml: str, python: str, root: str, config: str, sid: str) -> bool:
    import json

    identity = run(["whoami", "/user", "/fo", "csv", "/nh"])
    import csv

    if identity.returncode:
        return False
    account, actual_sid = next(csv.reader([identity.stdout.strip()]))
    if actual_sid != sid:
        return False
    # Task Scheduler canonicalizes trigger names and can omit default RunLevel.
    # Require independently read native Limited value before accepting omitted XML.
    native = run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "$t=Get-ScheduledTask -TaskName '"
            + NAME
            + "' -TaskPath ([string][char]92) -ErrorAction Stop; @{run_level=[string]$t.Principal.RunLevel} | ConvertTo-Json -Compress",
        ]
    )
    if native.returncode:
        return False
    level = json.loads(native.stdout)["run_level"]
    return verified(xml, python, root, config, sid, account_name=account, effective_run_level=level)


def definition(root: Path, config: Path) -> tuple[str, str, str, str]:
    if (
        not (root / "pyproject.toml").is_file()
        or not (root / "src" / "premetar" / "continuous").is_dir()
    ):
        raise ValueError("Run service commands from the project root")
    python = str(Path(sys.executable).with_name("pythonw.exe").resolve())
    if (
        Path(python) != (root / ".venv" / "Scripts" / "pythonw.exe").resolve()
        or not Path(python).is_file()
    ):
        raise ValueError("Use this project's uv environment")
    sid_result = run(["whoami", "/user", "/fo", "csv", "/nh"])
    import csv

    sid = next(csv.reader([sid_result.stdout.strip()]))[1]
    return python, str(root.resolve()), str(config.resolve()), sid


def install(root: Path, config: Path, preview: bool = True) -> str:
    python, working, configuration, sid = definition(root, config)
    xml = task_xml(python, working, configuration, sid)
    if preview:
        return xml
    old = query()
    if old and not owned(old, python, working, configuration):
        raise RuntimeError("Refusing to overwrite task not owned by this project/configuration")
    path = root / "data" / "continuous-task.xml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(xml, encoding="utf-16")
    args = ["schtasks", "/Create", "/TN", NAME, "/XML", str(path.resolve())]
    if old:
        args.append("/F")
    result = run(args)
    if result.returncode:
        raise RuntimeError(
            "Task registration failed; no administrator or password workaround attempted"
        )
    actual = query()
    if not actual or not verify_registered(actual, python, working, configuration, sid):
        raise RuntimeError("Task registration could not be verified")
    return actual


def remove(root: Path, config: Path) -> None:
    python, working, configuration, _ = definition(root, config)
    xml = query()
    if xml is None:
        return
    if not owned(xml, python, working, configuration):
        raise RuntimeError("Refusing to remove unrelated task")
    if run(["schtasks", "/Delete", "/TN", NAME, "/F"]).returncode:
        raise RuntimeError("Task removal failed")
