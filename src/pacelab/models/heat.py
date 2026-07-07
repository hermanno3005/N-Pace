"""Heat model — heat-stress index → pace penalty (FR-5, ADR-0010).

The primary index is **WBGT** (temperature + humidity + wind + solar; see models/wbgt.py),
which makes wind cooling intrinsic. When no solar data is available the model falls back to
the v1 **NWS Heat Index** (temperature + humidity only) — the persisted per-segment solar
value being NULL is the fallback's confidence tag. Each index maps to a fractional pace
penalty by a power-law anchored to El Helou (2012), zero at or below its own reference.

Coefficients are provisional (like grade's k_grade) — grounded in
docs/research/wbgt-heat-model.md, to be personalised by calibration (ADR-0006).
"""

import math

from pacelab.models.wbgt import wbgt
from pacelab.weather.conditions import Conditions

# Heat Index fallback curve (v1). Its zero-point is the 10 °C reference *air temperature*
# (ADR-0002); the primary WBGT path zeroes at WBGT_REF_C below instead.
REFERENCE_TEMP_C = 10.0
DEFAULT_HEAT_A = 0.0018  # Heat Index power-law scale
DEFAULT_HEAT_B = 1.5  # Heat Index curvature

# WBGT curve (v0.2, ADR-0010): reference and coefficients grounded in
# docs/research/wbgt-heat-model.md. Provisional pending ADR-0006 calibration.
WBGT_REF_C = 7.2
DEFAULT_WBGT_A = 0.0007
DEFAULT_WBGT_B = 2.0  # El Helou's fit is explicitly quadratic


def heat_index_c(temp_c: float, rh_pct: float) -> float:
    """NWS Heat Index in °C from air temperature (°C) and relative humidity (%)."""
    t = temp_c * 9 / 5 + 32  # to °F
    # Steadman simple estimate; only escalate to the full regression when it runs hot.
    hi = (0.5 * (t + 61.0 + (t - 68.0) * 1.2 + rh_pct * 0.094) + t) / 2
    if hi >= 80.0:
        hi = (
            -42.379 + 2.04901523 * t + 10.14333127 * rh_pct
            - 0.22475541 * t * rh_pct - 6.83783e-3 * t * t
            - 5.481717e-2 * rh_pct * rh_pct + 1.22874e-3 * t * t * rh_pct
            + 8.5282e-4 * t * rh_pct * rh_pct - 1.99e-6 * t * t * rh_pct * rh_pct
        )
        if rh_pct < 13 and 80 <= t <= 112:
            hi -= ((13 - rh_pct) / 4) * math.sqrt((17 - abs(t - 95)) / 17)
        elif rh_pct > 85 and 80 <= t <= 87:
            hi += ((rh_pct - 85) / 10) * ((87 - t) / 5)
    return (hi - 32) * 5 / 9  # back to °C


def heat_penalty(conditions: Conditions, *,
                 wbgt_ref_c: float = WBGT_REF_C, wbgt_a: float = DEFAULT_WBGT_A,
                 wbgt_b: float = DEFAULT_WBGT_B, hi_ref_c: float = REFERENCE_TEMP_C,
                 hi_a: float = DEFAULT_HEAT_A, hi_b: float = DEFAULT_HEAT_B) -> float:
    """Fractional pace penalty from heat stress; 0 at or below the reference.

    Primary: WBGT (ADR-0010), which folds in wind cooling and solar load. When no solar
    data is available (`solar_radiation_wm2 is None`) it falls back to the v1 Heat Index.
    """
    if conditions.solar_radiation_wm2 is None:
        hi = heat_index_c(conditions.temperature_c, conditions.humidity_pct)
        return hi_a * max(0.0, hi - hi_ref_c) ** hi_b
    return wbgt_a * max(0.0, wbgt(conditions) - wbgt_ref_c) ** wbgt_b
