"""FIT source adapter (FR-1.1) — the primary per-point input (ADR-0003).

Reads ``record`` messages from a Garmin/COROS FIT file into the canonical Track. FIT stores
latitude/longitude as *semicircles* (int32), converted to degrees here.

NOTE: not yet exercised against a real FIT export — field names below follow the FIT
Profile ``record`` message, but confirm against an actual COROS/Strava export before relying
on it (that's the deferred milestone-3 test).
"""

from pathlib import Path

import fitdecode

from pacelab.core import Track, Trackpoint

_SEMICIRCLE_TO_DEG = 180.0 / (2**31)


class FitAdapter:
    def parse(self, path: Path) -> Track:
        points: list[Trackpoint] = []
        with fitdecode.FitReader(str(path)) as reader:
            for frame in reader:
                if not isinstance(frame, fitdecode.FitDataMessage) or frame.name != "record":
                    continue
                lat = _get(frame, "position_lat")
                lon = _get(frame, "position_long")
                if lat is None or lon is None:
                    continue  # skip records without a GPS fix
                ts = _get(frame, "timestamp")
                ele = _get(frame, "enhanced_altitude")
                if ele is None:
                    ele = _get(frame, "altitude")
                points.append(
                    Trackpoint(
                        t=ts.timestamp() if ts is not None else 0.0,
                        lat=lat * _SEMICIRCLE_TO_DEG,
                        lon=lon * _SEMICIRCLE_TO_DEG,
                        ele=float(ele) if ele is not None else 0.0,
                        hr=_get(frame, "heart_rate"),
                    )
                )
        return Track(points=points)


def _get(frame, field):
    return frame.get_value(field, fallback=None) if frame.has_field(field) else None
