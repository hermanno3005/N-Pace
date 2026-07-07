from datetime import date

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
