import pytest

from pacelab.models.heat import heat_penalty
from pacelab.weather.conditions import Conditions


def _c(temp, rh):
    return Conditions(temp, rh, 0.0, 0.0, 0.0, 1013.0)


def test_reference_temperature_has_no_penalty():
    # Reference is 10 °C (ADR-0002); at/below it there is nothing to remove.
    assert heat_penalty(_c(10.0, 50.0)) == 0.0


def test_cold_has_no_penalty():
    assert heat_penalty(_c(2.0, 50.0)) == 0.0


def test_penalty_increases_monotonically_with_temperature():
    assert heat_penalty(_c(30.0, 50.0)) > heat_penalty(_c(20.0, 50.0)) > heat_penalty(_c(15.0, 50.0)) > 0


def test_humidity_increases_the_penalty_in_the_heat():
    # The whole reason for Heat Index over air temperature: mugginess wrecks hot runs.
    assert heat_penalty(_c(30.0, 85.0)) > heat_penalty(_c(30.0, 30.0))
