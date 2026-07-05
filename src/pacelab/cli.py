"""PaceLab CLI: analyse one activity or a directory of them (FR-9, FR-10).

    pacelab run.fit
    pacelab activities/ --json-dir out --segments

Results are stored in SQLite and re-runs are idempotent (skipped unless the model version
changed or --reprocess is given).
"""

import argparse
import json
import sys
from pathlib import Path

from pacelab.app import analyze_file
from pacelab.config import Config
from pacelab.report import format_segments, format_summary, to_dict
from pacelab.store import ResultStore
from pacelab.weather.open_meteo import OpenMeteoFetcher
from pacelab.weather.service import WeatherService

_SUFFIXES = {".fit", ".gpx"}


def _activities(path: Path) -> list[Path]:
    if path.is_dir():
        return sorted(p for p in path.iterdir() if p.suffix.lower() in _SUFFIXES)
    return [path]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pacelab", description="Environment-adjusted pace engine")
    parser.add_argument("path", type=Path, help="a FIT/GPX file or a directory of them")
    parser.add_argument("--db", type=Path, default=Path("pacelab.db"), help="results database")
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/weather"), help="weather cache")
    parser.add_argument("--json-dir", type=Path, default=None, help="also export per-activity JSON here")
    parser.add_argument("--segments", action="store_true", help="print the per-segment table")
    parser.add_argument("--apply-wind", action="store_true", help="include wind in the applied NP")
    parser.add_argument("--reprocess", action="store_true", help="recompute even if already current")
    args = parser.parse_args(argv)

    files = _activities(args.path)
    if not files:
        print(f"No FIT/GPX activities found at {args.path}", file=sys.stderr)
        return 1

    config = Config(apply_wind=args.apply_wind)
    store = ResultStore(args.db)
    service = WeatherService(OpenMeteoFetcher(), cache_dir=args.cache_dir)

    for path in files:
        activity_id = path.stem
        if not args.reprocess and store.is_current(activity_id, config.model_version):
            print(f"skip  {activity_id} (already current)")
            continue
        result = analyze_file(path, config, service)
        store.save(activity_id, result, config.model_version)
        if args.json_dir:
            args.json_dir.mkdir(parents=True, exist_ok=True)
            (args.json_dir / f"{activity_id}.json").write_text(
                json.dumps(to_dict(activity_id, result, config.model_version), indent=2)
            )
        print(format_summary(activity_id, result))
        if args.segments:
            print(format_segments(result))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
