"""GPX source adapter (FR-1.2) — the file fallback/alternative to FIT."""

from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree

from pacelab.core import Track, Trackpoint

_NS = {"gpx": "http://www.topografix.com/GPX/1/1"}


def _epoch(text: str) -> float:
    # GPX times are ISO 8601, typically UTC with a trailing 'Z'.
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


class GpxAdapter:
    def parse(self, path: Path) -> Track:
        root = ElementTree.parse(path).getroot()
        points = []
        for pt in root.iterfind(".//gpx:trkpt", _NS):
            ele = pt.find("gpx:ele", _NS)
            time = pt.find("gpx:time", _NS)
            points.append(
                Trackpoint(
                    t=_epoch(time.text) if time is not None else 0.0,
                    lat=float(pt.get("lat")),
                    lon=float(pt.get("lon")),
                    ele=float(ele.text) if ele is not None else 0.0,
                )
            )
        return Track(points=points)
