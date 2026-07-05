"""Combine per-condition pace penalties into an environmental cost (ADR-0001, ADR-0005)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CombinedCost:
    """The environmental cost of a segment, as pace-penalty cost factors.

    Divide observed pace by ``applied_factor`` to get Normalized Pace. ``reported_factor``
    is the fuller grade+heat+wind decomposition (which may exceed the applied set).
    """

    p_grade: float
    p_heat: float
    p_wind: float
    applied_factor: float
    reported_factor: float


def combine(p_grade: float, p_heat: float, p_wind: float, apply_wind: bool = False) -> CombinedCost:
    """Fuse per-condition pace penalties into a cost factor.

    Grade and wind are independent energy costs and combine additively in energy — which,
    in pace space, is just ``p_grade + p_wind`` (ADR-0001). Heat is a capacity limit and
    scales that mechanically-slowed pace, so it multiplies on top. Wind is excluded from
    the applied (NP) factor by default (ADR-0005) but always present in the reported one.
    """
    applied_mech = p_grade + (p_wind if apply_wind else 0.0)
    reported_mech = p_grade + p_wind
    heat = 1.0 + p_heat
    return CombinedCost(
        p_grade=p_grade,
        p_heat=p_heat,
        p_wind=p_wind,
        applied_factor=(1.0 + applied_mech) * heat,
        reported_factor=(1.0 + reported_mech) * heat,
    )
