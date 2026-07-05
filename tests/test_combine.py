import pytest

from pacelab.engine.combine import combine


def test_heat_multiplies_the_mechanical_penalty():
    # ADR-0001: heat is a capacity limit that SCALES the mechanically-slowed pace, so it
    # combines multiplicatively — (1+0.30)(1+0.20)=1.56, not the additive 1.50.
    cost = combine(p_grade=0.30, p_heat=0.20, p_wind=0.0)
    assert cost.reported_factor == pytest.approx(1.56)


def test_wind_is_reported_but_excluded_from_applied_by_default():
    # ADR-0005: wind is low-confidence, so it appears in the decomposition but is NOT
    # removed from the headline NP unless explicitly opted in.
    cost = combine(p_grade=0.10, p_heat=0.0, p_wind=0.10)
    assert cost.applied_factor == pytest.approx(1.10)  # grade only
    assert cost.reported_factor == pytest.approx(1.20)  # grade + wind
    assert cost.p_wind == 0.10  # still recorded for the decomposition


def test_apply_wind_flag_opts_wind_into_the_applied_cost():
    cost = combine(p_grade=0.10, p_heat=0.0, p_wind=0.10, apply_wind=True)
    assert cost.applied_factor == pytest.approx(1.20)


def test_reference_conditions_have_unit_cost():
    # All penalties zero (reference conditions) → nothing to remove: both the applied
    # and reported cost factors are 1.0 (dividing observed pace by 1.0 changes nothing).
    cost = combine(p_grade=0.0, p_heat=0.0, p_wind=0.0)
    assert cost.applied_factor == 1.0
    assert cost.reported_factor == 1.0
