"""Small opt-in development client; production collectors never import this tool."""

import argparse
import ipaddress
import json
import os
import socket
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[2]


def private_endpoint(url: str) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme not in ("http", "https")
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise ValueError("Use a plain local/private API base URL without embedded credentials")
    if not parts.hostname:
        raise ValueError("Missing host")
    addresses = socket.getaddrinfo(
        parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)
    )
    if not addresses or any(
        not (
            ipaddress.ip_address(item[4][0]).is_private
            or ipaddress.ip_address(item[4][0]).is_loopback
        )
        for item in addresses
    ):
        raise ValueError("Only local/private inference endpoints are permitted")
    return url.rstrip("/")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("health", "ask"))
    parser.add_argument("--task")
    parser.add_argument("--task-file", type=Path)
    parser.add_argument("--file", type=Path, action="append", default=[])
    parser.add_argument(
        "--system",
        default="You are a bounded development assistant. Return reviewable artifacts only.",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--max-tokens", type=int, default=4096)
    args = parser.parse_args()
    task_id = uuid4().hex
    start = time.monotonic()
    record = {
        "task_id": task_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "operation": args.command,
    }
    folder = ROOT / "reports/dev"
    folder.mkdir(parents=True, exist_ok=True)
    lock_path = folder / "qwen_worker.lock"
    lock = None
    try:
        if os.getenv("LOCAL_LLM_ENABLED", "false").lower() != "true":
            raise ValueError("Set LOCAL_LLM_ENABLED=true to opt in")
        if os.getenv("LOCAL_LLM_MAX_CONCURRENCY", "1") != "1":
            raise ValueError("This bounded worker supports one generation at a time")
        lock = lock_path.open("x", encoding="utf-8")
        base = private_endpoint(os.environ["LOCAL_LLM_BASE_URL"])
        timeout = float(os.getenv("LOCAL_LLM_TIMEOUT", "120"))
        if not 0 < timeout <= 600 or not 1 <= args.max_tokens <= 32768:
            raise ValueError("Invalid timeout or token bound")
        headers = {}
        if key := os.getenv("LOCAL_LLM_API_KEY"):
            headers["Authorization"] = "Bearer " + key
        with httpx.Client(
            headers=headers, timeout=timeout, trust_env=False, follow_redirects=False
        ) as client:
            models = client.get(base + "/models")
            models.raise_for_status()
            ids = [m["id"] for m in models.json()["data"]]
            model = os.getenv("LOCAL_LLM_MODEL", "auto")
            if model == "auto":
                candidates = [m for m in ids if "qwen" in m.lower()]
                if len(candidates) != 1:
                    raise ValueError("Ambiguous model list: explicitly set LOCAL_LLM_MODEL")
                model = candidates[0]
            if model not in ids:
                raise ValueError("Configured model is unavailable")
            prompt = (
                "Reply READY"
                if args.command == "health"
                else args.task
                or (args.task_file.read_text(encoding="utf-8") if args.task_file else "")
            )
            if not prompt:
                raise ValueError("Supply --task or --task-file")
            for path in args.file:
                resolved = path.resolve()
                if (
                    not resolved.is_relative_to(ROOT)
                    or resolved.suffix not in {".py", ".md", ".toml", ".json"}
                    or any(p in resolved.parts for p in ("data", ".git", ".venv"))
                ):
                    raise ValueError(
                        "Only selected repository source/docs/config files are allowed"
                    )
                if resolved.stat().st_size > 40000:
                    raise ValueError("Select smaller source context")
                prompt += f"\nFILE {resolved.relative_to(ROOT)}\n" + resolved.read_text(
                    encoding="utf-8"
                )
            if len(prompt) > 60000:
                raise ValueError("Context exceeds bounded task size")
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": args.system},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 16 if args.command == "health" else args.max_tokens,
                "stream": False,
            }
            if args.json:
                payload["response_format"] = {"type": "json_object"}
            for attempt in range(3):
                try:
                    response = client.post(base + "/chat/completions", json=payload)
                    if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                        retry = response.headers.get("Retry-After")
                        delay = float(2**attempt)
                        if retry:
                            try:
                                delay = max(delay, float(retry))
                            except ValueError:
                                delay = max(
                                    delay,
                                    (
                                        parsedate_to_datetime(retry) - datetime.now(UTC)
                                    ).total_seconds(),
                                )
                        if delay > 30:
                            response.raise_for_status()
                        time.sleep(delay)
                        continue
                    response.raise_for_status()
                    result = response.json()
                    content = result["choices"][0]["message"]["content"]
                    if not content or result["choices"][0].get("finish_reason") == "length":
                        raise ValueError("Empty or truncated generation")
                    if args.json:
                        json.loads(content)
                    break
                except (httpx.NetworkError, httpx.TimeoutException):
                    if attempt == 2:
                        raise
                    time.sleep(2**attempt)
            artifact = folder / "artifacts" / f"{task_id}.txt"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(content, encoding="utf-8")
            record.update(
                status="ok",
                model=model,
                usage=result.get("usage", {}),
                artifact=str(artifact.relative_to(ROOT)),
            )
    except Exception as exc:
        # No exception text, auth headers, request bodies or source files in audit.
        record.update(status="error", error_class=type(exc).__name__)
    finally:
        if lock is not None:
            lock.close()
            lock_path.unlink()
        record["duration_s"] = round(time.monotonic() - start, 3)
        with (folder / "qwen_delegation.jsonl").open("a", encoding="utf-8") as file:
            file.write(json.dumps(record) + "\n")
        print(json.dumps(record, indent=2))
    return 0 if record.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
