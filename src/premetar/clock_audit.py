"""Read-only Windows/NTP audit. Never starts services or changes clock configuration."""

import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

CACHE = Path("data/integrity/clock_audit.json")


def summarize(raw: dict[str, Any], tolerance_seconds: float = 1) -> dict[str, Any]:
    servers = []
    for entry in raw["evidence"]:
        if "/stripchart" not in entry["command"]:
            continue
        values = [
            float(v.replace(",", "."))
            for v in re.findall(r"([+-]\d+[.,]\d+)s", entry.get("stdout", ""))
        ]
        if entry.get("returncode") == 0 and len(values) >= 3:
            servers.append(
                dict(
                    server=next(
                        v.split(":", 1)[1] for v in entry["command"] if v.startswith("/computer:")
                    ),
                    samples_seconds=values,
                    median_offset_seconds=median(values),
                    spread_seconds=max(values) - min(values),
                )
            )
    stable = (
        len(servers) >= 2
        and max(s["median_offset_seconds"] for s in servers)
        - min(s["median_offset_seconds"] for s in servers)
        <= 0.25
        and all(s["spread_seconds"] <= 0.5 for s in servers)
    )
    offset = median([s["median_offset_seconds"] for s in servers]) if servers else None
    status = (
        ("VERIFIED" if abs(offset) <= tolerance_seconds else "FAILED")
        if stable and offset is not None
        else "UNKNOWN"
    )
    return dict(
        verification_status=status,
        synchronization_status="UNKNOWN",
        configured_clock_source="UNKNOWN",
        comparison_sources=[s["server"] for s in servers],
        measured_offset_seconds=offset,
        verified_at=raw["verified_at"],
        tolerance_seconds=tolerance_seconds,
        evidence_kind="APPROXIMATE_NTP_COMPARISON_NOT_MILLISECOND_CERTIFICATION",
        servers=servers,
        conclusion="Automatic synchronization and last successful W32Time sync could not be verified; stopped service alone does not establish clock error. No settings changed.",
        evidence=raw["evidence"],
    )


def run_audit(
    output: Path = Path("reports/integrity"), raw: dict[str, Any] | None = None
) -> dict[str, Any]:
    if raw is None:
        commands = [
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-Service W32Time | Select-Object Name,Status,StartType | ConvertTo-Json -Compress",
            ]
        ]
        commands += [
            ["w32tm", "/query", option] for option in ("/status", "/source", "/configuration")
        ]
        commands += [
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-TimeZone | Select-Object Id,BaseUtcOffset | ConvertTo-Json -Compress",
            ],
            ["sc.exe", "qtriggerinfo", "W32Time"],
            ["sc.exe", "qc", "W32Time"],
        ]
        commands += [
            ["w32tm", "/stripchart", "/computer:" + server, "/samples:5", "/dataonly"]
            for server in ("time.windows.com", "time.cloudflare.com")
        ]
        evidence = []
        for command in commands:
            at = datetime.now(UTC).isoformat()
            try:
                response = subprocess.run(command, capture_output=True, timeout=35, check=False)
                evidence.append(
                    dict(
                        command=command,
                        at=at,
                        returncode=response.returncode,
                        stdout=response.stdout.decode("utf-8", errors="replace"),
                        stderr=response.stderr.decode("utf-8", errors="replace"),
                    )
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                evidence.append(
                    dict(
                        command=command,
                        at=at,
                        returncode=None,
                        stdout="",
                        stderr=type(exc).__name__,
                    )
                )
        raw = dict(verified_at=datetime.now(UTC).isoformat(), evidence=evidence)
    result = summarize(raw)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(result, indent=2), encoding="utf-8")
    output.mkdir(parents=True, exist_ok=True)
    (output / "clock_audit.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (output / "clock_audit.md").write_text(
        "# Windows clock audit\n\n"
        + json.dumps(result, indent=2)
        + "\n\nFAILED denotes the configured 1-second research accuracy budget, not proof that the service is defective. Offsets are reported as returned by w32tm; no timestamps were corrected. Recommend reviewing existing Windows time synchronization/resync if a correction is desired; explicit approval is required before changing services/configuration.\n",
        encoding="utf-8",
    )
    return result


def cached_clock(now: datetime | None = None) -> dict[str, Any]:
    try:
        value = json.loads(CACHE.read_text(encoding="utf-8"))
        checked = datetime.fromisoformat(value["verified_at"])
        age = ((now or datetime.now(UTC)) - checked).total_seconds()
        if checked.tzinfo is None or age < 0 or age > 3600:
            return dict(
                verification_status="UNKNOWN",
                verified_at=value.get("verified_at"),
                reason="CLOCK_AUDIT_EXPIRED",
            )
        return {k: v for k, v in value.items() if k != "evidence"}
    except (OSError, ValueError, TypeError, KeyError):
        return dict(verification_status="UNKNOWN", reason="NO_USABLE_CLOCK_AUDIT")
