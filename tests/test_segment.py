import math

import pytest

from pacelab.core import Track, Trackpoint
from pacelab.preprocess.segment import haversine, segment_track


def straight_east_track(n: int, spacing_m: float, lat: float = 48.0, ele: float = 100.0,
                        dt: float = 10.0) -> Track:
    """A synthetic due-east track: n points, `spacing_m` apart, flat, evenly timed."""
    lon_step = spacing_m / (111_320 * math.cos(math.radians(lat)))
    pts = [Trackpoint(t=i * dt, lat=lat, lon=i * lon_step, ele=ele) for i in range(n)]
    return Track(points=pts)


def sloped_east_track(n: int, spacing_m: float, grade: float, lat: float = 48.0,
                      dt: float = 10.0) -> Track:
    """A due-east track climbing at a constant grade (rise/run)."""
    lon_step = spacing_m / (111_320 * math.cos(math.radians(lat)))
    pts = [
        Trackpoint(t=i * dt, lat=lat, lon=i * lon_step, ele=100.0 + i * spacing_m * grade)
        for i in range(n)
    ]
    return Track(points=pts)


def test_constant_slope_track_recovers_grade():
    track = sloped_east_track(n=20, spacing_m=30, grade=0.05)
    segs = segment_track(track, step_m=100)
    for s in segs:
        assert s.grade == pytest.approx(0.05, abs=1e-3)


def test_due_east_track_has_bearing_90():
    segs = segment_track(straight_east_track(n=10, spacing_m=30), step_m=100)
    for s in segs:
        assert s.bearing == pytest.approx(90.0, abs=0.5)


def test_segments_are_step_sized_with_shorter_remainder():
    # 270 m at 100 m step → 100, 100, 70.
    segs = segment_track(straight_east_track(n=10, spacing_m=30), step_m=100)
    assert [round(s.distance) for s in segs] == [100, 100, 70]


def test_stoppage_is_flagged_when_the_runner_pauses():
    # FR-2.4: a pause must be flagged so it doesn't distort pace. Run east at 3 m/s,
    # pause 120 s in place, then resume. The segment spanning the pause reads as very
    # slow and is flagged; the moving segments are not.
    lat = 48.0
    lon_step = 30 / (111_320 * math.cos(math.radians(lat)))
    pts = []
    t = 0.0
    for i in range(6):  # 0..150 m moving
        pts.append(Trackpoint(t=t, lat=lat, lon=i * lon_step, ele=100.0))
        t += 10.0
    pts.append(Trackpoint(t=t + 120.0, lat=lat, lon=5 * lon_step, ele=100.0))  # 120 s pause
    t += 120.0
    for i in range(6, 12):  # resume moving
        t += 10.0
        pts.append(Trackpoint(t=t, lat=lat, lon=i * lon_step, ele=100.0))

    segs = segment_track(Track(points=pts), step_m=100)
    assert any(s.stopped for s in segs)
    moving = [s for s in segs if not s.stopped]
    assert moving and all(s.distance / s.elapsed > 1.0 for s in moving)


def test_normal_running_is_never_flagged_as_stopped():
    segs = segment_track(straight_east_track(n=20, spacing_m=30), step_m=100)
    assert not any(s.stopped for s in segs)


def test_segments_carry_mean_heart_rate():
    # HR feeds calibration (steadiness detection, effort cross-check); a segment's hr is
    # the mean of the raw points inside its distance window.
    lat = 48.0
    lon_step = 30 / (111_320 * math.cos(math.radians(lat)))
    pts = [Trackpoint(t=i * 10.0, lat=lat, lon=i * lon_step, ele=100.0, hr=140 + i)
           for i in range(10)]
    segs = segment_track(Track(points=pts), step_m=100)
    assert segs[0].hr is not None
    assert 140 <= segs[0].hr <= 144  # mean of the first ~4 points
    assert segs[-1].hr > segs[0].hr  # rising HR visible across segments


def test_segments_without_hr_data_have_none():
    segs = segment_track(straight_east_track(n=10, spacing_m=30), step_m=100)
    assert all(s.hr is None for s in segs)


def test_segmentation_conserves_distance():
    # Resampling a track into segments must not lose or invent length: the segment
    # distances sum to the raw polyline length.
    track = straight_east_track(n=10, spacing_m=30)  # ~270 m
    raw_len = sum(
        haversine(a.lat, a.lon, b.lat, b.lon)
        for a, b in zip(track.points, track.points[1:])
    )
    segs = segment_track(track, step_m=100)
    assert sum(s.distance for s in segs) == pytest.approx(raw_len, rel=1e-6)


def test_tiny_final_remainder_merges_into_the_previous_segment():
    # A trailing 30 m sliver gets garbage grade from baro noise over a few metres —
    # remainders under half a step merge into the last full segment instead.
    track = straight_east_track(n=24, spacing_m=10)  # ~230 m
    raw_len = sum(haversine(a.lat, a.lon, b.lat, b.lon)
                  for a, b in zip(track.points, track.points[1:]))
    segs = segment_track(track, step_m=100)
    assert [round(s.distance) for s in segs] == [100, 130]
    assert sum(s.distance for s in segs) == pytest.approx(raw_len, rel=1e-6)
