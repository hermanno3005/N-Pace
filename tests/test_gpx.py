from pacelab.ingest.gpx import GpxAdapter

GPX = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg>
    <trkpt lat="48.0000" lon="11.0000"><ele>100.0</ele><time>2026-07-04T12:00:00Z</time></trkpt>
    <trkpt lat="48.0010" lon="11.0000"><ele>101.0</ele><time>2026-07-04T12:00:10Z</time></trkpt>
    <trkpt lat="48.0020" lon="11.0000"><ele>103.0</ele><time>2026-07-04T12:00:20Z</time></trkpt>
  </trkseg></trk>
</gpx>
"""


def test_gpx_parses_into_canonical_trackpoints(tmp_path):
    path = tmp_path / "run.gpx"
    path.write_text(GPX)

    track = GpxAdapter().parse(path)

    assert [p.lat for p in track.points] == [48.0, 48.001, 48.002]
    assert [p.lon for p in track.points] == [11.0, 11.0, 11.0]
    assert [p.ele for p in track.points] == [100.0, 101.0, 103.0]
    # Timestamps become epoch seconds; spacing is preserved.
    assert track.points[1].t - track.points[0].t == 10.0
    assert track.points[2].t - track.points[1].t == 10.0
