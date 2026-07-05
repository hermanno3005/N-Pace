import pytest

from pacelab.weather.conditions import Conditions
from pacelab.weather.service import WeatherService


def hourly_series():
    # 24 hourly readings on 1970-01-01 (epoch 0); temperature == hour, rest constant.
    return [(h * 3600.0, Conditions(float(h), 50.0, 2.0, 180.0, 0.0, 1013.0)) for h in range(24)]


class StubFetcher:
    def __init__(self, series):
        self.series = series
        self.calls = 0

    def fetch_hourly(self, lat, lon, day):
        self.calls += 1
        return self.series


class ExplodingFetcher:
    def fetch_hourly(self, lat, lon, day):
        raise AssertionError("network must not be hit on a cache hit")


def test_same_cell_and_day_fetches_only_once(tmp_path):
    fetcher = StubFetcher(hourly_series())
    svc = WeatherService(fetcher, cache_dir=tmp_path)

    svc.conditions_at(48.0, 11.0, 1800.0)  # 00:30
    svc.conditions_at(48.001, 11.001, 5400.0)  # 01:30, same 0.1° cell, same day

    assert fetcher.calls == 1


def test_disk_cache_survives_a_new_service(tmp_path):
    WeatherService(StubFetcher(hourly_series()), cache_dir=tmp_path).conditions_at(48.0, 11.0, 1800.0)

    # A brand-new service (cold memory) must serve from disk without fetching.
    svc = WeatherService(ExplodingFetcher(), cache_dir=tmp_path)
    cond = svc.conditions_at(48.0, 11.0, 1800.0)

    assert cond.temperature_c == pytest.approx(0.5)  # interpolated between hour 0 and 1
