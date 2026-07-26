"""Personal calibration by NP-stability (ADR-0006), report-only.

Two regressions, each run in the regime where effort is most nearly constant:

- **k_grade** within single runs: inside one steady run, effort is ~constant while grade
  varies, so each run is its own controlled experiment. Model ``pace_i = P0·(1 + k·e_i)``
  (``e_i`` = raw Minetti energy ratio − 1); least squares gives one k per run; the athlete's
  k is the median across runs.
- **wbgt_a** between runs: heat is constant within a run, so it only shows across runs.
  Model ``pace_gc = P0·(1 + drift·t + a·max(0, WBGT − ref)²)`` over grade-corrected steady
  runs, with a linear drift term so genuine fitness change isn't mistaken for weather.

Interval sessions (fast reps mixed with slow recoveries, elevated HR) violate the
constant-effort assumption, so calibration only consumes **steady** runs — moving-segment
pace dispersion below a threshold. Guards per FR-8.2: minimum run counts and condition
spread; fit quality reported; nothing is applied silently.
"""

from dataclasses import dataclass
from statistics import median

from pacelab.analyze import ActivityResult
from pacelab.models.grade import DEFAULT_GRADE_SENSITIVITY, cost_of_transport
from pacelab.models.heat import WBGT_REF_C
from pacelab.models.wbgt import wbgt
from pacelab.weather.conditions import Conditions

MAX_STEADY_CV = 0.10  # moving-pace dispersion above this = intervals/surges, excluded
MIN_DISTANCE_M = 3000.0  # junk fragments excluded
_C0 = cost_of_transport(0.0)


@dataclass(frozen=True)
class Fit:
    value: float
    n_runs: int
    spread: float  # IQR for k_grade; residual std for wbgt_a
    r2: float | None = None


def _moving(result: ActivityResult):
    return [s for s in result.segments if not s.stopped and s.elapsed > 0 and s.distance > 0]


def is_steady(result: ActivityResult, max_cv: float = MAX_STEADY_CV) -> bool:
    """True when moving-segment paces are tight — the constant-effort prerequisite."""
    segs = _moving(result)
    if len(segs) < 10:
        return False
    paces = [s.pace_obs for s in segs]
    mean = sum(paces) / len(paces)
    var = sum((p - mean) ** 2 for p in paces) / len(paces)
    return (var**0.5) / mean <= max_cv


def _energy_ratio(grade: float) -> float:
    return cost_of_transport(grade) / _C0 - 1.0


def _solve_lsq(X, y):
    """Least squares for ``y ≈ X·b`` via normal equations. None when unidentifiable.

    A pivot that vanishes relative to the matrix scale means the design is singular or
    near-singular — e.g. every run carrying the same timestamp (a database migrated before
    start_time existed loads them all as 0.0), which makes the drift column a copy of the
    intercept. Report nothing rather than dividing by ~0 and returning noise.
    """
    n = len(X[0])
    A = [[sum(xi[i] * xi[j] for xi in X) for j in range(n)] for i in range(n)]
    v = [sum(xi[i] * yi for xi, yi in zip(X, y)) for i in range(n)]
    scale = max(abs(a) for row in A for a in row)
    if scale == 0:
        return None
    for col in range(n):
        pivot = max(range(col, n), key=lambda r_: abs(A[r_][col]))
        A[col], A[pivot] = A[pivot], A[col]
        v[col], v[pivot] = v[pivot], v[col]
        if abs(A[col][col]) <= 1e-12 * scale:
            return None
        for r_ in range(col + 1, n):
            f = A[r_][col] / A[col][col]
            for c_ in range(col, n):
                A[r_][c_] -= f * A[col][c_]
            v[r_] -= f * v[col]
    b = [0.0] * n
    for i in reversed(range(n)):
        b[i] = (v[i] - sum(A[i][j] * b[j] for j in range(i + 1, n))) / A[i][i]
    return b


def _r2(ys, preds):
    mean_y = sum(ys) / len(ys)
    ss_res = sum((y - p) ** 2 for y, p in zip(ys, preds))
    ss_tot = sum((y - mean_y) ** 2 for y in ys) or 1.0
    return 1 - ss_res / ss_tot, (ss_res / len(ys)) ** 0.5


def _corr(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    return cov / (sx * sy) if sx and sy else 0.0


def _lsq2(xs, ys):
    """Least squares y = a + b·x."""
    n = len(xs)
    sx, sy = sum(xs), sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    d = n * sxx - sx * sx
    if d == 0:
        return None
    b = (n * sxy - sx * sy) / d
    a = (sy - b * sx) / n
    return a, b


def fit_k_grade(results: list[ActivityResult], min_grade_std: float = 0.015) -> Fit | None:
    """The athlete's grade sensitivity: median of per-steady-run regression slopes."""
    ks = []
    for r in results:
        if r.distance_m < MIN_DISTANCE_M or not is_steady(r):
            continue
        segs = _moving(r)
        es = [_energy_ratio(s.grade) for s in segs]
        mean_e = sum(es) / len(es)
        if (sum((e - mean_e) ** 2 for e in es) / len(es)) ** 0.5 < min_grade_std:
            continue  # too flat to inform the fit
        coeffs = _lsq2(es, [s.pace_obs for s in segs])
        if coeffs is None or coeffs[0] <= 0:
            continue
        ks.append(coeffs[1] / coeffs[0])  # pace = a + b·e  →  P0·(1+k·e): k = b/a
    if len(ks) < 5:
        return None  # FR-8.2: too sparse — keep population defaults
    ks.sort()
    q1, q3 = ks[len(ks) // 4], ks[(3 * len(ks)) // 4]
    return Fit(value=median(ks), n_runs=len(ks), spread=q3 - q1)


def _run_wbgt(result: ActivityResult) -> float | None:
    """Distance-weighted mean WBGT over moving segments that have solar data."""
    total_d = total = 0.0
    for s in _moving(result):
        if s.solar_radiation_wm2 is None:
            continue
        c = Conditions(s.temperature_c, s.humidity_pct, s.wind_speed_ms, s.wind_dir_deg,
                       0.0, 1013.0, s.solar_radiation_wm2)
        total += wbgt(c) * s.distance
        total_d += s.distance
    return total / total_d if total_d else None


def fit_wbgt_a(results: list[ActivityResult], k_grade: float,
               wbgt_ref: float = WBGT_REF_C) -> Fit | None:
    """The athlete's heat response: pace_gc = P0·(1 + drift·t + a·max(0,W−ref)²)."""
    rows = []  # (t_days, w2, grade-corrected pace)
    for r in results:
        if r.distance_m < MIN_DISTANCE_M or not is_steady(r):
            continue
        w = _run_wbgt(r)
        if w is None:
            continue
        segs = _moving(r)
        gc = [s.pace_obs / (1 + k_grade * _energy_ratio(s.grade)) for s in segs]
        rows.append((r.start_time / 86400.0, max(0.0, w - wbgt_ref) ** 2, sum(gc) / len(gc)))
    if len(rows) < 8:
        return None
    w2s = [w2 for _, w2, _ in rows]
    if max(w2s) - min(w2s) < 25.0:  # < ~5 °C WBGT spread above ref — can't identify heat
        return None

    # 3-param LSQ: y = b0 + b1·t + b2·w2.
    ys = [p for _, _, p in rows]
    coeffs = _solve_lsq([(1.0, t, w2) for t, w2, _ in rows], ys)
    if coeffs is None:
        return None
    b0, b1, b2 = coeffs
    # `a` is a *fraction* of baseline pace, so b2 must be divided by the athlete's actual
    # baseline — not by b0, which is pace extrapolated back to the epoch (1 Jan 1970) and
    # is off by decades of the drift term. P0 = the mean fitted pace with heat removed,
    # which is invariant to where the time axis is anchored.
    p0 = sum(y - b2 * w2 for y, (_, w2, _) in zip(ys, rows)) / len(rows)
    if p0 <= 0:
        return None
    preds = [b0 + b1 * t + b2 * w2 for t, w2, _ in rows]
    r2, resid = _r2(ys, preds)
    return Fit(value=b2 / p0, n_runs=len(rows), spread=resid, r2=r2)


@dataclass(frozen=True)
class HrFit:
    """An HR-conditioned heat fit plus the diagnostics ADR-0014 requires it to report."""

    value: float
    n_runs: int
    n_segments: int
    spread: float  # residual std, s/km
    r2: float  # optimistic: segments within a run are autocorrelated
    hr_coeff: float  # s/km per bpm; should be negative (higher HR → faster)
    hr_wbgt_corr: float  # how confounded effort and heat were
    run_mean_value: float | None  # same fit on run means — sensitivity to autocorrelation


MAX_HR_WBGT_CORR = 0.80  # above this, effort and heat aren't separable — abstain
_WARMUP_HR_FRAC = 0.97  # leading segments below this × the run's median HR are warmup


def _warmed_up(segs):
    """Drop the leading segments where HR is still climbing toward the run's level.

    Warmup pace and warmup HR tell inconsistent stories (you are already running while the
    heart is still catching up), so those segments would bias the HR coefficient.
    """
    hrs = sorted(s.avg_hr for s in segs)
    threshold = median(hrs) * _WARMUP_HR_FRAC
    for i, s in enumerate(segs):
        if s.avg_hr >= threshold:
            return segs[i:]
    return []


def fit_hr_conditioned_wbgt_a(
    results: list[ActivityResult],
    k_grade: float = DEFAULT_GRADE_SENSITIVITY,
    wbgt_ref: float = WBGT_REF_C,
) -> HrFit | None:
    """The heat penalty at constant heart rate (ADR-0014), report-only.

    ``pace_gc = b0 + b_hr·HR + b_t·time_in_run + b_w·max(0, W−ref)²``, fitted over
    warmed-up moving segments of steady runs. Effort *is* HR here, so the fit is
    intent-proof: an easy hot jog lands at low HR and is absorbed by the HR term instead
    of masquerading as a heat penalty. Abstains (FR-8.2) on thin data, on too little WBGT
    spread, and — the confound this fit exists to expose — when HR and heat are collinear.
    """
    per_run = []  # one list of (hr, t_in_run, w2, grade-corrected pace) rows per run
    for r in results:
        if r.distance_m < MIN_DISTANCE_M or not is_steady(r):
            continue
        w = _run_wbgt(r)
        if w is None:
            continue
        segs = [s for s in _moving(r) if s.avg_hr is not None]
        if len(segs) < 10:
            continue
        segs = _warmed_up(segs)
        if len(segs) < 5:
            continue
        w2 = max(0.0, w - wbgt_ref) ** 2
        # Elapsed accumulates from the run's start, so within-run cardiac drift gets its
        # own term instead of leaking into the heat coefficient.
        t_in_run = 0.0
        run_rows = []
        for s in segs:
            run_rows.append((s.avg_hr, t_in_run,
                             w2, s.pace_obs / (1 + k_grade * _energy_ratio(s.grade))))
            t_in_run += s.elapsed
        per_run.append(run_rows)

    rows = [row for run_rows in per_run for row in run_rows]
    n_runs = len(per_run)
    if n_runs < 8 or len(rows) < 40:
        return None
    hrs = [hr for hr, _, _, _ in rows]
    w2s = [w2 for _, _, w2, _ in rows]
    if max(w2s) - min(w2s) < 25.0:  # < ~5 °C WBGT spread above ref
        return None
    corr = _corr(hrs, w2s)
    if abs(corr) > MAX_HR_WBGT_CORR:
        return None  # ran easy when cool / hard when hot — the confound isn't separable

    ys = [p for _, _, _, p in rows]
    coeffs = _solve_lsq([(1.0, hr, t, w2) for hr, t, w2, _ in rows], ys)
    if coeffs is None:
        return None
    b0, b_hr, b_t, b_w = coeffs
    p0 = sum(y - b_w * w2 for y, w2 in zip(ys, w2s)) / len(rows)
    if p0 <= 0:
        return None
    preds = [b0 + b_hr * hr + b_t * t + b_w * w2 for hr, t, w2, _ in rows]
    r2, resid = _r2(ys, preds)
    return HrFit(value=b_w / p0, n_runs=n_runs, n_segments=len(rows), spread=resid, r2=r2,
                 hr_coeff=b_hr, hr_wbgt_corr=corr,
                 run_mean_value=_refit_on_run_means(per_run))


def _refit_on_run_means(per_run) -> float | None:
    """The same fit on one row per run — sensitivity check against segment autocorrelation.

    Segments inside a run are highly correlated, so the segment-level R² is optimistic and
    long runs carry more weight than they earn. If collapsing each run to its means moves
    `a` a lot, the segment-level fit was leaning on that structure.

    ``time_in_run`` is dropped: it exists to absorb *within*-run cardiac drift, and its
    per-run mean is very nearly the same number for every run — keeping it would hand the
    solver a near-copy of the intercept column.
    """
    means = [[sum(c) / len(rows) for c in zip(*rows)] for rows in per_run]
    coeffs = _solve_lsq([(1.0, hr, w2) for hr, _, w2, _ in means], [p for *_, p in means])
    if coeffs is None:
        return None
    b_w = coeffs[2]
    p0 = sum(p - b_w * w2 for *_, w2, p in means) / len(means)
    return b_w / p0 if p0 > 0 else None
