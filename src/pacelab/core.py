"""Canonical data model shared across ingest, preprocess, and the engine.

Every input source (FIT, GPX, an API) is an adapter that yields a ``Track`` — the ordered
stream of ``Trackpoint``s (CONTEXT: Trackpoint). Preprocessing turns a ``Track`` into
``Segment``s, the unit every impact model operates on (CONTEXT: Segment).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Trackpoint:
    """One sample of the canonical per-point record."""

    t: float  # seconds (unix epoch or activity-relative)
    lat: float  # degrees
    lon: float  # degrees
    ele: float  # metres
    hr: int | None = None


@dataclass(frozen=True)
class Track:
    """An ordered stream of trackpoints — one recorded activity's raw geometry."""

    points: list[Trackpoint]


@dataclass(frozen=True)
class Segment:
    """A ~fixed-distance span over which grade, bearing, and conditions are locally constant."""

    distance: float  # metres travelled
    grade: float  # rise/run as a fraction
    bearing: float  # initial course heading, degrees 0–360
    elapsed: float  # seconds
    lat: float  # midpoint latitude (for weather lookup)
    lon: float  # midpoint longitude
    start_time: float  # seconds, at the segment's start
    stopped: bool = False  # flagged when the runner was paused/stationary (FR-2.4)
