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
from pacelab.models.grade import cost_of_transport
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
    """Distance-weighted mean WBGT over segments that have solar data."""
    total_d = total = 0.0
    for s in result.segments:
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

    # 3-param LSQ: y = b0 + b1·t + b2·w2, solved via normal equations.
    def solve3(rows):
        import itertools
        X = [(1.0, t, w2) for t, w2, _ in rows]
        y = [p for _, _, p in rows]
        A = [[sum(xi[i] * xi[j] for xi in X) for j in range(3)] for i in range(3)]
        v = [sum(xi[i] * yi for xi, yi in zip(X, y)) for i in range(3)]
        # Gaussian elimination
        for col in range(3):
            pivot = max(range(col, 3), key=lambda r_: abs(A[r_][col]))
            A[col], A[pivot] = A[pivot], A[col]
            v[col], v[pivot] = v[pivot], v[col]
            for r_ in range(col + 1, 3):
                f = A[r_][col] / A[col][col]
                for c_ in range(col, 3):
                    A[r_][c_] -= f * A[col][c_]
                v[r_] -= f * v[col]
        b = [0.0, 0.0, 0.0]
        for i in (2, 1, 0):
            b[i] = (v[i] - sum(A[i][j] * b[j] for j in range(i + 1, 3))) / A[i][i]
        return b

    b0, b1, b2 = solve3(rows)
    if b0 <= 0:
        return None
    preds = [b0 + b1 * t + b2 * w2 for t, w2, _ in rows]
    ys = [p for _, _, p in rows]
    mean_y = sum(ys) / len(ys)
    ss_res = sum((y - p) ** 2 for y, p in zip(ys, preds))
    ss_tot = sum((y - mean_y) ** 2 for y in ys) or 1.0
    return Fit(value=b2 / b0, n_runs=len(rows),
               spread=(ss_res / len(rows)) ** 0.5, r2=1 - ss_res / ss_tot)