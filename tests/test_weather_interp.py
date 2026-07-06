import pytest

from pacelab.weather.conditions import Conditions
from pacelab.weather.interpolate import interpolate_conditions


def _cond(temp=10.0, hum=50.0, wspd=2.0, wdir=180.0, cloud=0.0, press=1013.0):
    return Conditions(temp, hum, wspd, wdir, cloud, press)


def test_temperature_is_linearly_interpolated_in_time():
    hourly = [(0.0, _cond(temp=10.0)), (3600.0, _cond(temp=20.0))]
    assert interpolate_conditions(hourly, 1800.0).temperature_c == pytest.approx(15.0)


def test_wind_direction_interpolates_across_the_360_wrap():
    # 350° and 10° straddle north — the shortest path midpoint is 0°, not 180°.
    hourly = [(0.0, _cond(wdir=350.0)), (3600.0, _cond(wdir=10.0))]
    result = interpolate_conditions(hourly, 1800.0).wind_dir_deg
    assert result == pytest.approx(0.0) or result == pytest.approx(360.0)


def test_solar_radiation_is_interpolated_in_time():
    hourly = [
        (0.0, Conditions(20.0, 50.0, 2.0, 180.0, 0.0, 1013.0, 0.0)),
        (3600.0, Conditions(20.0, 50.0, 2.0, 180.0, 0.0, 1013.0, 800.0)),
    ]
    assert interpolate_conditions(hourly, 1800.0).solar_radiation_wm2 == pytest.approx(400.0)


def test_missing_solar_stays_none_through_interpolation():
    hourly = [(0.0, _cond(temp=10.0)), (3600.0, _cond(temp=20.0))]  # solar defaults None
    assert interpolate_conditions(hourly, 1800.0).solar_radiation_wm2 is None


def test_times_outside_the_range_clamp_to_the_nearest_hour():
    hourly = [(0.0, _cond(temp=10.0)), (3600.0, _cond(temp=20.0))]
    assert interpolate_conditions(hourly, -100.0).temperature_c == 10.0
    assert interpolate_conditions(hourly, 9999.0).temperature_c == 20.0
