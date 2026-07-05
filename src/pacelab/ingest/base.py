"""The ingestion seam: every source is an adapter that yields the canonical Track.

FIT, GPX, and any API source implement the same ``SourceAdapter`` protocol, so the rest
of the pipeline is oblivious to where a run came from (NFR-8).
"""

from pathlib import Path
from typing import Protocol

from pacelab.core import Track


class SourceAdapter(Protocol):
    def parse(self, path: Path) -> Track:
        """Read an activity file and return its canonical trackpoint stream."""
        ...
