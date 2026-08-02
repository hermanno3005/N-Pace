import logging
import urllib.error

import pytest

from pacelab.weather.retry import fetch_with_retry


def test_returns_the_first_successful_result_without_sleeping():
    def fake_sleep(seconds):
        raise AssertionError("a call that succeeds must not pause")

    assert fetch_with_retry(lambda: "payload", sleep=fake_sleep) == "payload"


def test_retries_a_stalled_handshake_and_returns_the_later_success():
    # The measured fault (ADR-0020): one urlopen in ~20 stalls out the whole timeout.
    outcomes = [urllib.error.URLError("handshake timed out"), "payload"]
    pauses = []

    def call():
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    assert fetch_with_retry(call, sleep=pauses.append) == "payload"
    assert pauses == [1.0]  # one fixed pause, and only between attempts


def test_retries_a_bare_timeout_error():
    outcomes = [TimeoutError("read timed out"), "payload"]

    def call():
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    assert fetch_with_retry(call, sleep=lambda s: None) == "payload"


def test_does_not_retry_an_http_error():
    # HTTPError subclasses URLError, so this has to be excluded explicitly: a status code
    # means the server answered, and it will not answer differently inside one tick.
    attempts = []

    def call():
        attempts.append(1)
        raise urllib.error.HTTPError("http://x", 404, "Not Found", {}, None)

    with pytest.raises(urllib.error.HTTPError):
        fetch_with_retry(call, sleep=lambda s: None)

    assert len(attempts) == 1


def test_exhaustion_propagates_the_last_failure():
    attempts = []

    def call():
        attempts.append(1)
        raise urllib.error.URLError("handshake timed out")

    with pytest.raises(urllib.error.URLError):
        fetch_with_retry(call, attempts=3, sleep=lambda s: None)

    assert len(attempts) == 3
    # The last attempt fails without a trailing pause nobody waits on.


def test_logs_one_warning_per_failed_attempt_without_a_traceback(caplog):
    outcomes = [urllib.error.URLError("handshake timed out"), "payload"]

    def call():
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    with caplog.at_level(logging.WARNING, logger="pacelab.weather.retry"):
        fetch_with_retry(call, sleep=lambda s: None)

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.WARNING
    assert record.exc_info is None
    assert "attempt 1/3" in record.getMessage()
    assert "handshake timed out" in record.getMessage()


def test_a_single_attempt_never_retries():
    attempts = []

    def call():
        attempts.append(1)
        raise urllib.error.URLError("boom")

    with pytest.raises(urllib.error.URLError):
        fetch_with_retry(call, attempts=1, sleep=lambda s: None)

    assert len(attempts) == 1
