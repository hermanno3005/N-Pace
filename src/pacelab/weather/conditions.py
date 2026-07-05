"""Weather conditions at a point in space and time (FR-3.2)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Conditions:
    temperature_c: float
    humidity_pct: float
    wind_speed_ms: float
    wind_dir_deg: float  # meteorological: the direction the wind blows FROM, 0–360
    cloud_cover_pct: float
    pressure_hpa: float
