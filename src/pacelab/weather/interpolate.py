"""Interpolate hourly weather to a segment's exact timestamp (FR-3.1, ADR-0004).

Linear in time between the two bracketing hourly readings; times outside the series clamp
to the nearest hour. Wind direction is interpolated along the *shortest angular path* so
readings that straddle north (e.g. 350° → 10°) pass through 0°, not 180°.
"""

from pacelab.weather.conditions import Conditions

_HourlySeries = list[tuple[float, Conditions]]


def _interp_angle(a: float, b: float, frac: float) -> float:
    delta = ((b - a + 180.0) % 360.0) - 180.0  # shortest signed turn a→b
    return (a + frac * delta) % 360.0


def interpolate_conditions(hourly: _HourlySeries, t: float) -> Conditions:
    series = sorted(hourly)
    if t <= series[0][0]:
        return series[0][1]
    if t >= series[-1][0]:
        return series[-1][1]

    hi = 1
    while series[hi][0] < t:
        hi += 1
    (t0, c0), (t1, c1) = series[hi - 1], series[hi]
    frac = (t - t0) / (t1 - t0)

    def lin(x0: float, x1: float) -> float:
        return x0 + frac * (x1 - x0)

    return Conditions(
        temperature_c=lin(c0.temperature_c, c1.temperature_c),
        humidity_pct=lin(c0.humidity_pct, c1.humidity_pct),
        wind_speed_ms=lin(c0.wind_speed_ms, c1.wind_speed_ms),
        wind_dir_deg=_interp_angle(c0.wind_dir_deg, c1.wind_dir_deg, frac),
        cloud_cover_pct=lin(c0.cloud_cover_pct, c1.cloud_cover_pct),
        pressure_hpa=lin(c0.pressure_hpa, c1.pressure_hpa),
    )
