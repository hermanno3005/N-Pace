from pacelab.analyze import ActivityResult, SegmentResult
from pacelab.calibrate import fit_k_grade, fit_wbgt_a, is_steady
from pacelab.models.grade import cost_of_transport


def seg(pace, grade=0.0, temp=10.0, solar=0.0, dist=100.0):
    return SegmentResult(0, dist, grade, pace * dist / 1000.0, temp, 50.0, 0.0, 0.0,
                         0.0, 0.0, 0.0, pace, pace, False, solar, None)


def run(paces_grades, start_time=0.0, temp=10.0, solar=0.0):
    segs = [seg(p, g, temp=temp, solar=solar) for p, g in paces_grades]
    dist = sum(s.distance for s in segs)
    mean = sum(s.pace_obs for s in segs) / len(segs)
    return ActivityResult(mean, mean, 0.0, 0.0, 0.0, dist, segs, start_time=start_time)


def synthetic_run(k, base=300.0, temp=10.0, solar=0.0, start_time=0.0):
    """Constant-effort run over varied grades with a known grade sensitivity k."""
    grades = [-0.06, -0.03, 0.0, 0.02, 0.04, 0.06, 0.0, -0.02, 0.03, 0.05] * 3
    pg = [(base * (1 + k * (cost_of_transport(g) / cost_of_transport(0.0) - 1.0)), g)
          for g in grades]
    return run(pg, start_time=start_time, temp=temp, solar=solar)


def test_steady_run_passes_and_intervals_fail():
    steady = run([(300.0 + (i % 3), 0.0) for i in range(30)])
    intervals = run([(240.0 if i % 2 else 420.0, 0.0) for i in range(30)])
    assert is_steady(steady)
    assert not is_steady(intervals)


def test_fit_k_grade_recovers_the_planted_sensitivity():
    runs = [synthetic_run(k=0.5, start_time=i * 86400.0) for i in range(8)]
    fit = fit_k_grade(runs)
    assert abs(fit.value - 0.5) < 0.02
    assert fit.n_runs == 8


def test_fit_k_grade_ignores_interval_runs():
    runs = [synthetic_run(k=0.5)] * 6 + [run([(240.0 if i % 2 else 420.0, 0.02 * (i % 5))
                                              for i in range(30)])] * 4
    fit = fit_k_grade(runs)
    assert fit.n_runs == 6  # intervals excluded by steadiness
    assert abs(fit.value - 0.5) < 0.02


def test_fit_wbgt_a_recovers_the_planted_coefficient():
    # Flat steady runs across a season of temperatures with a known heat response
    # a = 0.001 (fraction per (WBGT-7.2)^2) and no fitness drift.
    from pacelab.models.wbgt import wbgt
    from pacelab.weather.conditions import Conditions

    runs = []
    for i, temp in enumerate([2.0, 6.0, 10.0, 14.0, 18.0, 22.0, 26.0, 30.0]):
        w = wbgt(Conditions(temp, 50.0, 0.0, 0.0, 0.0, 1013.0, 0.0))
        pace = 300.0 * (1 + 0.001 * max(0.0, w - 7.2) ** 2)
        runs.append(run([(pace, 0.0)] * 40, start_time=i * 7 * 86400.0, temp=temp))

    fit = fit_wbgt_a(runs, k_grade=0.4)
    assert abs(fit.value - 0.001) < 0.0002
    assert fit.n_runs == 8
    assert fit.r2 > 0.95
