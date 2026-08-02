# Runbook — HermiPi deployment

What runs where, how to change it, and what to look at when it misbehaves. Brought up in
issue #16; the decisions behind it are ADR-0013 (poll, not push), ADR-0015 (build
contract), ADR-0017 (health), ADR-0018 (snapshots) and ADR-0019 (unattended updates).

## Layout

    host                                            container
    /home/hermi/docker/pacelab/compose.yaml         —
    /home/hermi/docker/pacelab/.env                 (env_file; mode 600)
    /home/hermi/docker/pacelab/pacelab-update.sh    —  (hourly, from hermi's crontab)
    /home/hermi/docker/pacelab/update.log           —  (only grows when an update lands)
    /home/hermi/docker/pacelab/data/                /data
    /home/hermi/docker/pacelab/data/pacelab.db      /data/pacelab.db
    /home/hermi/docker/pacelab/data/.cache/         /data/.cache/
    /home/hermi/docker/pacelab/data/snapshots/      /data/snapshots/

`hermi` is uid/gid 1000, which is what the image runs as (ADR-0015), so nothing here needs
a `chown`. Nothing needs `sudo` either — `hermi` is in the `docker` group.

The Pi is a **live Home Assistant box** first (HA, Matter, OTBR, all bare `docker run`).
PaceLab is the only compose project on it. Anything you run here must stay inside its own
blast radius — see the prune note in ADR-0019.

## Everyday commands

All from `~/docker/pacelab`:

    docker compose ps                       # is it up, and does the probe say healthy?
    docker compose logs -f                  # the loop's running commentary
    docker compose exec pacelab pacelab health
    docker compose exec pacelab pacelab trend | tail
    docker compose exec pacelab pacelab calibrate      # report only, on demand
    docker compose exec pacelab pacelab snapshot       # by hand, e.g. after curating

`health` exits 0/1 and is what the compose `HEALTHCHECK` runs every 5 minutes: unhealthy
means no *successful* tick within 3 × the loop's interval (45 min at the default cadence).
Nothing acts on that automatically — `restart: unless-stopped` does not restart unhealthy
containers. It colours `docker compose ps` and gives a future notifier something to read.

## Updates

Hourly, at :17, from `hermi`'s crontab — `pacelab-update.sh` pulls `:latest` and re-ups only
if the digest moved (ADR-0019). This line **is** the mechanism, and a crontab lives on the
Pi rather than in this repo, so it is written down here and nowhere else — install it with
`crontab -e` (no `sudo`; it belongs to `hermi`):

    # PaceLab: follow :latest from GHCR (ADR-0019). Quiet unless something changed.
    17 * * * * /home/hermi/docker/pacelab/pacelab-update.sh >> /home/hermi/docker/pacelab/update.log 2>&1

That redirect is also the only thing that creates `update.log` — the script itself just
writes to stdout. It prints nothing when nothing changed, so:

    cat update.log        # empty, or one entry per update that actually landed

To force one now: `~/docker/pacelab/pacelab-update.sh`. To stop updates: `crontab -e` and
comment the line out.

**Rolling back.** CI publishes an immutable `:<sha>` tag alongside `:latest` for exactly
this. Pin it, re-up, and comment out the cron line so the next hour does not undo you:

    # in compose.yaml
    image: ghcr.io/hermanno3005/pacelab:<full-40-char-sha>

**Changing compose.yaml or the updater** means copying the file up — this repo is not
checked out on the Pi. From a clone:

    scp compose.yaml deploy/pacelab-update.sh hermi@192.168.1.104:docker/pacelab/
    ssh hermi@192.168.1.104 'chmod +x docker/pacelab/pacelab-update.sh && cd docker/pacelab && docker compose up -d'

## Seeding a corpus from scratch

Only needed on a rebuild — the corpus is curated and deliberately not re-derived (map
decision 2). From a laptop clone holding the good `pacelab.db`:

    ssh hermi@192.168.1.104 'mkdir -p ~/docker/pacelab/data'
    scp compose.yaml deploy/pacelab-update.sh .env hermi@192.168.1.104:docker/pacelab/
    rsync -a pacelab.db .cache hermi@192.168.1.104:docker/pacelab/data/

**Run `pacelab recompute` on the laptop first.** ADR-0016's pass fires on the Pi's very
first tick, and a corpus seeded mid-bump means the Pi's first act is rewriting rows and
republishing annotations over SSH, against the only copy, on the aged SD card. Settle it
where a failure is debuggable. (Skipped at bring-up, which is why that first tick found
three stale activities and took a snapshot instead of being the intended no-op. It worked
— but that is the thing this step exists to avoid.)

Then check the Pi reads back exactly what you sent, *before* starting the loop. Counts, not
vibes — a wrong bind-mount path shows up as an empty or unexpectedly small corpus, and a
cache the container cannot see shows up as a cache-miss storm on the first tick:

    docker compose run --rm --entrypoint python pacelab -c "
    import sqlite3; c = sqlite3.connect('/data/pacelab.db')
    print('activities', c.execute('select count(*) from activities').fetchone()[0])
    print('segments  ', c.execute('select count(*) from segments').fetchone()[0])
    print('versions  ', c.execute('select model_version, count(*) from activities group by 1').fetchall())"

    find data/.cache/weather -type f | wc -l      # ~190; must be non-zero, or ERA5 gets re-fetched
    find data/.cache/activities -type f | wc -l   # ~154 FITs, nested under intervals-<athlete>/

At bring-up (2026-08-02) that read **64 activities / 5752 segments**, all at `0.2.1`. The
curated seed was 55 / 5041 — the difference is real activities synced since curation, not a
seeding fault. Compare against the laptop you copied from, not against these numbers.

    docker compose run --rm pacelab watch --ticks 1     # one pass, in the foreground
    docker compose up -d

`--ticks 1` is worth the extra minute: it runs a complete pass with the output in front of
you instead of into `docker logs`, and a corpus that landed wrong shows up immediately.
Finally, install the cron line above — a deployment without it runs but never updates.

## When something looks wrong

**`no-weather` on recent activities is not a fault.** ERA5 publishes about a week behind
(ADR-0012), so the recompute pass skips anything still inside the lag and the sync tier
analyses it provisionally instead. It resolves itself as the archive catches up.

**Occasional `tick failed (URLError … handshake operation timed out)`.** Measured at bring-up:
roughly **1 in 20** TLS handshakes from this Pi to open-meteo stalls for the full 30 s
timeout, and one failure aborts the whole tick. It is the network path, not the code — MTUs
are 1500 end to end and `curl` from the same container succeeds in 0.1 s. There is no retry
at the fetch boundary yet (issue #31).

It is self-limiting rather than harmless: archive responses are disk-cached, so a tick's
successful fetches persist and only the *uncacheable* calls repeat — empty ERA5-lag days,
and the forecast tier, which is never cached by design. Those shrink to near zero as
provisional activities finalize, so a settled corpus makes very few calls per tick. Ticks
are idempotent and the next one retries, so the visible cost is an annotation landing in
~30 min instead of ~15.

Worry when it is *consecutive*: `pacelab health` reports the streak, and three in a row
(45 min) is what flips the probe unhealthy.

**A tick that dies rather than logs.** Only a failed snapshot does this by design
(ADR-0018) — the corpus is untouched and the loop sleeps and retries. Check disk first:

    df -h /home && du -sh ~/docker/pacelab/data/*

**Credentials.** `pacelab health` reads an unkeyed heartbeat row on purpose, so it still
reports on a corpus whose API key has expired instead of failing to resolve an account. An
expired key looks like ticks failing consecutively with an HTTP 401/403 in the log.
