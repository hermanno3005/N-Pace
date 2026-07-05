"""Wind model — headwind drag as a pace penalty (FR-6, ADR-0001/0005).

Air density comes straight from Open-Meteo's surface pressure and temperature (already
altitude-adjusted, so home elevation isn't needed here). The headwind component is the
wind projected onto the segment's bearing; the cost is the signed-quadratic excess drag
over still air, so a headwind costs more than an equal tailwind saves (Pugh/Davies).
"""

import math

from pacelab.core import Segment
from pacelab.models.grade import cost_of_transport
from pacelab.weather.conditions import Conditions

_R_SPECIFIC_DRY_AIR = 287.05  # J/(kg·K)
_FLAT_COST = cost_of_transport(0.0)  # Minetti C(0) = 3.6 J/kg/m, the pace-penalty denominator

# Effective aerodynamic drag area per body mass, C_d·A/m in m²/kg (Pugh/Davies order).
DEFAULT_DRAG_AREA_PER_MASS = 0.0057


def air_density(conditions: Conditions) -> float:
    """Air density in kg/m³ from temperature and (surface) pressure: ρ = P / (R·T)."""
    t_kelvin = conditions.temperature_c + 273.15
    return (conditions.pressure_hpa * 100.0) / (_R_SPECIFIC_DRY_AIR * t_kelvin)


def headwind_component(segment: Segment, conditions: Conditions) -> float:
    """Signed wind along the direction of travel: + into the runner, − from behind.

    Wind direction is meteorological (the direction it blows *from*), so a wind coming from
    exactly the runner's heading is a pure headwind.
    """
    angle = math.radians(conditions.wind_dir_deg - segment.bearing)
    return conditions.wind_speed_ms * math.cos(angle)


def wind_penalty(segment: Segment, conditions: Conditions,
                 drag_area_per_mass: float = DEFAULT_DRAG_AREA_PER_MASS) -> float:
    """Fractional pace penalty from air resistance relative to still air.

    Excess drag energy per metre is ``½·ρ·(C_dA/m)·((v+w)² − v²)``, converted to a pace
    penalty by the flat cost of transport. Signed in ``w``, so headwind > tailwind.
    """
    if segment.elapsed <= 0:
        return 0.0
    v = segment.distance / segment.elapsed
    w = headwind_component(segment, conditions)
    rho = air_density(conditions)
    excess_energy = 0.5 * rho * drag_area_per_mass * ((v + w) ** 2 - v**2)
    return excess_energy / _FLAT_COST
