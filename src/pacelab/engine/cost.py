"""Assemble the three impact models into a segment's environmental cost (ADR-0001)."""

from pacelab.config import Config
from pacelab.core import Segment
from pacelab.engine.combine import CombinedCost, combine
from pacelab.models.grade import grade_penalty
from pacelab.models.heat import heat_penalty
from pacelab.models.wind import wind_penalty
from pacelab.weather.conditions import Conditions

_DEFAULT = Config()


def segment_cost(segment: Segment, conditions: Conditions, config: Config = _DEFAULT) -> CombinedCost:
    """The grade + heat + wind pace penalties for a segment, combined per ADR-0001/0005."""
    return combine(
        p_grade=grade_penalty(segment.grade, k_grade=config.k_grade),
        p_heat=heat_penalty(conditions, wbgt_ref_c=config.wbgt_ref_c, wbgt_a=config.wbgt_a,
                            wbgt_b=config.wbgt_b, hi_ref_c=config.reference_temp_c,
                            hi_a=config.heat_a, hi_b=config.heat_b),
        p_wind=wind_penalty(segment, conditions, drag_area_per_mass=config.drag_area_per_mass),
        apply_wind=config.apply_wind,
    )
