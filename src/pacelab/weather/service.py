"""Cached weather lookup keyed by (grid-cell, day) — FR-3.3, NFR-3, ADR-0004.

A run's segments are enriched by ``conditions_at(lat, lon, t)``. Each (0.1° cell, UTC day)
is fetched at most once, then served from an in-memory dict and a JSON disk cache, so
re-runs are network-free and deterministic. Within a cell-day, conditions are interpolated
in time (ADR-0004: nearest-cell in space, linear in time).
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from pacelab.weather.conditions import Conditions
from pacelab.weather.interpolate import interpolate_conditions

# Grid resolution for the cache key: 0.1° ≈ 11 km, on the order of ERA5-Land's ~9 km grid.
CELL_DEGREES = 0.1

_HourlySeries = list[tuple[float, Conditions]]


class WeatherUnavailable(RuntimeError):
    """No weather exists for this day (yet) — typically ERA5's ~week publication lag."""


class Fetcher(Protocol):
    def fetch_hourly(self, lat: float, lon: float, day: str) -> _HourlySeries:
        """Return the hourly series for a cell on a given UTC day (the network boundary)."""
        ...


def _cell(lat: float, lon: float) -> tuple[float, float]:
    return (round(lat / CELL_DEGREES) * CELL_DEGREES, round(lon / CELL_DEGREES) * CELL_DEGREES)


def _day(t: float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).date().isoformat()


class WeatherService:
    def __init__(self, fetcher: Fetcher, cache_dir: Path, disk_cache: bool = True):
        # disk_cache=False is the provisional (forecast-tier) mode: previews must never
        # be persisted, or they'd block the final ERA5 value for that cell-day (ADR-0012).
        self._fetcher = fetcher
        self._disk_cache = disk_cache
        self._dir = Path(cache_dir)
        if disk_cache:
            self._dir.mkdir(parents=True, exist_ok=True)
        self._memory: dict[str, _HourlySeries] = {}

    def conditions_at(self, lat: float, lon: float, t: float) -> Conditions:
        return interpolate_conditions(self._hourly(lat, lon, t), t)

    def _hourly(self, lat: float, lon: float, t: float) -> _HourlySeries:
        cell_lat, cell_lon = _cell(lat, lon)
        day = _day(t)
        key = f"{cell_lat:.1f}_{cell_lon:.1f}_{day}"
        if key in self._memory:
            return self._memory[key]

        path = self._dir / f"{key}.json"
        if self._disk_cache and path.exists():
            series = _decode(json.loads(path.read_text()))
        else:
            series = self._fetcher.fetch_hourly(cell_lat, cell_lon, day)
            if not series:
                # No data for this day. Cache NOTHING — a cached empty day would block
                # the date forever once the source catches up.
                raise WeatherUnavailable(
                    f"no weather for {day} yet (ERA5 lags ~a week) — retry in a few days"
                )
            if self._disk_cache:
                path.write_text(json.dumps(_encode(series)))
        self._memory[key] = series
        return series


def _encode(series: _HourlySeries) -> list:
    return [
        [t, c.temperature_c, c.humidity_pct, c.wind_speed_ms, c.wind_dir_deg,
         c.cloud_cover_pct, c.pressure_hpa]
        for t, c in series
    ]


def _decode(rows: list) -> _HourlySeries:
    return [(r[0], Conditions(r[1], r[2], r[3], r[4], r[5], r[6])) for r in rows]
