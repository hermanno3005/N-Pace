"""Is the watch loop healthy? One predicate, read by `pacelab health` (ADR-0017).

Unhealthy is *no successful tick within 3 × the recorded interval* — a single clause that
covers a dead loop, a wedged loop and a live-but-failing loop alike, since all three stop
producing successes. `consecutive_failures` is deliberately not the predicate: it only
advances while ticks still happen, so a killed process freezes it and reads healthy
forever. It is still reported, and it is what a future push notification fires on.
"""

from datetime import datetime, timezone

from pacelab.store import Heartbeat
from pacelab.watch import DEFAULT_INTERVAL_S

STALE_MULTIPLE = 3  # ~45 min at the default 15-minute interval


def threshold_s(beat: Heartbeat | None, default_interval_s: int = DEFAULT_INTERVAL_S) -> int:
    """How old the last success may get before the loop is unhealthy."""
    interval = (beat.interval_s if beat and beat.interval_s else default_interval_s)
    return STALE_MULTIPLE * interval


def is_healthy(beat: Heartbeat | None, now: float,
               default_interval_s: int = DEFAULT_INTERVAL_S) -> bool:
    """True when the loop produced a successful tick recently enough.

    A missing row and a NULL `last_success_at` both read as infinitely stale: a loop that
    has never succeeded is unhealthy, however recently it tried.
    """
    if beat is None or beat.last_success_at is None:
        return False
    return now - beat.last_success_at <= threshold_s(beat, default_interval_s)


def format_health(beat: Heartbeat | None, now: float,
                  default_interval_s: int = DEFAULT_INTERVAL_S) -> str:
    """The human summary `pacelab health` prints. First line is the verdict."""
    threshold = threshold_s(beat, default_interval_s)
    if beat is None:
        return (f"UNHEALTHY  no heartbeat recorded — `pacelab watch` has never ticked "
                f"against this database")
    if beat.last_success_at is None:
        lines = [f"UNHEALTHY  no successful tick, ever (threshold {_duration(threshold)})"]
    elif is_healthy(beat, now, default_interval_s):
        lines = [f"healthy    last success {_ago(beat.last_success_at, now)} "
                 f"(threshold {_duration(threshold)})"]
    else:
        lines = [f"UNHEALTHY  no successful tick in {_ago(beat.last_success_at, now)} "
                 f"(threshold {_duration(threshold)})"]

    lines.append(f"  last tick      {_stamp(beat.last_tick_at)}"
                 + (f"   {beat.last_tick_summary}" if beat.last_tick_summary else ""))
    lines.append(f"  last success   {_stamp(beat.last_success_at)}")
    lines.append(f"  last recompute {_stamp(beat.last_recompute_at)}")
    lines.append(f"  failures       {beat.consecutive_failures} consecutive")
    if beat.last_error:
        lines.append(f"  last error     {beat.last_error}  ({_stamp(beat.last_error_at)})")
    lines.append(f"  interval       {beat.interval_s or default_interval_s}s")
    return "\n".join(lines)


def _stamp(when: float | None) -> str:
    """UTC, like every other timestamp the container emits — it carries no tz data."""
    if when is None:
        return "never"
    return datetime.fromtimestamp(when, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def _ago(when: float, now: float) -> str:
    return f"{_duration(now - when)} ago"


def _duration(seconds: float) -> str:
    seconds = int(max(seconds, 0))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h {seconds % 3600 // 60}m"
    return f"{seconds // 86400}d {seconds % 86400 // 3600}h"
