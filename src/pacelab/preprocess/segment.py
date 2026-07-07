"""Resample a Track into fixed-distance Segments (D-4: 100 m default; FR-2.3).

Segments are chunks of the track's cumulative along-path distance, so their distances sum
exactly to the polyline length. Each segment carries the grade, initial bearing, elapsed
time, and midpoint position the impact models and weather lookup need.
"""

import math

from pacelab.core import Segment, Track

_EARTH_RADIUS_M = 6_371_000.0


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


def initial_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle course from point 1 to point 2, in degrees 0–360."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlmb = math.radians(lon2 - lon1)
    y = math.sin(dlmb) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlmb)
    return math.degrees(math.atan2(y, x)) % 360.0


def _cumulative_distances(points) -> list[float]:
    cum = [0.0]
    for a, b in zip(points, points[1:]):
        cum.append(cum[-1] + haversine(a.lat, a.lon, b.lat, b.lon))
    return cum


def _interpolate(points, cum: list[float], d: float):
    """(lat, lon, ele, t) at along-path distance `d`, linearly between raw points."""
    if d <= 0:
        p = points[0]
        return p.lat, p.lon, p.ele, p.t
    if d >= cum[-1]:
        p = points[-1]
        return p.lat, p.lon, p.ele, p.t
    # Find the edge [i, i+1] containing d.
    hi = 1
    while cum[hi] < d:
        hi += 1
    lo = hi - 1
    span = cum[hi] - cum[lo]
    frac = 0.0 if span == 0 else (d - cum[lo]) / span
    a, b = points[lo], points[hi]
    return (
        a.lat + frac * (b.lat - a.lat),
        a.lon + frac * (b.lon - a.lon),
        a.ele + frac * (b.ele - a.ele),
        a.t + frac * (b.t - a.t),
    )


# Below this average speed a segment is treated as a pause, not running (FR-2.4).
# 0.5 m/s ≈ 33 min/km — slower than a slow walk, so only genuine stops trip it.
STOP_SPEED_MS = 0.5


def segment_track(track: Track, step_m: float = 100.0, stop_speed_ms: float = STOP_SPEED_MS) -> list[Segment]:
    points = track.points
    if len(points) < 2:
        return []
    cum = _cumulative_distances(points)
    total = cum[-1]

    # Boundary distances: 0, step, 2·step, …, total. A trailing remainder shorter than
    # half a step merges into the previous segment — over a few metres, baro noise turns
    # grade into garbage (observed: +146 grade on a 3.7 m sliver).
    boundaries = [0.0]
    while boundaries[-1] + step_m < total:
        boundaries.append(boundaries[-1] + step_m)
    if len(boundaries) > 1 and total - boundaries[-1] < step_m / 2:
        boundaries.pop()
    boundaries.append(total)

    # Pauses are detected on the raw edges (not on diluted segment averages): an edge
    # where the runner barely moved over a real time gap. Each pause is located at its
    # start distance so it can be attributed to the segment window that contains it.
    pauses = []  # (distance_position, pause_seconds)
    for i in range(len(points) - 1):
        dt = points[i + 1].t - points[i].t
        if dt > 0 and (cum[i + 1] - cum[i]) / dt < stop_speed_ms:
            pauses.append((cum[i], dt))

    segments: list[Segment] = []
    for d0, d1 in zip(boundaries, boundaries[1:]):
        lat0, lon0, ele0, t0 = _interpolate(points, cum, d0)
        lat1, lon1, ele1, t1 = _interpolate(points, cum, d1)
        latm, lonm, _, _ = _interpolate(points, cum, (d0 + d1) / 2)
        distance = d1 - d0
        grade = (ele1 - ele0) / distance if distance > 0 else 0.0
        # Subtract paused time inside this window so the segment's pace is moving pace.
        # Clamp to the wall-clock span: a pause edge straddling the window boundary must
        # not subtract more time than the segment actually took.
        wall = t1 - t0
        pause_time = min(sum(dt for pos, dt in pauses if d0 <= pos < d1), wall)
        moving_elapsed = wall - pause_time
        hrs = [p.hr for p, d in zip(points, cum) if d0 <= d < d1 and p.hr is not None]
        segments.append(
            Segment(
                distance=distance,
                grade=grade,
                bearing=initial_bearing(lat0, lon0, lat1, lon1),
                elapsed=moving_elapsed,
                lat=latm,
                lon=lonm,
                start_time=t0,
                stopped=pause_time > 0,
                hr=sum(hrs) / len(hrs) if hrs else None,
            )
        )
    return segments
