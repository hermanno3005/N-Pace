from pacelab.models.grade import grade_penalty


def test_flat_grade_has_zero_penalty():
    # Reference condition: 0% grade costs nothing (CONTEXT: Reference Conditions).
    assert grade_penalty(0.0) == 0.0


def test_climb_costs_more_than_equal_descent_returns():
    # FR-4.2: the cost is asymmetric — a climb costs more than the equal descent gives
    # back, so a there-and-back over the same grade nets a positive penalty.
    for g in (0.05, 0.10, 0.20):
        assert grade_penalty(g) + grade_penalty(-g) > 0


def test_running_is_cheapest_slightly_downhill():
    # Minetti's signature finding: minimum cost is at a gentle downhill, below the flat
    # cost, and a steep descent is costlier than that gentle one (benefit stops).
    assert grade_penalty(-0.10) < grade_penalty(0.0)
    assert grade_penalty(-0.30) > grade_penalty(-0.10)


def test_uphill_penalty_is_monotonic():
    assert grade_penalty(0.20) > grade_penalty(0.10) > grade_penalty(0.02) > 0


def test_grade_is_capped_at_minetti_validity_bounds():
    # FR-2.2: grades beyond ±45% are clamped, not extrapolated into nonsense.
    assert grade_penalty(0.60) == grade_penalty(0.45)
    assert grade_penalty(-0.60) == grade_penalty(-0.45)


def test_ten_percent_climb_matches_literature_magnitude():
    # Independent bracket: Minetti's cost at +10% grade is ~1.6–1.7× the flat cost.
    ratio = grade_penalty(0.10) + 1.0
    assert 1.55 < ratio < 1.75
