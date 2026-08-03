"""PaceLab CLI: analyse local files or sync from intervals.icu (FR-9/10, ADR-0008).

    pacelab analyze run.fit
    pacelab analyze activities/ --segments
    pacelab sync --from 2024-01-01
    pacelab recompute [--force]
    pacelab snapshot
    pacelab health

Results go to SQLite; re-runs are idempotent (skipped unless the model version changed or
--reprocess is given). `sync` needs INTERVALS_API_KEY in the environment.

Two output channels, deliberately (ADR-0017). Report commands — `analyze`, `calibrate`,
`trend`, `health` — `print()` the data a human asked for. `watch` is a daemon nobody is
watching live, so everything it says goes through `logging` with a timestamp on it.
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import date
from functools import partial
from pathlib import Path

from pacelab.account import Account
from pacelab.app import analyze_file
from pacelab.config import Config
from pacelab.health import format_health, is_healthy
from pacelab.providers.http import UrllibHttp
from pacelab.providers.intervals import IntervalsProvider, RateLimited
from pacelab.publish.publisher import publish_range
from pacelab.recompute import recompute
from pacelab.report import format_line, format_segments, format_summary, format_trend, to_dict
from pacelab.snapshot import KEEP, SnapshotError, write_snapshot
from pacelab.store import ResultStore
from pacelab.sync import sync
from pacelab.weather.forecast import ForecastFetcher
from pacelab.weather.open_meteo import OpenMeteoFetcher
from pacelab.weather.service import WeatherService

_SUFFIXES = {".fit", ".gpx"}

log = logging.getLogger(__name__)


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--db", type=Path, default=Path("pacelab.db"), help="results database")
    p.add_argument("--cache-dir", type=Path, default=Path(".cache"), help="cache root (weather + activities)")
    p.add_argument("--json-dir", type=Path, default=None, help="also export per-activity JSON here")
    p.add_argument("--segments", action="store_true", help="print the per-segment table")
    p.add_argument("--apply-wind", action="store_true", help="include wind in the applied NP")
    p.add_argument("--reprocess", action="store_true", help="recompute even if already current")


def _add_snapshots_dir(p: argparse.ArgumentParser) -> None:
    """Only the three commands that can write a snapshot take this (ADR-0018)."""
    p.add_argument("--snapshots-dir", type=Path, default=Path("snapshots"),
                   help="where corpus snapshots are written")


def _snapshot(args, keep: int = KEEP, say=None) -> Path:
    """Write one verified snapshot and say where it landed. Raises on failure."""
    archive = write_snapshot(args.db, args.cache_dir / "weather", args.snapshots_dir,
                             keep=keep)
    (say or _print)(f"snapshot {archive} ({archive.stat().st_size / 1024:.0f} KB)")
    return archive


def _print(message: str) -> None:
    print(message, flush=True)


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


class _SyncContext:
    """Everything a sync pass needs, built once (weather memory-caches stay warm).

    ``logged`` picks the output channel: `watch` sends every line through `logging` (one
    per activity, not `_emit`'s block), a hand-run `sync`/`recompute` prints its report.
    """

    def __init__(self, args, logged: bool = False):
        self.args = args
        self.logged = logged
        self.config = Config(apply_wind=args.apply_wind)
        account = Account.from_env()
        self.account_id = account.storage_id  # one key for store rows and FIT cache (ADR-0009)
        self.provider = IntervalsProvider(account, UrllibHttp(),
                                          cache_dir=args.cache_dir / "activities")
        self.store = ResultStore(args.db)
        self.service = _weather(args.cache_dir)
        # Forecast tier for runs inside ERA5's lag — never disk-cached (ADR-0012).
        self.provisional = WeatherService(ForecastFetcher(), cache_dir=args.cache_dir / "weather",
                                          disk_cache=False)

    def say(self, message: str) -> None:
        """One line out, on whichever channel this run owns."""
        if self.logged:
            log.info(message)
        else:
            print(message, flush=True)

    def end_block(self) -> None:
        """A blank line separates printed report blocks; a log has timestamps instead."""
        if not self.logged:
            print()

    def run(self, oldest: str, newest: str):
        outcomes = sync(self.provider, self.service, self.store, self.config, oldest, newest,
                        account_id=self.account_id, reprocess=self.args.reprocess,
                        provisional_service=self.provisional)
        analysed = {"ok", "provisional", "finalized"}
        for activity_id, status in outcomes:
            result = (self.store.load(activity_id, account_id=self.account_id)
                      if status in analysed else None)
            if self.logged:
                line = f" — {format_line(result)}" if result else ""
                self.say(f"{status:8} {activity_id}{line}")
            elif result is not None:
                if status != "ok":
                    print(f"[{status}]")
                _emit(activity_id, result, self.config, self.args)
            else:
                print(f"{status:8} {activity_id}")
        done = sum(1 for _, s in outcomes if s in analysed)
        self.say(f"synced {done} / {len(outcomes)} listed")
        self.end_block()
        return outcomes

    def snapshot(self):
        """Snapshot the corpus (ADR-0018). Raises — the caller must not rewrite on failure."""
        return _snapshot(self.args, say=self.say)

    def reconcile(self, force: bool = False):
        """The reconciliation pass (ADR-0016) — silent when the corpus is settled."""
        outcomes = recompute(self.provider, self.service, self.store, self.config,
                             self.account_id, force=force, before_rewrite=self.snapshot)
        if not outcomes:
            return outcomes  # nothing drifted: the every-tick pass says nothing
        for activity_id, status in outcomes:
            self.say(f"{status:14} {activity_id}")
        done = sum(1 for _, s in outcomes if s in ("ok", "finalized"))
        self.say(f"recomputed {done} / {len(outcomes)} drifted")
        self.end_block()
        return outcomes


def _run_sync(args) -> int:
    try:
        _SyncContext(args).run(args.oldest, args.newest)
    except RateLimited as e:
        print(f"{e} — already-synced activities are saved; rerun to continue.", file=sys.stderr)
        return 1
    return 0


def _run_recompute(args) -> int:
    try:
        _SyncContext(args).reconcile(force=args.force)
    except RateLimited as e:
        print(f"{e} — recomputed activities are saved; rerun to continue.", file=sys.stderr)
        return 1
    except SnapshotError as e:
        # The corpus is untouched: the pass aborts before the first rewrite (ADR-0018).
        print(f"snapshot failed: {e} — nothing was recomputed.", file=sys.stderr)
        return 1
    return 0


def _run_snapshot(args) -> int:
    """Write one verified snapshot by hand — the mitigation for curation between bumps."""
    try:
        _snapshot(args, keep=args.keep)
    except SnapshotError as e:
        print(f"snapshot failed: {e}", file=sys.stderr)
        return 1
    print(f"pull it with: scp <pi>:{args.snapshots_dir}/latest.tar.gz .")
    return 0


def _run_watch(args) -> int:
    from pacelab.watch import watch

    context = _SyncContext(args, logged=True)
    log.info("pacelab watch: every %ss over the last %s days", args.interval,
             args.window_days)
    # The interval is bound into the writer rather than passed down through tick(): the
    # loop's cadence is the caller's fact, and the reader derives its staleness threshold
    # from it instead of assuming one (ADR-0017).
    watch(context.run, interval_s=args.interval, window_days=args.window_days,
          ticks=args.ticks, recompute_fn=None if args.no_recompute else context.reconcile,
          record_fn=partial(context.store.record_tick, interval_s=args.interval))
    return 0


def _run_health(args) -> int:
    """Is the watch loop alive and succeeding? The compose HEALTHCHECK's whole interface.

    Deliberately resolves no account: the heartbeat is unkeyed, so this reports broken
    credentials instead of failing on them (ADR-0017).
    """
    # Deliberately no ResultStore() on a database that is not there: opening one creates
    # it, and a probe that fires every five minutes must not manufacture the state it
    # claims to read — an empty db under /data would outlive the mistake that made it.
    beat = ResultStore(args.db).read_heartbeat() if args.db.exists() else None
    now = time.time()
    print(format_health(beat, now=now))
    return 0 if is_healthy(beat, now=now) else 1


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


def _run_trend(args) -> int:
    account_id = Account.from_env().storage_id
    points = ResultStore(args.db).np_trend(account_id=account_id)
    if not points:
        print("no analysed activities yet — run `pacelab sync` first", file=sys.stderr)
        return 1
    print(format_trend(points))
    return 0


def _fmt(value: float | None) -> str:
    return f"{value:.5f}" if value is not None else "n/a"


def _print_versions(counts: list[tuple[str | None, int]]) -> None:
    """State which model versions the fit is reading — loudly when there is more than one.

    A mixed corpus is harmless for a coefficient bump (calibration reads only raw
    columns) and invalidating for a pipeline bump, and nothing here can tell which it
    was. So calibrate still fits, but never silently (ADR-0016).
    """
    breakdown = ", ".join(f"{version or 'unversioned'} ({n})" for version, n in counts)
    if len(counts) > 1:
        print(f"!! MIXED MODEL VERSIONS: {breakdown}")
        print("   harmless for a coefficient re-tune, not for a pipeline change — "
              "run `pacelab recompute`\n")
    elif counts:
        print(f"model version {counts[0][0] or 'unversioned'}\n")
    else:
        print()


def _run_calibrate(args) -> int:
    from pacelab.calibrate import (
        fit_hr_conditioned_wbgt_a, fit_k_grade, fit_wbgt_a, is_steady,
    )
    # Compare fits against what is *configured*, not against the ported population
    # defaults: once calibration has moved a coefficient (wbgt_a, ADR-0006), an abstention
    # keeps the configured value, and that is the number worth printing.
    config = Config()
    account_id = Account.from_env().storage_id
    store = ResultStore(args.db)
    results = [r for r in (store.load(p.activity_id, account_id=account_id)
                           for p in store.np_trend(account_id=account_id)) if r]
    steady = sum(1 for r in results if is_steady(r))
    print(f"{len(results)} analysed runs · {steady} steady (calibration input)")
    _print_versions(store.version_counts(account_id=account_id))

    k = fit_k_grade(results)
    if k is None:
        print(f"k_grade : insufficient data — keeping configured {config.k_grade}")
    else:
        print(f"k_grade : {k.value:.3f}   (configured {config.k_grade}; "
              f"IQR {k.spread:.3f} over {k.n_runs} hilly steady runs)")

    k_grade = k.value if k else config.k_grade
    a = fit_wbgt_a(results, k_grade=k_grade)
    if a is None:
        print(f"wbgt_a  : insufficient data/spread — keeping configured {config.wbgt_a}")
    else:
        print(f"wbgt_a  : {a.value:.5f} (configured {config.wbgt_a}; R²={a.r2:.2f}, "
              f"residual ±{a.spread:.1f} s/km over {a.n_runs} steady runs)")

    # The HR-conditioned cut (ADR-0014): pace at equal HR, hot vs cool. Intent-proof, so
    # it is the one the findings doc treats as decisive.
    hr = fit_hr_conditioned_wbgt_a(results, k_grade=k_grade)
    if hr is None:
        print("wbgt_a  : (at equal HR) insufficient data/spread, or HR and heat too "
              "collinear to separate")
    else:
        print(f"wbgt_a  : {hr.value:.5f} at equal HR — {hr.n_runs} runs / "
              f"{hr.n_segments} segments")
        print(f"          run-mean refit {_fmt(hr.run_mean_value)}, "
              f"HR {hr.hr_coeff:+.2f} s/km per bpm, corr(HR, heat) {hr.hr_wbgt_corr:+.2f}")
        print(f"          R²={hr.r2:.2f} — optimistic, segments within a run correlate")
    print("\nreport only — nothing applied (FR-8.2). Review before tuning config.")
    return 0


def _configure_logging(level: str) -> None:
    """One stream, timestamped, UTC — the container carries no tz data (ADR-0017).

    stdout rather than stderr: `docker logs` merges them, and a daemon's operational log
    is its normal output, not an error channel. The level is set after `basicConfig`,
    which is a no-op once a handler exists — so a second `main()` in the same process
    (the tests) re-reads `--log-level` rather than silently keeping the first one.
    """
    logging.Formatter.converter = time.gmtime
    logging.basicConfig(level=level.upper(), stream=sys.stdout,
                        format="%(asctime)s %(levelname)-5s %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%SZ")
    logging.getLogger().setLevel(level.upper())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pacelab", description="Environment-adjusted pace engine")
    parser.add_argument("--log-level", default=os.environ.get("PACELAB_LOG_LEVEL", "INFO"),
                        help="DEBUG, INFO, WARNING… (default $PACELAB_LOG_LEVEL or INFO)")
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

    recompute_p = sub.add_parser(
        "recompute", help="re-analyse and republish every drifted activity (ADR-0016)"
    )
    recompute_p.add_argument("--force", action="store_true",
                             help="re-analyse every stored activity, drifted or not")
    _add_common(recompute_p)
    _add_snapshots_dir(recompute_p)

    snapshot_p = sub.add_parser(
        "snapshot", help="write a verified corpus snapshot, keeping the last 10 (ADR-0018)"
    )
    snapshot_p.add_argument("--keep", type=int, default=KEEP,
                            help="how many snapshots to retain")
    _add_common(snapshot_p)
    _add_snapshots_dir(snapshot_p)

    from pacelab.watch import DEFAULT_INTERVAL_S, DEFAULT_WINDOW_DAYS

    watch_p = sub.add_parser("watch", help="poll intervals.icu and keep annotations current")
    watch_p.add_argument("--no-recompute", action="store_true",
                         help="skip the reconciliation pass at the top of each tick")
    watch_p.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_S,
                         help="seconds between ticks")
    watch_p.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS,
                         help="rolling sync window per tick")
    watch_p.add_argument("--ticks", type=int, default=None,
                         help="stop after N ticks (1 = cron-compatible single pass)")
    _add_common(watch_p)
    _add_snapshots_dir(watch_p)

    trend_p = sub.add_parser("trend", help="NP over time — fitness with conditions stripped out")
    trend_p.add_argument("--db", type=Path, default=Path("pacelab.db"), help="results database")

    cal_p = sub.add_parser("calibrate", help="fit personal coefficients (report only)")
    cal_p.add_argument("--db", type=Path, default=Path("pacelab.db"), help="results database")

    health_p = sub.add_parser("health", help="is the watch loop alive and succeeding?")
    health_p.add_argument("--db", type=Path, default=Path("pacelab.db"), help="results database")

    args = parser.parse_args(argv)
    _configure_logging(args.log_level)
    if args.command == "health":
        return _run_health(args)
    if args.command == "sync":
        return _run_sync(args)
    if args.command == "publish":
        return _run_publish(args)
    if args.command == "recompute":
        return _run_recompute(args)
    if args.command == "snapshot":
        return _run_snapshot(args)
    if args.command == "watch":
        return _run_watch(args)
    if args.command == "trend":
        return _run_trend(args)
    if args.command == "calibrate":
        return _run_calibrate(args)
    return _run_analyze(args)


if __name__ == "__main__":
    raise SystemExit(main())
