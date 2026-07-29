import logging
from datetime import date

import pytest

from pacelab.watch import tick, watch


class FakeHeartbeat:
    """Stands in for `ResultStore.record_tick` — the writer `tick()` is handed (ADR-0017).

    It keeps the one piece of state the real one keeps: the failure streak it returns.
    """

    def __init__(self):
        self.calls = []
        self.failures = 0

    def __call__(self, ok, summary=None, error=None, recomputed=False):
        self.failures = 0 if ok else self.failures + 1
        self.calls.append({"ok": ok, "summary": summary, "error": error,
                           "recomputed": recomputed})
        return self.failures


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

    watch(lambda oldest, newest: events.append("sync"), interval_s=900, window_days=14,
          ticks=2, sleep=lambda s: None, recompute_fn=recompute_fn)

    assert events == ["recompute", "sync"]  # tick 1 aborted, tick 2 ran in full


# --- the heartbeat and the log (ADR-0017) -------------------------------------------


def test_a_successful_tick_records_a_heartbeat():
    beat = FakeHeartbeat()

    tick(lambda oldest, newest: [("i1", "ok"), ("i2", "skip"), ("i3", "skip")],
         window_days=14, today=date(2026, 7, 7), record_fn=beat)

    assert beat.calls == [{"ok": True, "summary": "3 listed, 1 ok, 2 skip",
                           "error": None, "recomputed": False}]


def test_a_failed_tick_records_the_error():
    # The failure branch is the only code that sees a failed pass — recording from inside
    # the sync context would capture successes only.
    beat = FakeHeartbeat()

    def broken_sync(oldest, newest):
        raise RuntimeError("intervals.icu unreachable")

    assert tick(broken_sync, window_days=14, today=date(2026, 7, 7), record_fn=beat) is None

    assert beat.calls == [{"ok": False, "summary": None,
                           "error": "RuntimeError: intervals.icu unreachable",
                           "recomputed": False}]


def test_a_tick_that_recomputed_says_so():
    # Only a pass with work to do: the pass runs every tick and is silent when the corpus
    # is settled, so recording it as a recompute would make the field mean nothing.
    worked, settled = FakeHeartbeat(), FakeHeartbeat()

    tick(lambda o, n: [], window_days=14, today=date(2026, 7, 7),
         recompute_fn=lambda: [("i1", "ok")], record_fn=worked)
    tick(lambda o, n: [], window_days=14, today=date(2026, 7, 7),
         recompute_fn=lambda: [], record_fn=settled)

    assert worked.calls[0]["recomputed"] is True
    assert settled.calls[0]["recomputed"] is False


def test_a_contained_recompute_failure_still_counts_as_a_successful_tick(caplog):
    # `consecutive_failures` counts escaping exceptions and nothing else. The pass failed,
    # the sync annotated today's run — that tick did its job, and the log says the rest.
    beat = FakeHeartbeat()

    def broken_recompute():
        raise RuntimeError("recompute exploded")

    with caplog.at_level(logging.INFO, logger="pacelab.watch"):
        tick(lambda o, n: [("i1", "ok")], window_days=14, today=date(2026, 7, 7),
             recompute_fn=broken_recompute, record_fn=beat)

    assert beat.calls[0]["ok"] is True
    assert any("recompute exploded" in r.getMessage() for r in caplog.records)


def test_a_failed_snapshot_is_recorded_before_it_propagates():
    # It aborts the tick (ADR-0018), which makes it a failure like any other: a Pi that
    # cannot write its snapshot must not read healthy while it stops recomputing.
    from pacelab.snapshot import SnapshotError

    beat = FakeHeartbeat()

    def unprotected_recompute():
        raise SnapshotError("no space left on device")

    with pytest.raises(SnapshotError):
        tick(lambda o, n: [], window_days=14, today=date(2026, 7, 7),
             recompute_fn=unprotected_recompute, record_fn=beat)

    assert beat.calls == [{"ok": False, "summary": None,
                           "error": "SnapshotError: no space left on device",
                           "recomputed": False}]


def test_a_failure_streak_logs_a_traceback_once_then_one_liners(caplog):
    # The deliberate inverse of the warnings.warn bug this replaced: repeats stay loud,
    # but only the first one is worth reading in full.
    beat = FakeHeartbeat()

    def broken_sync(oldest, newest):
        raise RuntimeError("expired API key")

    with caplog.at_level(logging.INFO, logger="pacelab.watch"):
        for _ in range(3):
            tick(broken_sync, window_days=14, today=date(2026, 7, 7), record_fn=beat)

    failures = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert [r.exc_info is not None for r in failures] == [True, False, False]
    assert "3 consecutive" in failures[-1].getMessage()
    assert "expired API key" in failures[-1].getMessage()


def test_a_recovered_streak_gets_its_traceback_again(caplog):
    # A second outage is a second thing to read: the streak resets, so the count does.
    beat = FakeHeartbeat()
    attempts = []

    def flaky_sync(oldest, newest):
        attempts.append(1)
        if len(attempts) != 2:
            raise RuntimeError("blip")
        return []

    with caplog.at_level(logging.INFO, logger="pacelab.watch"):
        for _ in range(3):
            tick(flaky_sync, window_days=14, today=date(2026, 7, 7), record_fn=beat)

    failures = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert [r.exc_info is not None for r in failures] == [True, True]


def test_the_loop_logs_a_failed_snapshot_rather_than_warning(caplog):
    # warnings.warn printed once per unique (message, location) and then went silent —
    # exactly backwards for a daemon, where the repetition is the signal.
    from pacelab.snapshot import SnapshotError

    def unprotected_recompute():
        raise SnapshotError("no space left on device")

    with caplog.at_level(logging.INFO, logger="pacelab.watch"):
        watch(lambda o, n: [], interval_s=900, window_days=14, ticks=2,
              sleep=lambda s: None, recompute_fn=unprotected_recompute,
              record_fn=FakeHeartbeat())

    failures = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(failures) == 2  # both ticks, not just the first
    assert all("no space left on device" in r.getMessage() for r in failures)


def test_a_heartbeat_that_cannot_be_written_does_not_end_the_loop(caplog):
    # The sharpest case of "contained": the failure that fills the disk is the same one
    # that fails this write, and a daemon that dies while reporting that it is unwell is
    # worse than one that stays quiet.
    def broken_writer(ok, summary=None, error=None, recomputed=False):
        raise RuntimeError("database or disk is full")

    with caplog.at_level(logging.INFO, logger="pacelab.watch"):
        watch(lambda o, n: [], interval_s=900, window_days=14, ticks=2,
              sleep=lambda s: None, record_fn=broken_writer)

    assert any("could not record the heartbeat" in r.getMessage() for r in caplog.records)
