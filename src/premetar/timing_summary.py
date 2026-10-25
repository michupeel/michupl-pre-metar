"""Nearest-rank operational percentiles, reviewed/adapted from Qwen's proposal."""

import math
from collections import defaultdict
from typing import Any


def summarize_timings(records: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if isinstance(record.get("operation_name"), str):
            groups[record["operation_name"]].append(record)
    result: dict[str, dict[str, float | int]] = {}
    for name, items in groups.items():
        summary: dict[str, float | int] = {
            "count": len(items),
            "failed_count": sum(r.get("success") is False for r in items),
        }
        for metric in ("queue_wait_ms", "duration_ms", "db_execution_ms", "worker_execution_ms"):
            values = sorted(
                float(r[metric])
                for r in items
                if isinstance(r.get(metric), (int, float))
                and not isinstance(r[metric], bool)
                and math.isfinite(r[metric])
                and r[metric] >= 0
            )
            for label, fraction in (("p95", 0.95), ("p99", 0.99)):
                if values:
                    summary[f"{metric}_{label}"] = values[math.ceil(len(values) * fraction) - 1]
        result[name] = summary
    return result
