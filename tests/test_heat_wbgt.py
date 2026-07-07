import pytest

from pacelab.models.heat import heat_index_c, heat_penalty
from pacelab.weather.conditions import Conditions


def _solar(temp, rh, wind, solar):
    return Conditions(temp, rh, wind, 0.0, 0.0, 1013.0, solar)


def test_wbgt_path_is_zero_at_reference():
    # 10 °C / 50% / no wind / no sun → WBGT ≈ 7.2 = WBGT_ref → penalty 0.
    assert heat_penalty(_solar(10.0, 50.0, 0.0, 0.0)) == pytest.approx(0.0, abs=1e-6)


def test_wbgt_path_penalises_a_hot_sunny_run():
    assert heat_penalty(_solar(28.0, 60.0, 2.0, 800.0)) > 0


def test_wind_reduces_the_heat_penalty_through_wbgt():
    calm = heat_penalty(_solar(28.0, 60.0, 0.0, 600.0))
    windy = heat_penalty(_solar(28.0, 60.0, 6.0, 600.0))
    assert windy < calm


def test_falls_back_to_heat_index_when_solar_is_missing():
    # No solar field → v1 Heat Index path, unchanged.
    conditions = Conditions(30.0, 60.0, 0.0, 0.0, 0.0, 1013.0)  # solar defaults None
    hi = heat_index_c(30.0, 60.0)
    expected = 0.0018 * max(0.0, hi - 10.0) ** 1.5
    assert heat_penalty(conditions) == pytest.approx(expected)
