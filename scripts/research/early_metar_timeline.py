"""Small static timeline of actual recorded clocks, never synthetic weather data."""

import importlib
from pathlib import Path
from typing import Any

from scripts.research.early_metar_data import clock


def plot_timeline(examples: list[dict[str, Any]], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    # Matplotlib's date/plot API has incomplete annotations; keep this boundary local.
    plt: Any = importlib.import_module("matplotlib.pyplot")
    chosen = [r for r in examples if r["example_class"] == "EXPLORATORY_INCREMENTAL_SUCCESS"][:5]
    fig, axis = plt.subplots(figsize=(15, max(4, 1.25 * len(chosen) + 2)))
    fields = [
        ("measurement_time", "PWS measurement", "#777777", "o", -0.24),
        ("pws_first_received", "PWS first receipt", "#0072B2", "s", -0.12),
        ("decision_time", "Reconstructed decision", "#009E73", "^", 0),
        ("target_time", "Nominal METAR", "#222222", "D", 0.12),
        ("metar_first_received", "First METAR receipt", "#D55E00", "X", 0.24),
    ]
    for i, row in enumerate(chosen):
        target = clock(row["target_time"])
        offsets = [(clock(row[key]) - target).total_seconds() for key, _, _, _, _ in fields]
        axis.plot([min(offsets), max(offsets)], [i, i], color="#cccccc", linewidth=1, zorder=0)
        for key, label, color, marker, dy in fields:
            instant = clock(row[key])
            offset = (instant - target).total_seconds()
            axis.scatter(
                [offset],
                [i + dy],
                color=color,
                marker=marker,
                s=55,
                label=label if i == 0 else None,
                zorder=3,
            )
            axis.annotate(
                instant.strftime("%H:%M:%S"),
                (offset, i + dy),
                xytext=(5, 0),
                textcoords="offset points",
                fontsize=8,
                va="center",
            )
    axis.set_yticks(
        range(len(chosen)),
        [
            f"{r['airport']} {clock(r['target_time']).strftime('%d Oct %H:%M')} UTC\n{r['method']} {r['phase']} {r['previous_integer']}→{r['actual_integer']}°C"
            for r in chosen
        ],
    )
    axis.axvline(0, color="#999999", linestyle="--", linewidth=0.8)
    axis.set_xlabel(
        "Seconds relative to nominal METAR observation (0); labels are actual UTC clocks"
    )
    axis.set_title(
        "EXP-0010 — recorded information timeline; reconstructed estimates, not live forecasts"
    )
    axis.grid(axis="x", alpha=0.2)
    axis.invert_yaxis()
    axis.margins(x=0.2, y=0.12)
    axis.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3, fontsize=9)
    if not chosen:
        axis.text(
            0.5, 0.5, "NO ELIGIBLE INCREMENTAL EXAMPLES", transform=axis.transAxes, ha="center"
        )
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
