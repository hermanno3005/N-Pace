"""Outdoor WBGT (Wet-Bulb Globe Temperature) — v0.2 heat-stress index (ADR-0010).

`WBGT = 0.7·Tnw + 0.2·Tg + 0.1·Ta`, computed closed-form from air temperature, humidity,
wind, and solar irradiance. Wind lowers WBGT and solar raises it, so the wind→heat cooling
coupling is intrinsic — no separate coefficient (ADR-0001).

Terms:
- `Tw`  — psychrometric wet-bulb, Stull (2011).
- `Tnw` — natural wet-bulb, NDFD regression (carries the wind ↓ and solar ↑ coupling).
- `Tg`  — globe temperature. The full Dimiceli globe needs solar zenith / diffuse split / an
  unpublished coefficient, none cleanly available from Open-Meteo; since the coupling lives in
  the 0.7-weighted `Tnw`, the 0.2-weighted globe uses a shade-anchored simplification
  `Tg = Ta + 0.0096·S` (Carter et al. 2020 solar slope, `Tg = Ta` in shade). This keeps
  WBGT_ref = 7.2 °C exactly consistent with the research; see ADR-0010.
"""

import math

from pacelab.weather.conditions import Conditions

# Carter et al. (2020) solar slope for the globe, anchored so shade (S=0) → Tg = Ta.
_GLOBE_SOLAR_SLOPE = 0.009624  # °C per W/m²


def wet_bulb_stull(temp_c: float, rh_pct: float) -> float:
    """Psychrometric wet-bulb temperature (°C), Stull (2011) closed-form."""
    t, rh = temp_c, rh_pct
    return (
        t * math.atan(0.151977 * math.sqrt(rh + 8.313659))
        + math.atan(t + rh)
        - math.atan(rh - 1.676331)
        + 0.00391838 * rh**1.5 * math.atan(0.023101 * rh)
        - 4.686035
    )


def natural_wet_bulb(temp_c: float, rh_pct: float, solar_wm2: float, wind_ms: float) -> float:
    """Natural wet-bulb temperature (°C), NDFD regression. Wind in m/s, solar in W/m²."""
    tw = wet_bulb_stull(temp_c, rh_pct)
    twd = temp_c - tw  # wet-bulb depression
    return tw + 0.001651 * solar_wm2 - 0.09555 * wind_ms + 0.13235 * twd + 0.20249


def globe_temperature(temp_c: float, solar_wm2: float) -> float:
    """Globe temperature (°C), shade-anchored solar approximation (see module docstring)."""
    return temp_c + _GLOBE_SOLAR_SLOPE * solar_wm2


def wbgt(conditions: Conditions) -> float:
    """Outdoor WBGT (°C) from weather conditions."""
    ta = conditions.temperature_c
    tnw = natural_wet_bulb(ta, conditions.humidity_pct, conditions.solar_radiation_wm2,
                           conditions.wind_speed_ms)
    tg = globe_temperature(ta, conditions.solar_radiation_wm2)
    return 0.7 * tnw + 0.2 * tg + 0.1 * ta
