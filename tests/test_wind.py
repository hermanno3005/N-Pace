import pytest

from pacelab.core import Segment
from pacelab.models.wind import wind_penalty
from pacelab.weather.conditions import Conditions


def _seg(bearing=90.0, distance=100.0, elapsed=30.0):
    # ~3.33 m/s heading due east.
    return Segment(distance=distance, grade=0.0, bearing=bearing, elapsed=elapsed,
                   lat=48.0, lon=11.0, start_time=0.0)


def _wind(speed, from_dir):
    return Conditions(15.0, 50.0, speed, from_dir, 0.0, 1013.25)


def test_no_wind_has_no_penalty():
    assert wind_penalty(_seg(), _wind(0.0, 0.0)) == 0.0


def test_headwind_costs_and_tailwind_helps():
    headwind = wind_penalty(_seg(bearing=90.0), _wind(6.0, 90.0))  # wind FROM the east, heading east
    tailwind = wind_penalty(_seg(bearing=90.0), _wind(6.0, 270.0))  # wind FROM the west
    assert headwind > 0
    assert tailwind < 0


def test_headwind_costs_more_than_equal_tailwind_saves():
    # Pugh/Davies asymmetry: the quadratic makes a headwind hurt more than the same
    # tailwind helps.
    headwind = wind_penalty(_seg(bearing=90.0), _wind(6.0, 90.0))
    tailwind = wind_penalty(_seg(bearing=90.0), _wind(6.0, 270.0))
    assert headwind > -tailwind


def test_crosswind_projects_to_no_headwind():
    # Only the along-bearing component matters (FR-6.1); a pure crosswind → ~0.
    assert wind_penalty(_seg(bearing=90.0), _wind(6.0, 0.0)) == pytest.approx(0.0, abs=1e-9)
