"""The two fetchers retry their own requests (ADR-0020).

`test_weather_retry.py` owns the policy; this owns the wiring — that the retry sits around
one HTTP call and not around `fetch_hourly`, and that the timeout budget shrank so three
attempts spend what one used to.
"""

import io
import json
import urllib.error
import urllib.parse

import pytest

from pacelab.weather.forecast import ForecastFetcher
from pacelab.weather.open_meteo import OpenMeteoFetcher

_HOUR = {
    "time": ["2026-07-07T12:00"],
    "temperature_2m": [20.0],
    "relative_humidity_2m": [50.0],
    "wind_speed_10m": [3.0],
    "wind_direction_10m": [180.0],
    "cloud_cover": [10.0],
    "surface_pressure": [1013.0],
    "shortwave_radiation": [700.0],
}
_STALL = urllib.error.URLError("handshake timed out")


def _payload():
    return io.BytesIO(json.dumps({"hourly": _HOUR}).encode())


class FakeUrlopen:
    """Stands in for `urllib.request.urlopen`, scripted per model.

    Records every URL it is handed, so a test can tell a retried call from a repeated one.
    """

    def __init__(self, outcomes):
        self.outcomes = outcomes  # model name (or None) -> outcomes, consumed in order
        self.urls = []
        self.timeouts = []

    def __call__(self, url, timeout=None, context=None):
        self.urls.append(url)
        self.timeouts.append(timeout)
        model = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("models", [None])[0]
        outcome = self.outcomes[model].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _install(monkeypatch, outcomes):
    """Script the transport and return the fake, plus a sleep that must never really wait."""
    fake = FakeUrlopen(outcomes)
    monkeypatch.setattr("pacelab.weather.retry.urllib.request.urlopen", fake)
    return fake


def _no_sleep(seconds):
    assert seconds == 1.0  # the fixed pause, never actually waited on


def test_the_archive_fetcher_retries_a_stalled_request(monkeypatch):
    fake = _install(monkeypatch, {"era5_land": [_STALL, _payload()], "era5": [_payload()]})

    series = OpenMeteoFetcher(sleep=_no_sleep).fetch_hourly(52.5, 13.4, "2026-07-07")

    assert len(series) == 1
    assert len(fake.urls) == 3


def test_a_stalled_second_model_does_not_repay_the_first(monkeypatch):
    # The reason the retry wraps one request and not `fetch_hourly`: era5_land succeeded
    # once and must stay bought.
    fake = _install(monkeypatch, {"era5_land": [_payload()], "era5": [_STALL, _payload()]})

    OpenMeteoFetcher(sleep=_no_sleep).fetch_hourly(52.5, 13.4, "2026-07-07")

    assert len([u for u in fake.urls if "era5_land" in u]) == 1


def test_the_archive_fetcher_does_not_retry_an_http_error(monkeypatch):
    error = urllib.error.HTTPError("http://x", 404, "Not Found", {}, None)
    fake = _install(monkeypatch, {"era5_land": [error], "era5": []})

    with pytest.raises(urllib.error.HTTPError):
        OpenMeteoFetcher(sleep=_no_sleep).fetch_hourly(52.5, 13.4, "2026-07-07")

    assert len(fake.urls) == 1


def test_the_archive_fetcher_propagates_an_exhausted_retry(monkeypatch):
    fake = _install(monkeypatch, {"era5_land": [_STALL] * 3, "era5": []})

    with pytest.raises(urllib.error.URLError):
        OpenMeteoFetcher(sleep=_no_sleep).fetch_hourly(52.5, 13.4, "2026-07-07")

    assert len(fake.urls) == 3


def test_the_forecast_fetcher_retries_a_stalled_request(monkeypatch):
    fake = _install(monkeypatch, {None: [_STALL, _payload()]})

    series = ForecastFetcher(sleep=_no_sleep).fetch_hourly(52.5, 13.4, "2026-07-07")

    assert len(series) == 1
    assert len(fake.urls) == 2


def test_the_forecast_fetcher_propagates_an_exhausted_retry(monkeypatch):
    fake = _install(monkeypatch, {None: [_STALL] * 3})

    with pytest.raises(urllib.error.URLError):
        ForecastFetcher(sleep=_no_sleep).fetch_hourly(52.5, 13.4, "2026-07-07")

    assert len(fake.urls) == 3


@pytest.mark.parametrize("fetcher,outcomes", [
    (OpenMeteoFetcher, {"era5_land": [_STALL, _payload()], "era5": [_payload()]}),
    (ForecastFetcher, {None: [_STALL, _payload()]}),
])
def test_every_attempt_uses_the_shortened_timeout(monkeypatch, fetcher, outcomes):
    # 10 s per attempt, retried attempts included — that is what keeps three attempts inside
    # the 30 s of timeout a single 30 s attempt used to cost.
    fake = _install(monkeypatch, outcomes)

    fetcher(sleep=_no_sleep).fetch_hourly(52.5, 13.4, "2026-07-07")

    assert len(fake.timeouts) > 1
    assert set(fake.timeouts) == {10.0}
