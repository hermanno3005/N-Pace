import pytest

from pacelab.models.wind import air_density
from pacelab.weather.conditions import Conditions


def _cond(temp, pressure):
    return Conditions(temp, 50.0, 0.0, 0.0, 0.0, pressure)


def test_standard_sea_level_air_density():
    # Textbook: dry air at 15 °C, 1013.25 hPa is ~1.225 kg/m³.
    assert air_density(_cond(15.0, 1013.25)) == pytest.approx(1.225, abs=0.005)


def test_colder_air_is_denser():
    assert air_density(_cond(0.0, 1013.25)) > air_density(_cond(30.0, 1013.25))


def test_thinner_air_at_altitude_is_less_dense():
    # Lower surface pressure (e.g. Munich ~956 hPa) → less dense than sea level.
    assert air_density(_cond(15.0, 956.0)) < air_density(_cond(15.0, 1013.25))
