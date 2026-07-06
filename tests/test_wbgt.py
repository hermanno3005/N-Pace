import pytest

from pacelab.models.wbgt import wbgt, wet_bulb_stull
from pacelab.weather.conditions import Conditions


def _cond(temp=10.0, rh=50.0, wind=0.0, solar=0.0):
    return Conditions(temp, rh, wind, 0.0, 0.0, 1013.0, solar)


def test_stull_wet_bulb_matches_reference_arithmetic():
    # Research (docs/research/wbgt-heat-model.md): 10 °C / 50% RH → 5.10 °C.
    assert wet_bulb_stull(10.0, 50.0) == pytest.approx(5.10, abs=0.05)


def test_wet_bulb_approaches_air_temp_at_saturation():
    assert wet_bulb_stull(20.0, 100.0) == pytest.approx(20.0, abs=0.6)


def test_wet_bulb_is_well_below_air_temp_when_dry():
    assert wet_bulb_stull(30.0, 20.0) < 20.0


def test_wbgt_at_reference_conditions_is_about_7_2():
    # Reference: 10 °C, 50% RH, no wind, no sun → WBGT_ref ≈ 7.2 °C (ADR-0010).
    assert wbgt(_cond(10.0, 50.0, 0.0, 0.0)) == pytest.approx(7.2, abs=0.1)


def test_wind_lowers_wbgt():
    # The intrinsic cooling coupling: more wind → lower WBGT (ADR-0001 dissolved).
    calm = wbgt(_cond(28.0, 60.0, wind=0.0, solar=600.0))
    windy = wbgt(_cond(28.0, 60.0, wind=6.0, solar=600.0))
    assert windy < calm


def test_solar_raises_wbgt():
    shade = wbgt(_cond(28.0, 60.0, wind=2.0, solar=0.0))
    sun = wbgt(_cond(28.0, 60.0, wind=2.0, solar=800.0))
    assert sun > shade
