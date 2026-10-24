"""Small descriptive lead statistics."""


def lead_summary(values: list[float]) -> dict[str, float | int | None]:
    """Compute lead summary statistics.

    Args:
        values: A list of positive finite float values.

    Returns:
        A dictionary with keys 'N', 'p10', 'p50', 'p90', 'maximum'
        containing the count and percentiles, or None for empty input.

    Raises:
        ValueError: If any value is not a positive finite number.
    """
    if not values:
        return {"N": 0, "p10": None, "p50": None, "p90": None, "maximum": None}

    import math

    # Validate all values are positive and finite
    for v in values:
        if not (
            isinstance(v, (int, float)) and v > 0 and math.isfinite(v)
        ):  # v == v checks for NaN
            raise ValueError("All values must be positive finite numbers.")

    sorted_values = sorted(values)
    n = len(sorted_values)

    def percentile(q: float) -> float:
        index = (n - 1) * q
        lower_index = int(index)
        upper_index = lower_index + 1
        if upper_index >= n:
            return sorted_values[lower_index]
        weight = index - lower_index
        return sorted_values[lower_index] * (1 - weight) + sorted_values[upper_index] * weight

    return {
        "N": n,
        "p10": percentile(0.1),
        "p50": percentile(0.5),
        "p90": percentile(0.9),
        "maximum": sorted_values[-1],
    }


def day_block_interval(
    values: list[tuple[str, float]], minimum_days: int = 7, minimum_targets: int = 100
) -> dict[str, float | int | str | None]:
    """Resample complete UTC target days, preserving dependence within each day.

    Descriptive 95% percentile interval; dependence across days remains a limitation.
    Caller supplies one matched-target difference per airport/checkpoint/model.
    """
    import math
    from collections import defaultdict
    from random import Random

    blocks: dict[str, list[float]] = defaultdict(list)
    for day, value in values:
        if not math.isfinite(value):
            raise ValueError("Nonfinite sample")
        blocks[day].append(value)
    result: dict[str, float | int | str | None] = dict(
        N=len(values), days=len(blocks), lower=None, upper=None, status="INSUFFICIENT DATA"
    )
    if len(values) < minimum_targets or len(blocks) < minimum_days:
        return result
    aggregate = [(sum(block), len(block)) for block in blocks.values()]
    rng = Random(20261024)
    samples = []
    for _ in range(2000):
        chosen = rng.choices(aggregate, k=len(aggregate))
        samples.append(sum(s for s, _ in chosen) / sum(n for _, n in chosen))
    samples.sort()

    def quantile(q: float) -> float:
        index = (len(samples) - 1) * q
        lo = int(index)
        return samples[lo] + (samples[min(lo + 1, len(samples) - 1)] - samples[lo]) * (index - lo)

    result.update(
        lower=quantile(0.025), upper=quantile(0.975), status="DESCRIPTIVE_UTC_DAY_BLOCK_BOOTSTRAP"
    )
    return result
