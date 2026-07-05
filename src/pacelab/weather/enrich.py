"""Attach weather Conditions to each Segment (FR-3.1).

Each segment is looked up at its midpoint in time (so a long segment isn't pinned to its
start) and its midpoint position; the WeatherService handles caching and interpolation.
"""

from typing import Protocol

from pacelab.core import Segment
from pacelab.weather.conditions import Conditions


class ConditionsSource(Protocol):
    def conditions_at(self, lat: float, lon: float, t: float) -> Conditions:
        ...


def enrich(segments: list[Segment], source: ConditionsSource) -> list[tuple[Segment, Conditions]]:
    return [
        (s, source.conditions_at(s.lat, s.lon, s.start_time + s.elapsed / 2))
        for s in segments
    ]
