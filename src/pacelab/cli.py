"""PaceLab CLI: analyse local files or sync from intervals.icu (FR-9/10, ADR-0008).

    pacelab analyze run.fit
    pacelab analyze activities/ --segments
    pacelab sync --from 2024-01-01

Results go to SQLite; re-runs are idempotent (skipped unless the model version changed or
--reprocess is given). `sync` needs INTERVALS_API_KEY in the environment.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from pacelab.account import Account
from pacelab.app import analyze_file
from pacelab.config import Config
from pacelab.providers.http import UrllibHttp
from pacelab.providers.intervals import IntervalsProvider, RateLimited
from pacelab.publish.publisher import publish_range
from pacelab.report import format_segments, format_summary, to_dict
from pacelab.store import ResultStore
from pacelab.sync import sync
from pacelab.weather.forecast import ForecastFetcher
from pacelab.weather.open_meteo import OpenMeteoFetcher
from pacelab.weather.service import WeatherService

_SUFFIXES = {".fit", ".gpx"}


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--db", type=Path, default=Path("pacelab.db"), help="results database")
    p.add_argument("--cache-dir", type=Path, default=Path(".cache"), help="cache root (weather + activities)")
    p.add_argument("--json-dir", type=Path, default=None, help="also export per-activity JSON here")
    p.add_argument("--segments", action="store_true", help="print the per-segment table")
    p.add_argument("--apply-wind", action="store_true", help="include wind in the applied NP")
    p.add_argument("--reprocess", action="store_true", help="recompute even if already current")


def _weather(cache_dir: Path) -> WeatherService:
    return WeatherService(OpenMeteoFetcher(), cache_dir=cache_dir / "weather")


def _emit(activity_id, result, config, args) -> None:
    if args.json_dir:
        args.json_dir.mkdir(parents=True, exist_ok=True)
        (args.json_dir / f"{activity_id}.json").write_text(
            json.dumps(to_dict(activity_id, result, config.model_version), indent=2)
        )
    print(format_summary(activity_id, result))
    if args.segments:
        print(format_segments(result))
    print()


def _run_analyze(args) -> int:
    path = args.path
    files = sorted(p for p in path.iterdir() if p.suffix.lower() in _SUFFIXES) if path.is_dir() else [path]
    if not files:
        print(f"No FIT/GPX activities found at {path}", file=sys.stderr)
        return 1
    config = Config(apply_wind=args.apply_wind)
    store = ResultStore(args.db)
    service = _weather(args.cache_dir)
    for f in files:
        activity_id = f.stem
        if not args.reprocess and store.is_current(activity_id, config.model_version):
            print(f"skip  {activity_id} (already current)")
            continue
        result = analyze_file(f, config, service)
        store.save(activity_id, result, config.model_version)
        _emit(activity_id, result, config, args)
    return 0


def _run_sync(args) -> int:
    config = Config(apply_wind=args.apply_wind)
    account = Account.from_env()
    account_id = account.storage_id  # same key for store rows and the FIT cache (ADR-0009)
    provider = IntervalsProvider(account, UrllibHttp(), cache_dir=args.cache_dir / "activities")
    store = ResultStore(args.db)
    service = _weather(args.cache_dir)

    # Forecast tier for runs inside ERA5's lag — previews are never disk-cached (ADR-0012).
    provisional_service = WeatherService(ForecastFetcher(), cache_dir=args.cache_dir / "weather",
                                         disk_cache=False)

    try:
        outcomes = sync(provider, service, store, config, args.oldest, args.newest,
                        account_id=account_id, reprocess=args.reprocess,
                        provisional_service=provisional_service)
    except RateLimited as e:
        print(f"{e} — already-synced activities are saved; rerun to continue.", file=sys.stderr)
        return 1

    analysed = {"ok", "provisional", "finalized"}
    for activity_id, status in outcomes:
        if status in analysed:
            if status != "ok":
                print(f"[{status}]")
            _emit(activity_id, store.load(activity_id, account_id=account_id), config, args)
        else:
            print(f"{status:8} {activity_id}")
    done = sum(1 for _, s in outcomes if s in analysed)
    print(f"\nsynced {done} / {len(outcomes)} listed")
    return 0


def _run_publish(args) -> int:
    config = Config()
    account = Account.from_env()
    provider = IntervalsProvider(account, UrllibHttp(), cache_dir=args.cache_dir / "activities")
    store = ResultStore(args.db)

    try:
        outcomes = publish_range(provider, store, config, args.oldest, args.newest,
                                 account_id=account.storage_id)
    except RateLimited as e:
        print(f"{e} — published annotations are saved; rerun to continue.", file=sys.stderr)
        return 1

    for activity_id, status in outcomes:
        print(f"{status:14} {activity_id}")
    published = sum(1 for _, s in outcomes if s == "published")
    print(f"\npublished {published} / {len(outcomes)} listed")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pacelab", description="Environment-adjusted pace engine")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze", help="analyse a local FIT/GPX file or directory")
    analyze.add_argument("path", type=Path)
    _add_common(analyze)

    sync_p = sub.add_parser("sync", help="fetch new activities from intervals.icu and analyse them")
    sync_p.add_argument("--from", dest="oldest", required=True, help="oldest date, YYYY-MM-DD")
    sync_p.add_argument("--to", dest="newest", default=date.today().isoformat(), help="newest date")
    _add_common(sync_p)

    publish_p = sub.add_parser(
        "publish", help="write annotations for already-analysed activities (backfill/re-publish)"
    )
    publish_p.add_argument("--from", dest="oldest", required=True, help="oldest date, YYYY-MM-DD")
    publish_p.add_argument("--to", dest="newest", default=date.today().isoformat(), help="newest date")
    _add_common(publish_p)

    args = parser.parse_args(argv)
    if args.command == "sync":
        return _run_sync(args)
    if args.command == "publish":
        return _run_publish(args)
    return _run_analyze(args)


if __name__ == "__main__":
    raise SystemExit(main())
