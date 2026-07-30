"""The watch loop (ADR-0013): poll intervals.icu and keep annotations current.

Each tick runs one idempotent sync pass over a rolling window ending today — new runs get
analysed (provisionally if inside the ERA5 lag) and annotated; stored provisionals are
finalized as the archive catches up; everything already current is skipped for the cost of
one listing call. Failures are contained per tick: the next tick retries.

Every tick also leaves a heartbeat behind (ADR-0017), written through an injected callable
so this module stays free of any storage import, and reports itself through `logging` —
the daemon's only output channel, since nobody is watching stdout live.
"""

import logging
import time
from collections import Counter
from datetime import date, timedelta

from pacelab.snapshot import SnapshotError

DEFAULT_INTERVAL_S = 900  # 15 min: ~annotation-within-minutes at 96 listing calls/day
DEFAULT_WINDOW_DAYS = 14  # comfortably covers ERA5's ~week lag, so provisionals finalize

log = logging.getLogger(__name__)


def _summarize(outcomes) -> str:
    """"5 listed, 1 ok, 4 skip" — what one tick did, short enough for a heartbeat row."""
    if not outcomes:
        return "0 listed"
    counts = Counter(status for _, status in outcomes)
    return ", ".join([f"{len(outcomes)} listed",
                      *(f"{n} {status}" for status, n in sorted(counts.items()))])


def tick(sync_fn, window_days: int, today: date | None = None, recompute_fn=None,
         record_fn=None):
    """One poll: reconcile the corpus, then sync the rolling window.

    Returns the sync outcomes, or None on a contained failure. ``recompute_fn`` runs
    first and against the archive tier only (ADR-0016), so a provisional still inside
    ERA5's lag falls through to sync's forecast tier in this same tick. It is optional:
    ``pacelab watch --no-recompute`` disables a misbehaving pass without stopping the loop.

    ``record_fn`` is the heartbeat writer (``ResultStore.record_tick``), injected rather
    than imported. Both branches below record it, and that is forced rather than
    stylistic: ``_SyncContext.run`` lets exceptions propagate, so this ``except`` is the
    only code that sees a failed pass. The writer returns the failure streak, which
    decides whether the log line carries a full traceback.

    A recompute failure is contained and the sync still runs — that tick is a *success*,
    because the counter means "escaping exceptions" and nothing else (ADR-0017). A failed
    corpus snapshot is the one exception: ``SnapshotError`` **propagates out of the tick**
    (ADR-0018) once recorded, so the sync half never runs and the caller can tell a failed
    tick from a quiet one.
    """
    today = today or date.today()
    oldest = (today - timedelta(days=window_days)).isoformat()
    recomputed = False
    try:
        if recompute_fn is not None:
            try:
                recomputed = bool(recompute_fn())
            except SnapshotError:
                # Deliberately not caught here. The snapshot exists to protect a
                # whole-corpus rewrite; recomputing without it removes the protection at
                # the single moment it was built for, and a Pi that cannot write 1.8 MB is
                # broken in a way that should be loud rather than contained.
                raise
            except Exception as e:  # noqa: BLE001 — the pass must not take the sync down
                log.warning("recompute failed (%s) — syncing anyway", e)
        outcomes = sync_fn(oldest, today.isoformat())
    except Exception as e:  # noqa: BLE001 — the loop must survive anything transient
        _log_failure(e, _record(record_fn, False, error=f"{type(e).__name__}: {e}"))
        if isinstance(e, SnapshotError):
            raise
        return None
    summary = _summarize(outcomes)
    _record(record_fn, True, summary=summary, recomputed=recomputed)
    log.info("tick ok — %s", summary)
    return outcomes


def _record(record_fn, ok: bool, summary: str | None = None, error: str | None = None,
            recomputed: bool = False) -> int | None:
    """Write the heartbeat if there is one to write, and return the failure streak.

    Contained like everything else in a tick, and for a sharper reason than most: the
    observability of a failure must never be what ends the loop. The failure that takes
    the disk down (ADR-0018's full SD card) is exactly the one that also fails this write,
    and a daemon that dies while reporting that it is unwell is worse than a silent one.
    """
    if record_fn is None:
        return None
    try:
        return record_fn(ok, summary=summary, error=error, recomputed=recomputed)
    except Exception as e:  # noqa: BLE001 — recording is not worth the process
        log.warning("could not record the heartbeat (%s) — `pacelab health` will read "
                    "stale until the next tick that can write", e)
        return None


def _log_failure(exc: BaseException, failures: int | None) -> None:
    """A traceback once per streak, then one-liners carrying the count.

    The first occurrence is the one worth reading after the fact; the repeats need to
    prove only that it is still happening. The deliberate inverse of ``warnings.warn``,
    whose default filter goes silent on exactly the repetition that is the signal here.
    """
    if failures is None or failures <= 1:
        log.error("tick failed (%s: %s) — retrying next tick", type(exc).__name__, exc,
                  exc_info=exc)
    else:
        log.error("tick failed (%s: %s) — %d consecutive, retrying next tick",
                  type(exc).__name__, exc, failures)


def watch(sync_fn, interval_s: int = DEFAULT_INTERVAL_S, window_days: int = DEFAULT_WINDOW_DAYS,
          ticks: int | None = None, sleep=time.sleep, recompute_fn=None,
          record_fn=None) -> None:
    """Tick forever (or ``ticks`` times — ``1`` makes it cron-compatible).

    A raised tick (today: only a failed snapshot) is slept off rather than ending the
    process — a Pi that recovers disk space must start annotating again with nobody there.
    It has already been logged and recorded by ``tick`` itself, which is where the streak
    count lives, so exactly one place reports a failed tick.
    """
    n = 0
    while True:
        try:
            tick(sync_fn, window_days, recompute_fn=recompute_fn, record_fn=record_fn)
        except SnapshotError:
            pass  # logged and recorded inside tick(); the corpus is untouched
        n += 1
        if ticks is not None and n >= ticks:
            return
        sleep(interval_s)
