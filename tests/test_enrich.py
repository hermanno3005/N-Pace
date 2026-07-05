import pytest

from pacelab.core import Segment
from pacelab.weather.conditions import Conditions
from pacelab.weather.enrich import enrich


class StubService:
    def __init__(self):
        self.calls = []

    def conditions_at(self, lat, lon, t):
        self.calls.append((lat, lon, t))
        return Conditions(t / 3600.0, 50.0, 2.0, 180.0, 0.0, 1013.0)


def test_enrich_looks_up_conditions_at_each_segment_midpoint():
    seg = Segment(distance=100.0, grade=0.0, bearing=90.0, elapsed=60.0,
                  lat=48.0, lon=11.0, start_time=3600.0)  # starts 01:00, 60 s long
    service = StubService()

    enriched = enrich([seg], service)

    # Looked up at the segment's midpoint in time (3600 + 30) and its midpoint position.
    assert service.calls == [(48.0, 11.0, 3630.0)]
    out_seg, cond = enriched[0]
    assert out_seg is seg
    assert cond.temperature_c == pytest.approx(3630.0 / 3600.0)
