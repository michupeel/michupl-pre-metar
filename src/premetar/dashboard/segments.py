"""Read immutable EXP0013 segments without starting any collector."""

import json
from datetime import date
from pathlib import Path
from typing import Any

from premetar.dashboard.reader import Reader


class SegmentReader:
    def __init__(self, weather: Path, research: Path, trader: Path) -> None:
        self.weather, self.research, self.trader = weather, research, trader

    def paths(self) -> list[Path]:
        manifest = self.research.parent / "segments.json"
        try:
            entries = json.loads(manifest.read_text(encoding="utf-8"))["segments"]
        except (OSError, ValueError, KeyError, TypeError):
            return [self.research]
        if not isinstance(entries, list):
            return [self.research]
        result = [self.research.resolve()]
        for entry in entries[-4:]:
            if not isinstance(entry, str):
                continue
            path = (self.research.parent / entry).resolve()
            if (
                path.parent == self.research.parent.resolve()
                and path.suffix == ".sqlite3"
                and path.is_file()
                and path not in result
            ):
                result.append(path)
        return result

    def load_day(self, day: date) -> dict[str, Any]:
        paths = self.paths()
        base = Reader(self.weather, paths[0], self.trader).load_day(day)
        for path in paths[1:]:
            newer = Reader(self.weather, path, self.trader).load_day(day)
            for kind in ("forecasts", "book_samples", "markets", "signals", "trades"):
                base.setdefault(kind, []).extend(newer.get(kind, []))
            for kind in ("research", "websocket"):
                if newer.get("health", {}).get(kind):
                    base.setdefault("health", {})[kind] = newer["health"][kind]
            for category in ("errors", "truncated", "rowcounts", "query_duration_ms"):
                for key, value in newer.get("limits", {}).get(category, {}).items():
                    base.setdefault("limits", {}).setdefault(category, {})[
                        path.stem + ":" + key
                    ] = value
        base.setdefault("limits", {})["research_segments"] = [p.name for p in paths]
        return base
