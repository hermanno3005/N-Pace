"""Retry the weather fetchers' individual HTTP requests (ADR-0020).

Bring-up measured ~1 in 20 TLS handshakes to open-meteo stalling for the full timeout and
aborting the whole tick. This wraps one request — not one ``fetch_hourly``, which issues two —
so a stalled call never repays a sibling that already succeeded.

Only transport failures retry. ``HTTPError`` is a ``URLError`` subclass, so it is excluded
explicitly: a status code means the server was reached and answered, and it will not answer
differently inside one tick. The 15-minute tick is the retry for anything slower-moving.
"""

import json
import logging
import ssl
import time
import urllib.error
import urllib.request
from typing import Any, Callable

log = logging.getLogger(__name__)

_PAUSE_S = 1.0  # Fixed, not exponential: the server is fine, the path is not.


def fetch_json(
    url: str, *, timeout: float, context: ssl.SSLContext, sleep=time.sleep
) -> dict:
    """GET ``url`` and parse the JSON body, retrying transport failures.

    The unit of retry both fetchers share: one request, one timeout, one policy.
    """

    def request() -> dict:
        with urllib.request.urlopen(url, timeout=timeout, context=context) as resp:
            return json.load(resp)

    return fetch_with_retry(request, sleep=sleep)


def fetch_with_retry(
    call: Callable[[], Any], *, attempts: int = 3, sleep=time.sleep
) -> Any:
    """Call ``call()``, retrying transport failures up to ``attempts`` times.

    ``sleep`` is injected (``watch.py``'s precedent) so tests assert the retry without
    waiting. The last failure propagates untouched — ADR-0017's tick handler logs it.
    """
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except urllib.error.HTTPError:
            raise  # A subclass of URLError, and never retryable.
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == attempts:
                raise
            # One line, no traceback: cheap at the measured rate, and the only signal that
            # would show 1-in-20 becoming 1-in-3 before it starts costing ticks.
            log.warning("retrying open-meteo (attempt %d/%d): %s", attempt, attempts, exc)
            sleep(_PAUSE_S)
