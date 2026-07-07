# Automatic annotation via a polling watch loop, not webhooks

New activities are picked up automatically by **`pacelab watch`** — a long-running loop
(default: every 15 min) that runs one idempotent sync pass over a rolling window (default:
14 days) — shipped as a Docker container for the always-on HermiPi (realizing C-4). The
athlete's machine never needs to be on; annotations appear within ~one tick of upload.

**The trigger surface is intervals.icu, not Strava.** A Strava-only activity has no
downloadable original (ADR-0008), so a Strava-side trigger could never lead to an analysis;
and Strava webhooks sit behind the paid API (ADR-0011 amendment). Everything analysable
arrives at intervals.icu, so watching it covers both platforms.

**Why poll rather than push (webhooks):** a webhook needs a publicly reachable HTTPS
endpoint on the home network — port-forwarding/tunnel, TLS, an always-up listener — heavy
surface for a single-user tool, buying only ~10 minutes of latency. Polling is nearly free
here because sync is already idempotent-cheap: an all-current tick costs **one** listing
call (~96 calls/day at 15 min vs the 5 000/day budget), skips never download, and originals
re-analyse from the immutable FIT cache. The rolling window also does two jobs webhooks
wouldn't: it **finalizes provisionals** as ERA5 catches up (ADR-0012) and catches late
COROS uploads.

**Resilience:** each tick is failure-contained (network blips, rate limits → warn, retry
next tick); the loop never dies. `--ticks 1` degrades gracefully to a cron-compatible
single pass for anyone preferring OS scheduling.

**Known limit:** a provisional older than the window (e.g. the Pi was off for weeks) stays
provisional until a manual `pacelab sync` over that range — accepted; the window is a flag.
