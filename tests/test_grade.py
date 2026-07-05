from pacelab.models.grade import cost_of_transport, grade_penalty


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


def test_ten_percent_climb_matches_literature_energy_cost():
    # Independent bracket: Minetti's *energy* cost at +10% grade is ~1.6–1.7× flat.
    ratio = cost_of_transport(0.10) / cost_of_transport(0.0)
    assert 1.55 < ratio < 1.75


def test_default_sensitivity_dampens_grade_toward_empirical_gap():
    # FR-4.3/NFR-1: the pure Minetti energy ratio (v ∝ 1/C) over-corrects real running
    # pace ~2×, so the default grade sensitivity dampens a 6% climb from ~+37% to the
    # empirical-GAP neighbourhood (~+13–20%).
    assert 0.13 < grade_penalty(0.06) < 0.20


def test_full_sensitivity_recovers_pure_minetti():
    # k_grade = 1.0 is the undamped constant-power model — pace penalty == energy ratio − 1.
    undamped = cost_of_transport(0.06) / cost_of_transport(0.0) - 1.0
    assert grade_penalty(0.06, k_grade=1.0) == undamped
