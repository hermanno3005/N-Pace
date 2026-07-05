import math

from pacelab.app import analyze_file
from pacelab.config import Config
from pacelab.weather.conditions import Conditions


class StubService:
    """A fixed-weather source so the end-to-end path needs no network."""

    def conditions_at(self, lat, lon, t):
        return Conditions(20.0, 50.0, 0.0, 0.0, 0.0, 1013.0)


def _write_gpx(path):
    lat = 48.0
    step_m = 10.0  # 10 m every 3 s ≈ 3.3 m/s, a realistic running pace
    lon_step = step_m / (111_320 * math.cos(math.radians(lat)))
    body = ""
    for i in range(60):  # ~590 m, gentle climb
        sec = i * 3
        iso = f"2023-07-04T12:{sec // 60:02d}:{sec % 60:02d}Z"
        body += (f'<trkpt lat="{lat:.6f}" lon="{i * lon_step:.6f}">'
                 f'<ele>{100 + i * 0.3:.1f}</ele><time>{iso}</time></trkpt>\n')
    path.write_text(
        '<?xml version="1.0"?>\n<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">'
        f'<trk><trkseg>\n{body}</trkseg></trk></gpx>\n'
    )


def test_analyze_file_runs_gpx_end_to_end(tmp_path):
    path = tmp_path / "run.gpx"
    _write_gpx(path)

    result = analyze_file(path, Config(), StubService())

    assert result.distance_m > 400
    assert len(result.segments) >= 1
    assert result.cost_heat > 0  # 20 °C is above the 10 °C reference
