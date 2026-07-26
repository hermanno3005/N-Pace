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


def test_provisional_service_never_writes_to_disk(tmp_path):
    # Forecast-tier weather is a preview — persisting it would freeze non-final data
    # under the (cell, day) key and block the eventual ERA5 value (ADR-0012).
    fetcher = StubFetcher(hourly_series())
    svc = WeatherService(fetcher, cache_dir=tmp_path, disk_cache=False)

    svc.conditions_at(48.0, 11.0, 1800.0)
    svc.conditions_at(48.0, 11.0, 5400.0)  # same cell-day: memory-cached, one fetch

    assert fetcher.calls == 1
    assert list(tmp_path.iterdir()) == []  # nothing persisted


class EmptyThenFullFetcher:
    """ERA5's publication lag: a too-recent day is empty now, populated days later."""

    def __init__(self, series):
        self.series = series
        self.calls = 0

    def fetch_hourly(self, lat, lon, day):
        self.calls += 1
        return [] if self.calls == 1 else self.series


def test_missing_weather_raises_and_is_never_cached(tmp_path):
    # An empty day (ERA5 lag) must raise a clear error AND leave no cache entry —
    # a cached empty day would block that date forever once ERA5 catches up.
    from pacelab.weather.service import WeatherUnavailable

    fetcher = EmptyThenFullFetcher(hourly_series())
    svc = WeatherService(fetcher, cache_dir=tmp_path)

    with pytest.raises(WeatherUnavailable, match="1970-01-01"):
        svc.conditions_at(48.0, 11.0, 1800.0)
    assert list(tmp_path.iterdir()) == []  # nothing poisoned on disk

    # Once the archive has the day, the same service serves it (refetches).
    assert svc.conditions_at(48.0, 11.0, 1800.0).temperature_c == pytest.approx(0.5)
    assert fetcher.calls == 2


def test_disk_cache_survives_a_new_service(tmp_path):
    WeatherService(StubFetcher(hourly_series()), cache_dir=tmp_path).conditions_at(48.0, 11.0, 1800.0)

    # A brand-new service (cold memory) must serve from disk without fetching.
    svc = WeatherService(ExplodingFetcher(), cache_dir=tmp_path)
    cond = svc.conditions_at(48.0, 11.0, 1800.0)

    assert cond.temperature_c == pytest.approx(0.5)  # interpolated between hour 0 and 1


def test_stale_cache_format_is_refetched(tmp_path):
    # Cache files written before the solar field existed (7 values per row) must be
    # refreshed, not served — they silently starve WBGT into the Heat Index fallback.
    import json

    sunny = [(h * 3600.0, Conditions(float(h), 50.0, 2.0, 180.0, 0.0, 1013.0, 100.0))
             for h in range(24)]
    fetcher = StubFetcher(sunny)
    svc = WeatherService(fetcher, cache_dir=tmp_path)
    stale = [[h * 3600.0, float(h), 50.0, 2.0, 180.0, 0.0, 1013.0] for h in range(24)]
    (tmp_path / "48.0_11.0_1970-01-01.json").write_text(json.dumps(stale))

    cond = svc.conditions_at(48.0, 11.0, 1800.0)

    assert fetcher.calls == 1  # refetched despite the cache file
    assert cond.solar_radiation_wm2 is not None
