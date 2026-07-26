import math

from pacelab.analyze import ActivityResult, SegmentResult
from pacelab.calibrate import fit_hr_conditioned_wbgt_a, fit_k_grade, fit_wbgt_a, is_steady
from pacelab.models.grade import cost_of_transport
from pacelab.models.wbgt import wbgt
from pacelab.weather.conditions import Conditions


def _wbgt_at(temp):
    return wbgt(Conditions(temp, 50.0, 0.0, 0.0, 0.0, 1013.0, 0.0))


def hr_run(temp, base_hr, a, start_time, n=40, warmup_frac=0.2):
    """A flat steady run at a given HR and temperature, planted heat coefficient `a`.

    pace = P0·(1 + hr_gain·(HR-150) + a·(WBGT-7.2)²); early segments are warmup (HR still
    climbing) so pace/HR is inconsistent there and must be dropped by the fitter.
    """
    w2 = max(0.0, _wbgt_at(temp) - 7.2) ** 2
    segs = []
    t = start_time
    for i in range(n):
        warm = i < n * warmup_frac
        hr = base_hr - (25 if warm else 0)  # warmup: HR lags low
        pace = 300.0 * (1 - 0.004 * (base_hr - 150) + a * w2)
        if warm:
            pace *= 0.8  # ran faster than HR implies during warmup — the trap
        segs.append(SegmentResult(i, 100.0, 0.0, pace * 100.0 / 1000.0, temp, 50.0, 0.0,
                                  0.0, 0.0, 0.0, 0.0, pace, pace, False, 100.0, avg_hr=hr))
        t += pace * 100.0 / 1000.0
    mean = sum(s.pace_obs for s in segs) / len(segs)
    return ActivityResult(mean, mean, 0.0, 0.0, 0.0, sum(s.distance for s in segs), segs,
                          start_time=start_time)


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
    runs = [synthetic_run(k=0.5, start_time=j * 86400.0) for j in range(6)]
    runs += [run([(240.0 if i % 2 else 420.0, 0.02 * (i % 5)) for i in range(30)],
                 start_time=j * 86400.0) for j in range(6, 10)]
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


def test_fit_wbgt_a_abstains_when_every_run_shares_a_timestamp():
    # A database migrated before start_time existed loads every activity at t=0.0, making
    # the drift column a copy of the intercept. The design is singular: abstain (FR-8.2)
    # rather than divide by a zero pivot.
    from pacelab.models.wbgt import wbgt
    from pacelab.weather.conditions import Conditions

    runs = []
    for temp in [2.0, 6.0, 10.0, 14.0, 18.0, 22.0, 26.0, 30.0]:
        w = wbgt(Conditions(temp, 50.0, 0.0, 0.0, 0.0, 1013.0, 0.0))
        pace = 300.0 * (1 + 0.001 * max(0.0, w - 7.2) ** 2)
        runs.append(run([(pace, 0.0)] * 40, start_time=0.0, temp=temp))

    assert fit_wbgt_a(runs, k_grade=0.4) is None


def test_fit_wbgt_a_is_invariant_to_the_time_origin_when_the_athlete_drifts():
    # `a` is a fraction of baseline pace. Normalising by the regression intercept means
    # dividing by pace extrapolated back to 1 Jan 1970 — with a real drift term and real
    # epoch timestamps that is off by a factor of four. Same season, two time origins,
    # same answer.
    def season(base_t):
        runs = []
        for i, temp in enumerate([2.0, 6.0, 10.0, 14.0, 18.0, 22.0, 26.0, 30.0]):
            pace = 300.0 * (1 + 0.001 * max(0.0, _wbgt_at(temp) - 7.2) ** 2) - 0.05 * (i * 7)
            runs.append(run([(pace, 0.0)] * 40, start_time=base_t + i * 7 * 86400.0,
                            temp=temp))
        return fit_wbgt_a(runs, k_grade=0.4)

    epoch_2026 = 1767225600.0
    assert abs(season(0.0).value - 0.001) < 0.0001
    assert abs(season(epoch_2026).value - 0.001) < 0.0001


def test_hr_conditioned_fit_agrees_with_its_run_mean_refit():
    # Segments within a run are autocorrelated; the run-mean refit is the sensitivity
    # check. On clean data the two must land in the same place.
    temps = [2.0, 8.0, 14.0, 20.0, 26.0, 30.0]
    hrs = [140, 165, 150, 175, 145, 160]
    runs = [hr_run(t, h, a=0.0004, start_time=i * 3 * 86400.0)
            for i, (t, h) in enumerate(zip(temps * 3, hrs * 3))]
    fit = fit_hr_conditioned_wbgt_a(runs)
    assert fit.hr_coeff < 0  # higher HR → faster → fewer s/km
    assert fit.run_mean_value is not None
    assert abs(fit.run_mean_value - fit.value) < 0.00005


def test_hr_conditioned_fit_recovers_planted_a_despite_effort_variation():
    # Runs vary BOTH in HR (effort) and temperature, independently — the HR covariate must
    # separate effort from heat and recover the planted a=0.0004.
    runs = []
    temps = [2.0, 8.0, 14.0, 20.0, 26.0, 30.0]
    hrs = [140, 165, 150, 175, 145, 160]  # effort deliberately NOT aligned with temp
    for i, (temp, hr) in enumerate(zip(temps * 3, (hrs * 3))):
        runs.append(hr_run(temp, hr, a=0.0004, start_time=i * 3 * 86400.0))
    fit = fit_hr_conditioned_wbgt_a(runs)
    assert fit is not None
    assert abs(fit.value - 0.0004) < 0.00012
    assert fit.r2 is not None


def test_hr_conditioned_fit_abstains_when_effort_and_heat_are_collinear():
    # Ran easy when cool, hard when hot (HR rises with temp) — effort and heat can't be
    # separated; the fit must abstain rather than launder the confound.
    runs = []
    for i, temp in enumerate([4.0, 10.0, 16.0, 22.0, 28.0, 32.0] * 3):
        hr = 130 + temp * 2  # HR perfectly tracks temperature
        runs.append(hr_run(temp, hr, a=0.0004, start_time=i * 3 * 86400.0))
    assert fit_hr_conditioned_wbgt_a(runs) is None
