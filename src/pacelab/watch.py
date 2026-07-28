"""The watch loop (ADR-0013): poll intervals.icu and keep annotations current.

Each tick runs one idempotent sync pass over a rolling window ending today — new runs get
analysed (provisionally if inside the ERA5 lag) and annotated; stored provisionals are
finalized as the archive catches up; everything already current is skipped for the cost of
one listing call. Failures are contained per tick: the next tick retries.
"""

import time
import warnings
from datetime import date, timedelta

from pacelab.snapshot import SnapshotError

DEFAULT_INTERVAL_S = 900  # 15 min: ~annotation-within-minutes at 96 listing calls/day
DEFAULT_WINDOW_DAYS = 14  # comfortably covers ERA5's ~week lag, so provisionals finalize


def tick(sync_fn, window_days: int, today: date | None = None, recompute_fn=None):
    """One poll: reconcile the corpus, then sync the rolling window.

    Returns the sync outcomes, or None on a contained failure. ``recompute_fn`` runs
    first and against the archive tier only (ADR-0016), so a provisional still inside
    ERA5's lag falls through to sync's forecast tier in this same tick. It is optional:
    ``pacelab watch --no-recompute`` disables a misbehaving pass without stopping the loop.

    A recompute failure is contained and the sync still runs — except for a failed corpus
    snapshot, which fails the tick entire (ADR-0018).
    """
    today = today or date.today()
    oldest = (today - timedelta(days=window_days)).isoformat()
    if recompute_fn is not None:
        try:
            recompute_fn()
        except SnapshotError as e:
            # The one failure that is not contained (ADR-0018). The snapshot exists to
            # protect a whole-corpus rewrite; recomputing without it removes the
            # protection at the single moment it was built for, and a Pi that cannot
            # write 1.8 MB is broken in a way that should be loud. So the tick fails
            # entire — sync included — and the corpus stays untouched for the next one.
            warnings.warn(f"snapshot failed ({e}) — tick aborted, corpus untouched",
                          stacklevel=2)
            return None
        except Exception as e:  # noqa: BLE001 — the pass must not take the sync down
            warnings.warn(f"recompute failed ({e}) — syncing anyway", stacklevel=2)
    try:
        return sync_fn(oldest, today.isoformat())
    except Exception as e:  # noqa: BLE001 — the loop must survive anything transient
        warnings.warn(f"watch tick failed ({e}) — retrying next tick", stacklevel=2)
        return None


def watch(sync_fn, interval_s: int = DEFAULT_INTERVAL_S, window_days: int = DEFAULT_WINDOW_DAYS,
          ticks: int | None = None, sleep=time.sleep, recompute_fn=None) -> None:
    """Tick forever (or ``ticks`` times — ``1`` makes it cron-compatible)."""
    n = 0
    while True:
        tick(sync_fn, window_days, recompute_fn=recompute_fn)
        n += 1
        if ticks is not None and n >= ticks:
            return
        sleep(interval_s)
