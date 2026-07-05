import pytest

from pacelab.engine.combine import combine
from pacelab.engine.normalize import adjust, normalize


from pacelab.models.grade import grade_penalty


def test_reference_conditions_leave_pace_unchanged():
    # Under reference conditions there is no environmental cost, so NP == observed pace.
    reference = combine(p_grade=0.0, p_heat=0.0, p_wind=0.0)
    assert normalize(300.0, reference) == 300.0


def test_forward_then_backward_is_identity():
    # V-2: forward (AP) and backward (NP) are inverses of the same model. Realistic
    # segment: a 6% climb in the heat.
    cost = combine(p_grade=grade_penalty(0.06), p_heat=0.08, p_wind=0.0)
    observed = 312.5  # s/km
    assert adjust(normalize(observed, cost), cost) == pytest.approx(observed)


def test_normalizing_a_climb_yields_a_faster_pace():
    # A climb slows you, so removing its cost gives a quicker (smaller s/km) NP.
    cost = combine(p_grade=grade_penalty(0.08), p_heat=0.0, p_wind=0.0)
    assert normalize(330.0, cost) < 330.0
