import importlib.util
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

_spec = importlib.util.spec_from_file_location(
    "epwa_plot", Path(__file__).parents[1] / "scripts/research/epwa_plot.py"
)
assert _spec is not None and _spec.loader is not None
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
measurement_segments = _module.measurement_segments
plot_comparison = _module.plot_comparison


def point(instant: str, temperature: float = 12) -> dict[str, Any]:
    return {
        "station_id": "station",
        "sensor_id": "temperature",
        "measurement_time_utc": instant,
        "temperature_c": temperature,
    }


def test_segments_sort_and_break_only_large_gaps() -> None:
    segments = measurement_segments(
        [
            point("2026-10-25T02:00:01Z"),
            point("2026-10-25T01:30:00Z"),
            point("2026-10-25T01:45:00Z"),
        ]
    )
    assert [len(segment) for segment in segments] == [2, 1]
    assert segments[0][0][0].minute == 30


def test_repeated_warsaw_hour_is_not_collapsed() -> None:
    segments = measurement_segments([point("2026-10-25T00:30:00Z"), point("2026-10-25T01:30:00Z")])
    first, second = segments[0][0][0], segments[1][0][0]
    assert (second - first).total_seconds() == 3600
    assert first.astimezone(ZoneInfo("Europe/Warsaw")).hour == 2
    assert second.astimezone(ZoneInfo("Europe/Warsaw")).hour == 2
    assert (
        first.astimezone(ZoneInfo("Europe/Warsaw")).utcoffset()
        != second.astimezone(ZoneInfo("Europe/Warsaw")).utcoffset()
    )


def test_naive_measurement_time_rejected() -> None:
    with pytest.raises(ValueError, match="timezone aware"):
        measurement_segments([point("2026-10-25T02:30:00")])


def test_empty_chart_can_be_exported(tmp_path: Path) -> None:
    output = tmp_path / "chart.png"
    plot_comparison([], [], [], output)
    assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_multiple_instruments_and_metar_export(tmp_path: Path) -> None:
    second = point("2026-10-25T12:05:00Z", 13)
    second["sensor_id"] = "other-temperature"
    output = tmp_path / "chart.png"
    plot_comparison(
        [point("2026-10-25T12:00:00Z"), second],
        [
            {
                "observation_time_utc": "2026-10-25T12:00:00Z",
                "temperature_c": 12,
                "report_type": "METAR",
                "correction": False,
            },
            {
                "observation_time_utc": "2026-10-25T12:10:00Z",
                "temperature_c": 15,
                "report_type": "SPECI",
                "correction": False,
            },
        ],
        [{"station_id": "station", "station_name": "Actual station", "distance_km": 2.665}],
        output,
    )
    assert output.stat().st_size > 10_000


def test_metar_reference_excludes_corrections_speci_and_duplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from matplotlib.axes import Axes

    original = Axes.scatter
    plotted: list[float] = []

    def capture(self: Any, x: Any, y: Any, *args: Any, **kwargs: Any) -> Any:
        plotted.extend(y)
        return original(self, x, y, *args, **kwargs)

    monkeypatch.setattr(Axes, "scatter", capture)
    routine = {
        "observation_time_utc": "2026-10-25T12:00:00Z",
        "temperature_c": 12,
        "report_type": "METAR",
        "correction": False,
    }
    plot_comparison(
        [],
        [
            routine,
            dict(routine),
            {**routine, "temperature_c": 13, "correction": True},
            {**routine, "temperature_c": 14, "report_type": "SPECI"},
        ],
        [],
        tmp_path / "reference.png",
    )
    assert plotted == [12]
