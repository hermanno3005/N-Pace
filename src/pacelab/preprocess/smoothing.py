"""Elevation smoothing (FR-2.2): suppress GPS/baro spikes before computing grade.

A rolling median is used rather than a moving average: it removes isolated spikes
completely while passing a real sustained ramp through unchanged (the median of a
symmetric window over a monotonic run is its centre value). The window shrinks
symmetrically toward the ends, so the endpoints are preserved exactly.
"""

from statistics import median

DEFAULT_WINDOW = 5  # samples (radius 2)


def smooth_elevation(elevations: list[float], window: int = DEFAULT_WINDOW) -> list[float]:
    n = len(elevations)
    if n == 0:
        return []
    half = window // 2
    out: list[float] = []
    for i in range(n):
        radius = min(i, n - 1 - i, half)  # symmetric window that fits → endpoints exact
        out.append(median(elevations[i - radius : i + radius + 1]))
    return out
