"""The health predicate and its human summary (ADR-0017)."""

from pacelab.health import format_health, is_healthy
from pacelab.store import Heartbeat

NOW = 1_800_000_000.0


def _beat(**overrides) -> Heartbeat:
    fields = {
        "last_tick_at": NOW - 60, "last_success_at": NOW - 60, "consecutive_failures": 0,
        "last_error": None, "last_error_at": None, "last_recompute_at": None,
        "last_tick_summary": "3 listed, 1 ok, 2 skip", "interval_s": 900,
    }
    return Heartbeat(**{**fields, **overrides})


def test_a_loop_that_ticked_recently_is_healthy():
    assert is_healthy(_beat(), now=NOW)


def test_a_loop_that_has_never_ticked_is_unhealthy():
    # No row at all: the container started and the first tick never landed, or the db is
    # not the one the loop writes. Either way, not healthy.
    assert not is_healthy(None, now=NOW)
    assert "never" in format_health(None, now=NOW).lower()


def test_a_loop_that_has_never_succeeded_is_unhealthy():
    # NULL last_success_at reads as infinitely stale — a loop that has only ever failed is
    # unhealthy, correctly, however recently it ticked.
    beat = _beat(last_success_at=None, last_tick_at=NOW, consecutive_failures=9,
                 last_error="Account: INTERVALS_API_KEY is not set", last_error_at=NOW)

    assert not is_healthy(beat, now=NOW)


def test_unhealthy_is_no_success_within_three_intervals():
    # One clause covering all three failure modes: a dead loop, a wedged loop and a
    # live-but-failing loop all stop producing successes.
    assert is_healthy(_beat(last_success_at=NOW - 2699), now=NOW)
    assert not is_healthy(_beat(last_success_at=NOW - 2701), now=NOW)


def test_the_threshold_tracks_the_recorded_interval():
    # Stored rather than assumed, so `--interval 60` is not permanently unhealthy and
    # `--interval 3600` does not go unnoticed for three hours.
    assert not is_healthy(_beat(last_success_at=NOW - 200, interval_s=60), now=NOW)
    assert is_healthy(_beat(last_success_at=NOW - 200, interval_s=3600), now=NOW)


def test_a_missing_interval_falls_back_to_the_default():
    # A row written before --interval was recorded, or by an older build.
    assert is_healthy(_beat(last_success_at=NOW - 2699, interval_s=None), now=NOW)
    assert not is_healthy(_beat(last_success_at=NOW - 2701, interval_s=None), now=NOW)


def test_a_dead_loop_reads_unhealthy_even_with_a_clean_counter():
    # Why the predicate is not `consecutive_failures`: the counter only advances while
    # ticks still happen, so a killed process freezes it at zero forever.
    assert not is_healthy(_beat(last_tick_at=NOW - 90_000, last_success_at=NOW - 90_000,
                                consecutive_failures=0), now=NOW)


def test_the_summary_says_what_it_is_and_when():
    out = format_health(_beat(last_recompute_at=NOW - 7200), now=NOW)

    assert out.splitlines()[0].startswith("healthy")
    assert "3 listed, 1 ok, 2 skip" in out
    assert "900" in out  # the interval the threshold is derived from


def test_the_summary_leads_with_the_error_when_it_is_failing():
    out = format_health(
        _beat(last_success_at=NOW - 90_000, last_tick_at=NOW - 60, consecutive_failures=17,
              last_error="RateLimited: 429 too many requests", last_error_at=NOW - 60),
        now=NOW,
    )

    assert out.splitlines()[0].startswith("UNHEALTHY")
    assert "17" in out
    assert "RateLimited: 429 too many requests" in out


def test_a_recovered_loop_still_shows_the_last_error():
    # "It broke at 03:00 and came back" is most of what a heartbeat read after the fact
    # is for; the healthy verdict does not erase the evidence.
    out = format_health(_beat(last_error="RuntimeError: blip", last_error_at=NOW - 90_000),
                        now=NOW)

    assert out.startswith("healthy")
    assert "RuntimeError: blip" in out
