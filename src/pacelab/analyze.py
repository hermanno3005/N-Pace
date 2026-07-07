"""Analyse an enriched activity into Normalized Pace + a cost decomposition (FR-7.4).

Pure over already-enriched segments (no I/O). Per segment it applies the engine to get the
normalized pace, then attributes the environmental cost to grade/heat/wind as an s/km
share (each ``fully_adjusted_pace × penalty``). Activity aggregates are distance-weighted.
The headline NP removes only the *applied* cost (grade + heat, ADR-0005); the decomposition
reports all three.
"""

from dataclasses import dataclass

from pacelab.config import Config
from pacelab.core import Segment
from pacelab.engine.cost import segment_cost
from pacelab.engine.normalize import normalize
from pacelab.weather.conditions import Conditions


@dataclass(frozen=True)
class SegmentResult:
    idx: int
    distance: float
    grade: float
    elapsed: float
    temperature_c: float
    humidity_pct: float
    wind_speed_ms: float
    wind_dir_deg: float
    p_grade: float
    p_heat: float
    p_wind: float
    pace_obs: float  # s/km
    pace_np: float  # s/km
    stopped: bool
    # Per-segment solar (ADR-0006: persist per-segment conditions). None doubles as the
    # confidence tag for the Heat Index fallback (ADR-0010): no solar data → HI was used.
    solar_radiation_wm2: float | None = None


@dataclass(frozen=True)
class ActivityResult:
    observed_pace: float  # s/km
    np_pace: float  # s/km (grade + heat removed)
    cost_grade: float  # s/km
    cost_heat: float  # s/km
    cost_wind: float  # s/km (reported, not applied)
    distance_m: float
    segments: list[SegmentResult]


def analyze(enriched: list[tuple[Segment, Conditions]], config: Config) -> ActivityResult:
    seg_results: list[SegmentResult] = []
    total_dist = total_t_obs = total_t_np = 0.0
    cost_grade = cost_heat = cost_wind = 0.0

    for idx, (s, c) in enumerate(enriched):
        if s.distance <= 0 or s.elapsed <= 0:
            continue
        cost = segment_cost(s, c, config)
        pace_obs = (s.elapsed / s.distance) * 1000.0
        pace_np = normalize(pace_obs, cost)
        fully_adjusted = pace_obs / cost.reported_factor
        dist_km = s.distance / 1000.0

        cost_grade += fully_adjusted * cost.p_grade * dist_km
        cost_heat += fully_adjusted * cost.p_heat * dist_km
        cost_wind += fully_adjusted * cost.p_wind * dist_km
        total_dist += s.distance
        total_t_obs += s.elapsed
        total_t_np += pace_np * dist_km

        seg_results.append(SegmentResult(
            idx=idx, distance=s.distance, grade=s.grade, elapsed=s.elapsed,
            temperature_c=c.temperature_c, humidity_pct=c.humidity_pct,
            wind_speed_ms=c.wind_speed_ms, wind_dir_deg=c.wind_dir_deg,
            p_grade=cost.p_grade, p_heat=cost.p_heat, p_wind=cost.p_wind,
            pace_obs=pace_obs, pace_np=pace_np, stopped=s.stopped,
            solar_radiation_wm2=c.solar_radiation_wm2,
        ))

    if total_dist == 0:
        return ActivityResult(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, seg_results)

    total_km = total_dist / 1000.0
    return ActivityResult(
        observed_pace=total_t_obs / total_km,
        np_pace=total_t_np / total_km,
        cost_grade=cost_grade / total_km,
        cost_heat=cost_heat / total_km,
        cost_wind=cost_wind / total_km,
        distance_m=total_dist,
        segments=seg_results,
    )
