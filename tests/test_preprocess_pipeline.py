import math

from pacelab.core import Track, Trackpoint
from pacelab.preprocess.pipeline import to_segments


def test_elevation_is_smoothed_before_grade_is_computed():
    # A lone +30 m elevation spike must not turn into a bogus grade — smoothing runs
    # first (FR-2.2), so the segment grades stay near flat.
    lat = 48.0
    lon_step = 30 / (111_320 * math.cos(math.radians(lat)))
    eles = [100.0] * 20
    eles[10] = 130.0  # single-sample spike
    track = Track([Trackpoint(t=i * 10.0, lat=lat, lon=i * lon_step, ele=eles[i]) for i in range(20)])

    segs = to_segments(track, step_m=100)

    assert max(abs(s.grade) for s in segs) < 0.02
