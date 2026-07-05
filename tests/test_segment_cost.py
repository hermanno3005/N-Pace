from pacelab.core import Segment
from pacelab.engine.cost import segment_cost
from pacelab.weather.conditions import Conditions


def _seg(grade=0.0, elapsed=30.0, bearing=90.0):
    return Segment(distance=100.0, grade=grade, bearing=bearing, elapsed=elapsed,
                   lat=48.0, lon=11.0, start_time=0.0)


def test_hot_flat_calm_segment_cost_is_all_heat():
    cost = segment_cost(_seg(grade=0.0), Conditions(30.0, 50.0, 0.0, 0.0, 0.0, 1013.0))
    assert cost.p_heat > 0
    assert cost.p_grade == 0.0
    assert cost.p_wind == 0.0


def test_hilly_cool_calm_segment_cost_is_all_grade():
    cost = segment_cost(_seg(grade=0.06), Conditions(10.0, 50.0, 0.0, 0.0, 0.0, 1013.0))
    assert cost.p_grade > 0
    assert cost.p_heat == 0.0
    assert cost.p_wind == 0.0


def test_headwind_segment_records_wind_in_reported_not_applied():
    # Flat, cool, into a 6 m/s headwind (ADR-0005: wind reported, not applied).
    cost = segment_cost(_seg(bearing=90.0), Conditions(10.0, 50.0, 6.0, 90.0, 0.0, 1013.0))
    assert cost.p_wind > 0
    assert cost.reported_factor > cost.applied_factor
