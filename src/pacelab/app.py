"""Orchestration: a file on disk → an analysed ActivityResult.

Picks a source adapter by extension (FIT primary per ADR-0003, GPX fallback), preprocesses
into segments, enriches with weather, and analyses. The weather source is injected so the
pure path can be tested without a network.
"""

from pathlib import Path
from typing import Protocol

from pacelab.analyze import ActivityResult, analyze
from pacelab.config import Config
from pacelab.ingest.fit import FitAdapter
from pacelab.ingest.gpx import GpxAdapter
from pacelab.preprocess.pipeline import to_segments
from pacelab.weather.conditions import Conditions
from pacelab.weather.enrich import enrich


class ConditionsSource(Protocol):
    def conditions_at(self, lat: float, lon: float, t: float) -> Conditions:
        ...


def _adapter_for(path: Path):
    return FitAdapter() if path.suffix.lower() == ".fit" else GpxAdapter()


def analyze_file(path: Path, config: Config, source: ConditionsSource) -> ActivityResult:
    track = _adapter_for(path).parse(path)
    segments = to_segments(track, step_m=config.step_m)
    enriched = enrich(segments, source)
    return analyze(enriched, config)
