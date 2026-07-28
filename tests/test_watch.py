from datetime import date

import pytest

from pacelab.watch import tick, watch


def test_tick_syncs_a_rolling_window_ending_today():
    calls = []

    def fake_sync(oldest, newest):
        calls.append((oldest, newest))
        return [("i1", "skip")]

    outcomes = tick(fake_sync, window_days=14, today=date(2026, 7, 7))

    assert calls == [("2026-06-23", "2026-07-07")]
    assert outcomes == [("i1", "skip")]


def test_tick_contains_failures():
    # A network blip or rate limit must not kill the loop — the next tick retries.
    def broken_sync(oldest, newest):
        raise RuntimeError("intervals.icu unreachable")

    assert tick(broken_sync, window_days=14, today=date(2026, 7, 7)) is None


def test_watch_runs_ticks_and_sleeps_between_them():
    events = []

    def fake_sync(oldest, newest):
        events.append("sync")
        return []

    def fake_sleep(seconds):
        events.append(f"sleep {seconds}")

    watch(fake_sync, interval_s=900, window_days=14, ticks=3, sleep=fake_sleep)

    assert events == ["sync", "sleep 900", "sync", "sleep 900", "sync"]


def test_tick_recomputes_before_syncing():
    # Ordering is load-bearing (ADR-0016): the archive-only recompute runs first, so a
    # provisional still inside the lag is skipped there and picked up by sync's forecast
    # tier in the same tick.
    events = []

    outcomes = tick(
        lambda oldest, newest: events.append("sync") or [("i1", "ok")],
        window_days=14,
        today=date(2026, 7, 7),
        recompute_fn=lambda: events.append("recompute"),
    )

    assert events == ["recompute", "sync"]
    assert outcomes == [("i1", "ok")]


def test_tick_without_a_recompute_fn_only_syncs():
    # What --no-recompute buys: a misbehaving pass can be switched off without taking
    # the watch loop down with it.
    events = []

    tick(lambda oldest, newest: events.append("sync"), window_days=14, today=date(2026, 7, 7))

    assert events == ["sync"]


def test_a_failing_recompute_does_not_take_the_sync_down():
    # The pass is the newer, riskier half of the tick; sync must still annotate today's
    # run. A shared outage fails the sync on its own, contained separately.
    events = []

    def broken_recompute():
        raise RuntimeError("recompute exploded")

    outcomes = tick(lambda oldest, newest: events.append("sync") or [("i1", "ok")],
                    window_days=14, today=date(2026, 7, 7), recompute_fn=broken_recompute)

    assert events == ["sync"]
    assert outcomes == [("i1", "ok")]


def test_watch_recomputes_on_every_tick():
    # Not boot-only: try_publish never raises, so a pass can finish with rows stamped
    # current and annotations stale. Every tick is what closes that gap.
    events = []

    watch(lambda oldest, newest: events.append("sync"), interval_s=900, window_days=14,
          ticks=2, sleep=lambda s: None, recompute_fn=lambda: events.append("recompute"))

    assert events == ["recompute", "sync", "recompute", "sync"]


def test_a_failed_snapshot_fails_the_whole_tick():
    # ADR-0018: the snapshot guards the rewrite, so its failure is not contained the way
    # an ordinary recompute failure is. It propagates out of the tick — sync does not run,
    # and a caller (ADR-0017's health handler) can tell this apart from a quiet tick,
    # which a contained `return None` would not.
    from pacelab.snapshot import SnapshotError

    events = []

    def unprotected_recompute():
        raise SnapshotError("no space left on device")

    with pytest.raises(SnapshotError):
        tick(lambda oldest, newest: events.append("sync") or [("i1", "ok")],
             window_days=14, today=date(2026, 7, 7), recompute_fn=unprotected_recompute)

    assert events == []  # not even the sync half ran


def test_the_loop_survives_a_failed_snapshot():
    # Failing the tick must not mean failing the process: a Pi that recovers disk space
    # starts annotating again on its own, with nobody there.
    from pacelab.snapshot import SnapshotError

    events = []
    attempts = []

    def recompute_fn():
        attempts.append(1)
        if len(attempts) == 1:
            raise SnapshotError("no space left on device")
        events.append("recompute")

    with pytest.warns(UserWarning, match="snapshot"):
        watch(lambda oldest, newest: events.append("sync"), interval_s=900, window_days=14,
              ticks=2, sleep=lambda s: None, recompute_fn=recompute_fn)

    assert events == ["recompute", "sync"]  # tick 1 aborted, tick 2 ran in full
