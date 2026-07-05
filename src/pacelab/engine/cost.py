"""Assemble the three impact models into a segment's environmental cost (ADR-0001)."""

from pacelab.core import Segment
from pacelab.engine.combine import CombinedCost, combine
from pacelab.models.grade import grade_penalty
from pacelab.models.heat import heat_penalty
from pacelab.models.wind import wind_penalty
from pacelab.weather.conditions import Conditions


def segment_cost(segment: Segment, conditions: Conditions, apply_wind: bool = False) -> CombinedCost:
    """The grade + heat + wind pace penalties for a segment, combined per ADR-0001/0005."""
    return combine(
        p_grade=grade_penalty(segment.grade),
        p_heat=heat_penalty(conditions),
        p_wind=wind_penalty(segment, conditions),
        apply_wind=apply_wind,
    )
