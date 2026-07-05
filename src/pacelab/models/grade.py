"""Grade model — Minetti (2002) energy cost of running vs gradient.

Converts a segment's grade into a pace penalty (CONTEXT: Pace Penalty) via the
constant-power relation ``speed ∝ 1 / cost-of-transport`` (ADR-0001): at constant
metabolic power, pace scales as the energy-cost ratio, so the penalty is
``C(grade) / C(0) − 1``.
"""

# Minetti et al. (2002) polynomial for the energy cost of running, C(i), in J/kg/m,
# where i is the gradient as a fraction (rise/run). Valid over i ∈ [−0.45, +0.45].
_MINETTI = (155.4, -30.4, -43.3, 46.3, 19.5, 3.6)  # coefficients for i⁵ … i⁰

# Minetti's validity bounds; grades are capped here before evaluation (FR-2.2).
GRADE_CAP = 0.45

_C0 = _MINETTI[-1]  # cost on the flat, C(0) = 3.6 J/kg/m


def cost_of_transport(grade: float) -> float:
    """Minetti energy cost C(i) in J/kg/m for a gradient fraction, capped to ±45%."""
    i = max(-GRADE_CAP, min(GRADE_CAP, grade))
    c5, c4, c3, c2, c1, c0 = _MINETTI
    return ((((c5 * i + c4) * i + c3) * i + c2) * i + c1) * i + c0


def grade_penalty(grade: float) -> float:
    """Fractional pace penalty from grade at constant effort.

    Positive = slower than flat (a climb); negative = faster (a descent).
    """
    return cost_of_transport(grade) / _C0 - 1.0
