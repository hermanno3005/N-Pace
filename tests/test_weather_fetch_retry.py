"""The two fetchers retry their own requests (ADR-0020).

`test_weather_retry.py` covers the policy; this covers the wiring — that the retry sits
around one HTTP call and not around `fetch_hourly`, and that the timeout budget shrank so
three attempts cost what one used to.
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


def _payload():
    return io.BytesIO(json.dumps({"hourly": _HOUR}).encode())


class FakeUrlopen:
    """Stands in for `urllib.request.urlopen`, scripted per model.

    Records every URL it is handed, so a test can tell a retried call from a repeated one.
    """

    def __init__(self, outcomes):
        self.outcomes = outcomes  # model name (or None) -> list of outcomes, consumed in order
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


def _install(monkeypatch, module, fake):
    monkeypatch.setattr(f"pacelab.weather.{module}.urllib.request.urlopen", fake)
    # The fetchers take the retry's default sleep, so shorten the pause instead of
    # replacing it — no test may spend a real second.
    monkeypatch.setattr("pacelab.weather.retry._PAUSE_S", 0.0)


def test_the_archive_fetcher_retries_a_stalled_request(monkeypatch):
    fake = FakeUrlopen({
        "era5_land": [urllib.error.URLError("handshake timed out"), _payload()],
        "era5": [_payload()],
    })
    _install(monkeypatch, "open_meteo", fake)

    series = OpenMeteoFetcher().fetch_hourly(52.5, 13.4, "2026-07-07")

    assert len(series) == 1
    assert len(fake.urls) == 3


def test_a_stalled_second_model_does_not_repay_the_first(monkeypatch):
    # The reason the retry wraps `_request` and not `fetch_hourly`: era5_land succeeded once
    # and must stay bought.
    fake = FakeUrlopen({
        "era5_land": [_payload()],
        "era5": [urllib.error.URLError("handshake timed out"), _payload()],
    })
    _install(monkeypatch, "open_meteo", fake)

    OpenMeteoFetcher().fetch_hourly(52.5, 13.4, "2026-07-07")

    land_calls = [u for u in fake.urls if "era5_land" in u]
    assert len(land_calls) == 1


def test_the_archive_fetcher_does_not_retry_an_http_error(monkeypatch):
    fake = FakeUrlopen({
        "era5_land": [urllib.error.HTTPError("http://x", 404, "Not Found", {}, None)],
        "era5": [],
    })
    _install(monkeypatch, "open_meteo", fake)

    with pytest.raises(urllib.error.HTTPError):
        OpenMeteoFetcher().fetch_hourly(52.5, 13.4, "2026-07-07")

    assert len(fake.urls) == 1


def test_the_archive_fetcher_propagates_an_exhausted_retry(monkeypatch):
    fake = FakeUrlopen({
        "era5_land": [urllib.error.URLError("handshake timed out")] * 3,
        "era5": [],
    })
    _install(monkeypatch, "open_meteo", fake)

    with pytest.raises(urllib.error.URLError):
        OpenMeteoFetcher().fetch_hourly(52.5, 13.4, "2026-07-07")

    assert len(fake.urls) == 3


def test_the_forecast_fetcher_retries_a_stalled_request(monkeypatch):
    fake = FakeUrlopen({None: [urllib.error.URLError("handshake timed out"), _payload()]})
    _install(monkeypatch, "forecast", fake)

    series = ForecastFetcher().fetch_hourly(52.5, 13.4, "2026-07-07")

    assert len(series) == 1
    assert len(fake.urls) == 2


def test_the_forecast_fetcher_does_not_retry_an_http_error(monkeypatch):
    fake = FakeUrlopen({None: [urllib.error.HTTPError("http://x", 429, "Too Many", {}, None)]})
    _install(monkeypatch, "forecast", fake)

    with pytest.raises(urllib.error.HTTPError):
        ForecastFetcher().fetch_hourly(52.5, 13.4, "2026-07-07")

    assert len(fake.urls) == 1


@pytest.mark.parametrize("module,fetcher,outcomes", [
    ("open_meteo", OpenMeteoFetcher, {"era5_land": [_payload()], "era5": [_payload()]}),
    ("forecast", ForecastFetcher, {None: [_payload()]}),
])
def test_the_per_attempt_timeout_leaves_the_worst_case_unchanged(
    monkeypatch, module, fetcher, outcomes
):
    # 3 attempts x 10 s is the same 30 s the single attempt used to cost.
    fake = FakeUrlopen(outcomes)
    _install(monkeypatch, module, fake)

    fetcher().fetch_hourly(52.5, 13.4, "2026-07-07")

    assert set(fake.timeouts) == {10.0}
