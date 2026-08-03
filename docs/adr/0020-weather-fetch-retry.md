# The weather fetch retries transport failures; everything else still aborts the tick

Bring-up (#16) measured the network boundary from inside the running container: of 20 real
`OpenMeteoFetcher.fetch_hourly` calls, 19 returned in ~0.1–3 s and **one stalled for the full
30 s timeout** and failed with `URLError: <urlopen error _ssl.c:1015: The handshake operation
timed out>`. Roughly 1 in 20. It is the path and not the code — MTUs are 1500 end to end and
`curl` from the same container returns 200 in ~0.1 s repeatedly.

Nothing retries anywhere at that boundary. `ForecastFetcher` and `OpenMeteoFetcher` call
`urllib.request.urlopen` directly, so **one stalled handshake aborts the entire tick** — and
three consecutive failures is exactly ADR-0017's unhealthy predicate, so the probe flaps for a
reason that has nothing to do with the daemon's health.

## Retry lives in the fetchers, not in the shared `Http` seam

Three layers could own it. `UrllibHttp` is the shared seam, but it also serves the
intervals.icu **annotation write**, and a blind retry on a PUT is not free. A decorator around
the `Fetcher` protocol would sit in one place, but `OpenMeteoFetcher.fetch_hourly` issues
**two** upstream calls (`era5_land` then `era5`), so retrying at that level repays a
successful first call to fix a stalled second one.

So the retry wraps the individual request: `OpenMeteoFetcher._request` and `ForecastFetcher`'s
single `urlopen`. Narrowest blast radius, and the unit of retry is the unit that actually
failed. `UrllibHttp` is untouched and keeps its 30 s timeout.

One property comes free from where the seam already sits: `WeatherUnavailable` is raised by
`WeatherService._hourly` when the fetcher returns an **empty** series — *above* the fetcher.
Nothing inside the fetcher can see it, so the ERA5-lag case can never be retried. That matters
more than it sounds: an empty series is exactly the call that is deliberately uncached
(ADR-0012 — caching it would block the date forever), so it is the call that repeats on
*every* tick. Retrying it would triple the cost of the only calls that recur.

## Only transport failures are retryable

`urllib.error.HTTPError` is a **subclass** of `URLError`, so a naive `except URLError` retries
every 404, 401 and 400. The split is therefore explicit:

- **Retried:** `URLError` and bare `TimeoutError` — the stalled handshake, a connection reset,
  a DNS blip.
- **Re-raised on the first attempt:** anything that is an `HTTPError`. Every status code —
  400, 404, 429, 500 — propagates exactly as it does today.

A status code means the server was reached and answered. A second identical request will not
change its mind inside one tick, and the 15-minute tick is already the retry for anything
slower-moving. 429 is the sharpest case for retrying and the sharpest case against: it is the
one retry that can actively make things worse, and doing it correctly means honouring
`Retry-After` rather than a fixed backoff. Not built until something observes one.

## Three attempts at 10 s, paid for out of the existing worst case

The measurements decide the numbers. Successes land in **0.1–3 s**; a stall **never recovers**
— it burns the full 30 s and then fails. So the 30 s timeout is not protecting a slow-but-alive
request, it is only how long it takes to notice a dead one. That means attempts can be spent
out of the existing budget rather than added on top:

**3 attempts × 10 s, with a ~1 s pause between.** Worst case per call stays **30 s**, identical
to today's single attempt, so nothing gets slower in the bad case. 10 s is 3× the slowest
observed success. At the measured rate a call's failure odds go from ~5% to ~0.01%, and
expected added latency is well under a second per call. The pause exists to stop a hot loop on
failures that return instantly — the IPv6 `ENETUNREACH` that `urllib` already falls through is
one.

Backoff is fixed, not exponential. Exponential backoff protects an overloaded server; the
server here is demonstrably fine, and the fault is in the path.

## A residual failure still aborts the pass

The tempting next step is to catch the transport failure per activity in `sync` and
`recompute`, as `WeatherUnavailable` already is, so one unreachable cell-day stops costing
activities that had nothing to do with it. **Deliberately not done**, for two reasons.

ADR-0017 defines a successful tick as one that raised nothing, and reports `publish-failed`
through the summary rather than the failure counter precisely so one bad activity cannot pin
the loop unhealthy forever. Degrading transport failures the same way inverts that: a
*genuinely dead network* would report every tick as a success, and health would read green
while nothing worked. Retry takes the per-call failure rate down ~400×, so a tick that still
fails three times running now means the network really is broken — which is what the unhealthy
predicate is for. Retry fixes the flapping; degradation would fix it by blinding the probe.

And the case that looks most expensive is already contained. A full-corpus walk (#27, the
first live `model_version` bump) is the run with the most network calls this system will ever
make — but `tick()` already catches a failed `recompute` and runs the sync anyway, and
ADR-0016's pass is store-driven and resumable by construction: the next tick re-enumerates
whatever is still stale. An aborted walk costs 15 minutes and no data.

## Shape

`pacelab/weather/retry.py` holds `fetch_with_retry(call, *, attempts=3, sleep=time.sleep)` —
a plain function both fetchers wrap their `urlopen` in. `sleep` is injected following
`watch.py`'s precedent, so tests assert the retry without ever sleeping. The 10 s becomes the
constructor default on both fetchers.

Each failed attempt logs **one WARNING, no traceback** —
`retrying open-meteo (attempt 1/3): <handshake timed out>`. Cheap at the measured rate, and it
is the only signal that would show the 1-in-20 becoming 1-in-3 before it starts costing ticks.
Exhaustion needs nothing extra: it propagates, and ADR-0017's tick handler already logs it
with a traceback once per streak.
