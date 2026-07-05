from pacelab.preprocess.smoothing import smooth_elevation


def test_isolated_spike_is_suppressed():
    # A single-sample GPS/baro spike must not survive into grade computation (FR-2.2).
    elevations = [100, 100, 100, 140, 100, 100, 100]
    smoothed = smooth_elevation(elevations)
    assert smoothed[3] == 100


def test_sustained_ramp_is_preserved():
    # A real climb must pass through unchanged — smoothing kills noise, not signal.
    ramp = [100 + i for i in range(11)]
    smoothed = smooth_elevation(ramp)
    assert smoothed == ramp


def test_endpoints_are_preserved():
    elevations = [50, 60, 70, 80, 90]
    smoothed = smooth_elevation(elevations)
    assert smoothed[0] == 50
    assert smoothed[-1] == 90
