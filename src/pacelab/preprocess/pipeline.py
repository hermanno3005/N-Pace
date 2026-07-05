"""Preprocess a raw Track into Segments: smooth elevation, then segment (FR-2)."""

from dataclasses import replace

from pacelab.core import Segment, Track
from pacelab.preprocess.segment import segment_track
from pacelab.preprocess.smoothing import smooth_elevation


def to_segments(track: Track, step_m: float = 100.0) -> list[Segment]:
    """Smooth the track's elevation (FR-2.2) and resample into segments (FR-2.3)."""
    smoothed = smooth_elevation([p.ele for p in track.points])
    clean = Track([replace(p, ele=e) for p, e in zip(track.points, smoothed)])
    return segment_track(clean, step_m=step_m)
