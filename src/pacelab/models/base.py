"""The impact-model seam (NFR-8).

Every environmental effect is a callable that maps a segment and its conditions to a pace
penalty (CONTEXT: Pace Penalty) — a fractional slowing at constant effort. Grade, heat, and
wind implement this shape, so they are interchangeable behind it and Phase-3 calibration
swaps coefficients without touching the engine.
"""

from typing import Protocol

from pacelab.core import Segment
from pacelab.weather.conditions import Conditions


class ImpactModel(Protocol):
    def cost(self, segment: Segment, conditions: Conditions) -> float:
        ...
