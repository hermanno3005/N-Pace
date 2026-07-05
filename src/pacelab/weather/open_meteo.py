"""Open-Meteo historical weather client (IF-1, ADR-0004).

Pinned to fixed reanalysis models rather than the API's mutable ``best_match``, so history
stays reproducible (NFR-3). ERA5-Land (~9 km) only carries temperature and humidity; wind,
cloud, and pressure come from ERA5 (~25 km). Each field is taken from ERA5-Land when present
and ERA5 otherwise, giving finer near-surface temperature without losing the other fields.
Implements the ``Fetcher`` protocol; the WeatherService caches its output, so this runs at
most once per cell-day (two upstream requests, merged).

Stdlib-only (urllib). Not exercised against the live API in the test suite; validate against
a real fetch before relying on field names/units.
"""

import json
import ssl
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import certifi

from pacelab.weather.conditions import Conditions

_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
_HOURLY_FIELDS = [
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "wind_direction_10m",
    "cloud_cover",
    "surface_pressure",
]
# ERA5-Land is finer (~9 km) but only carries temperature/humidity; ERA5 (~25 km) has the
# rest. Each field prefers the first model that provides a non-null value.
_PREFERRED = "era5_land"
_BASE = "era5"


class OpenMeteoFetcher:
    def __init__(self, timeout: float = 30.0):
        self._timeout = timeout
        # Explicit CA bundle so HTTPS works without relying on system certs (macOS).
        self._ssl = ssl.create_default_context(cafile=certifi.where())

    def fetch_hourly(self, lat: float, lon: float, day: str) -> list[tuple[float, Conditions]]:
        land = self._request(lat, lon, day, _PREFERRED)["hourly"]
        base = self._request(lat, lon, day, _BASE)["hourly"]
        return _merge_series(land, base)

    def _request(self, lat: float, lon: float, day: str, model: str) -> dict:
        query = urllib.parse.urlencode(
            {
                "latitude": lat,
                "longitude": lon,
                "start_date": day,
                "end_date": day,
                "hourly": ",".join(_HOURLY_FIELDS),
                "models": model,
                "timezone": "UTC",
                "wind_speed_unit": "ms",
            }
        )
        url = f"{_ARCHIVE_URL}?{query}"
        with urllib.request.urlopen(url, timeout=self._timeout, context=self._ssl) as resp:
            return json.load(resp)


def _epoch(iso: str) -> float:
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp()


def _at(hourly: dict, field: str, i: int):
    values = hourly.get(field) or []
    return values[i] if i < len(values) else None


def _merge_series(land: dict, base: dict) -> list[tuple[float, Conditions]]:
    """Per-field, per-hour merge: ERA5-Land where present, else ERA5."""
    times = land.get("time") or base.get("time") or []
    series = []
    for i, iso in enumerate(times):
        row = []
        for field in _HOURLY_FIELDS:
            value = _at(land, field, i)
            if value is None:
                value = _at(base, field, i)
            row.append(value)
        if any(v is None for v in row):
            continue  # drop only if a field is missing from both models
        series.append((_epoch(iso), Conditions(*row)))
    return series
