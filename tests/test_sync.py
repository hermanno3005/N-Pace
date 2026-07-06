import math

from pacelab.analyze import ActivityResult
from pacelab.config import Config
from pacelab.providers.intervals import ActivityRef
from pacelab.store import ResultStore
from pacelab.sync import sync
from pacelab.weather.conditions import Conditions


def _write_gpx(path):
    lat = 48.0
    lon_step = 10 / (111_320 * math.cos(math.radians(lat)))
    body = "".join(
        f'<trkpt lat="{lat:.6f}" lon="{i * lon_step:.6f}"><ele>{100 + i * 0.3:.1f}</ele>'
        f'<time>2023-07-04T12:{(i * 3) // 60:02d}:{(i * 3) % 60:02d}Z</time></trkpt>\n'
        for i in range(60)
    )
    path.write_text(
        '<?xml version="1.0"?>\n<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">'
        f'<trk><trkseg>\n{body}</trkseg></trk></gpx>\n'
    )


class StubProvider:
    def __init__(self, refs, gpx_path):
        self._refs = refs
        self._gpx = gpx_path
        self.downloaded = []

    def list_activities(self, oldest, newest):
        return self._refs

    def download(self, activity_id):
        self.downloaded.append(activity_id)
        return self._gpx


class StubService:
    def conditions_at(self, lat, lon, t):
        return Conditions(20.0, 50.0, 0.0, 0.0, 0.0, 1013.0)


def _write_trackless_gpx(path):
    # A valid GPX with no trackpoints — e.g. a treadmill/strength activity (FR-1.4).
    path.write_text('<?xml version="1.0"?>\n<gpx version="1.1" '
                    'xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
                    '</trkseg></trk></gpx>\n')


def test_sync_skips_activities_with_no_gps_track(tmp_path):
    empty = tmp_path / "empty.gpx"
    _write_trackless_gpx(empty)
    store = ResultStore(tmp_path / "db")
    provider = StubProvider([ActivityRef("i900", "2024-07-01", "WeightTraining", "Gym")], empty)

    outcomes = dict(sync(provider, StubService(), store, Config(), "2024-01-01", "2024-12-31",
                         account_id="acct"))

    assert outcomes["i900"] == "no-track"
    assert store.load("i900", account_id="acct") is None  # not stored


def test_sync_skips_current_downloads_new_and_stores(tmp_path):
    gpx = tmp_path / "a.gpx"
    _write_gpx(gpx)
    store = ResultStore(tmp_path / "db")
    # i100 is already current; i200 is new.
    store.save("i100", ActivityResult(0, 0, 0, 0, 0, 0, []), "0.1.0", account_id="acct")
    provider = StubProvider(
        [ActivityRef("i100", "2024-07-01", "Run", "A"), ActivityRef("i200", "2024-07-02", "Run", "B")],
        gpx,
    )

    outcomes = dict(sync(provider, StubService(), store, Config(), "2024-01-01", "2024-12-31",
                         account_id="acct"))

    assert provider.downloaded == ["i200"]  # current one never downloaded (rate-limit friendly)
    assert outcomes["i100"] == "skip"
    assert outcomes["i200"] == "ok"
    assert store.is_current("i200", "0.1.0", account_id="acct")
