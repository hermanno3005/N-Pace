import pytest

from pacelab.analyze import analyze
from pacelab.config import Config
from pacelab.core import Segment
from pacelab.weather.conditions import Conditions


def seg(grade=0.0, elapsed=34.0, bearing=90.0, dist=100.0):
    return Segment(distance=dist, grade=grade, bearing=bearing, elapsed=elapsed,
                   lat=48.0, lon=11.0, start_time=0.0)


def cond(temp=10.0, rh=50.0, wind=0.0, wdir=0.0):
    return Conditions(temp, rh, wind, wdir, 0.0, 1013.25)


def activity(segment, conditions, n=10):
    return [(segment, conditions) for _ in range(n)]


def test_reference_conditions_normalize_to_observed():
    result = analyze(activity(seg(grade=0.0), cond(10.0, 50.0)), Config())
    assert result.np_pace == pytest.approx(result.observed_pace)
    assert result.cost_grade == pytest.approx(0.0, abs=1e-6)
    assert result.cost_heat == pytest.approx(0.0, abs=1e-6)


def test_v4_hilly_run_is_grade_dominated():
    result = analyze(activity(seg(grade=0.06, elapsed=40.0), cond(10.0, 50.0)), Config())
    assert result.cost_grade > 0
    assert abs(result.cost_grade) > abs(result.cost_heat)
    assert abs(result.cost_grade) > abs(result.cost_wind)
    assert result.np_pace < result.observed_pace  # a climb removed → faster NP


def test_v4_hot_run_is_heat_dominated():
    result = analyze(activity(seg(grade=0.0), cond(30.0, 60.0)), Config())
    assert result.cost_heat > 0
    assert abs(result.cost_heat) > abs(result.cost_grade)
    assert abs(result.cost_heat) > abs(result.cost_wind)
    assert result.np_pace < result.observed_pace  # heat removed → faster NP


def test_v4_windy_run_reports_wind_but_does_not_change_np():
    # Flat, cool, into an 8 m/s headwind: wind dominates the decomposition, but NP is
    # unchanged because wind is reported-not-applied and grade/heat are ~0 (ADR-0005).
    result = analyze(activity(seg(grade=0.0, bearing=90.0), cond(10.0, 50.0, 8.0, 90.0)), Config())
    assert result.cost_wind > 0
    assert abs(result.cost_wind) > abs(result.cost_grade)
    assert abs(result.cost_wind) > abs(result.cost_heat)
    assert result.np_pace == pytest.approx(result.observed_pace)
