"""intervals.icu Provider — list activities and download original files (ADR-0008).

Knows the network and credentials, never file formats. Downloads land in the account-keyed
FIT cache, where the existing FitAdapter/GPX pipeline takes over.
"""

import base64
import gzip
import json
import warnings
from dataclasses import dataclass
from pathlib import Path

from pacelab.account import Account
from pacelab.providers.http import Http

_BASE = "https://intervals.icu/api/v1"
_GZIP_MAGIC = b"\x1f\x8b"


def _sniff_extension(raw: bytes) -> str:
    """Detect the activity file format from its bytes (original may be FIT/GPX/TCX)."""
    if len(raw) >= 12 and raw[8:12] == b".FIT":
        return "fit"
    head = raw[:512].lstrip()
    if b"<gpx" in head:
        return "gpx"
    if b"TrainingCenterDatabase" in head:
        return "tcx"
    return "fit"  # default: COROS originals are FIT


@dataclass(frozen=True)
class ActivityRef:
    """A remote activity's identity from a listing, before its file is downloaded."""

    id: str
    start_date: str | None
    type: str | None
    name: str | None


class IntervalsProvider:
    def __init__(self, account: Account, http: Http, cache_dir: Path):
        self._account = account
        self._http = http
        self._cache_dir = Path(cache_dir)
        token = base64.b64encode(f"API_KEY:{account.api_key}".encode()).decode()
        self._headers = {"Authorization": f"Basic {token}"}

    def list_activities(self, oldest: str, newest: str) -> list[ActivityRef]:
        url = f"{_BASE}/athlete/{self._account.athlete_id}/activities?oldest={oldest}&newest={newest}"
        resp = self._http.get(url, self._headers)
        activities = json.loads(resp.content)
        return [
            ActivityRef(
                id=a["id"],
                start_date=a.get("start_date_local"),
                type=a.get("type"),
                name=a.get("name"),
            )
            for a in activities
        ]

    def download(self, activity_id: str) -> Path | None:
        """Download an activity's original file into the account-keyed cache.

        Returns the cached path, or ``None`` (with a warning) when no original is available
        — e.g. Strava-synced activities, which intervals.icu can't serve (ADR-0008).
        """
        url = f"{_BASE}/activity/{activity_id}/file"
        resp = self._http.get(url, self._headers)
        if resp.status != 200:
            warnings.warn(
                f"no original file for {activity_id} (HTTP {resp.status}) — skipping",
                stacklevel=2,
            )
            return None
        raw = resp.content
        if raw[:2] == _GZIP_MAGIC:
            raw = gzip.decompress(raw)
        dest = self._cache_dir / self._account.athlete_id / f"{activity_id}.{_sniff_extension(raw)}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        return dest
