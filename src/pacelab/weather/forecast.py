"""Open-Meteo forecast-API fetcher — the provisional weather tier (ADR-0012).

Serves recent days (inside ERA5's ~week publication lag) from current forecast-model runs.
Deliberately NOT pinned to a model (ADR-0004's pin is about reproducible *final* data;
provisional previews are replaced by ERA5, so drift doesn't matter). Same hourly fields and
series shape as the archive fetcher; used behind a WeatherService with disk_cache=False so
previews are never persisted.
"""

import json
import ssl
import urllib.parse
import urllib.request

import certifi

from pacelab.weather.conditions import Conditions
from pacelab.weather.open_meteo import _HOURLY_FIELDS, _merge_series

_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


class ForecastFetcher:
    def __init__(self, timeout: float = 30.0):
        self._timeout = timeout
        self._ssl = ssl.create_default_context(cafile=certifi.where())

    def fetch_hourly(self, lat: float, lon: float, day: str) -> list[tuple[float, Conditions]]:
        query = urllib.parse.urlencode(
            {
                "latitude": lat,
                "longitude": lon,
                "start_date": day,
                "end_date": day,
                "hourly": ",".join(_HOURLY_FIELDS),
                "timezone": "UTC",
                "wind_speed_unit": "ms",
            }
        )
        url = f"{_FORECAST_URL}?{query}"
        with urllib.request.urlopen(url, timeout=self._timeout, context=self._ssl) as resp:
            data = json.load(resp)
        hourly = data.get("hourly", {})
        return _merge_series(hourly, {})  # single payload; merge degenerates to a parse
