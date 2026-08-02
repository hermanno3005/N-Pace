# The Pi follows :latest by cron, not by a supervising container

Map decision 5 asks for a fully automatic end-to-end path: CI publishes a gated image, the
Pi picks it up, a `model_version` bump recomputes the corpus and republishes every
annotation, with nobody watching. Issue #15 built the publishing half — `:latest` on GHCR,
public, arm64, strictly downstream of green tests. This ADR decides the receiving half:
what on the Pi notices a new digest and acts on it.

Everything downstream of the restart is already decided. ADR-0016's pass is store-driven
and runs on every tick, so a new image with a bumped `model_version` reconciles the corpus
by itself; ADR-0018 snapshots before it rewrites. The only question here is what pulls.

## The Pi is somebody's house first

This is the constraint that decides it. #11 found HermiPi is a live Home Assistant box —
HA, Matter, and OpenThread Border Router, all started with bare `docker run`, no compose
project of its own. PaceLab is a guest on hardware whose day job is running a home.

That rules out the obvious answer. **Watchtower** — the standard choice, a container that
polls the registry and recreates what it manages — needs `/var/run/docker.sock` bind-mounted
to do it. The docker socket is root-equivalent on the host: anything holding it can start a
privileged container and own the machine. Granting that to a long-lived third-party image,
permanently, on the box that also runs the smart home, to save a ten-line script, is not a
trade worth making. Scoping it by label limits what it *restarts*; it does not limit what
the socket can do.

**A systemd timer** is the better-engineered option and was the first choice — journald
handles the logging and the retention, `OnCalendar` handles the schedule, and a failed unit
is visible to `systemctl status` rather than to nobody. It was rejected on access, not
merit: a system unit needs `sudo`, and a `--user` unit needs `loginctl enable-linger` to
survive logout, which also needs `sudo`. #11 established that everything after it is AFK
precisely because `hermi` is in the `docker` group and needs no `sudo` — this would have
been the one thing to break that, permanently, for every future change to the schedule.

**So: `hermi`'s own crontab, hourly**, running `deploy/pacelab-update.sh`. No root, no new
daemon, no socket handed to anything, and the mechanism is editable by the same account
that already runs everything else. Hourly because CI only publishes on a push to main; the
gap between a merge and the Pi running it is not worth a tighter poll on an SD card.

## What the script has to get right

Cron is a hostile environment and the script is written for it: absolute paths throughout
(`/usr/bin/docker`, an absolute `-f` compose path — `docker compose -f` does not chdir),
`set -euo pipefail`, and a `flock -n` so a pull slower than the interval cannot have two
runs racing to recreate the same container.

**It is quiet unless something changed.** It captures the image id before the pull and
compares after; an unchanged digest exits 0 having printed nothing. This is what keeps its
log off the rotation problem ADR-0017 left open — a file that only grows when an update
actually lands grows a line a week, not a line an hour.

**Reclaiming the superseded image is by id, never by prune.** A superseded image loses its
tag, so it is indistinguishable by repository from any other dangling image on the host —
including Home Assistant's. `docker image prune` would collect those too. The id captured
before the pull is the only handle that names exactly this one image. It is not optional
housekeeping either: the SD card is from 2022, and a new image an hour would be the thing
that ends it.

**Restarting mid-tick is safe, by construction rather than by luck.** `up -d` recreates the
container whenever it likes, possibly mid-pass. The corpus is SQLite, so a killed write
rolls back, and ADR-0016 deliberately kept no resume state — every pass is driven by what
is stored, and `save()` clearing `published_version` *is* the crash-safety. There is no
in-memory progress a restart can lose. ADR-0013's failure-contained tick covers the rest.

## What this accepts

- **A bad green image reaches the Pi within the hour, unattended.** That is map decision 5
  as written, and the test gate is the only thing standing in front of it — which is why
  #15 made that gate the one invariant it asserts exactly. Rollback is manual and cheap:
  the `:<sha>` tags are published for this, so pinning `image:` to one and re-upping is the
  whole procedure.
- **A failed update is silent unless someone reads the log.** The container keeps running
  the old image, which is the safe failure, but nothing announces it. The heartbeat does
  not cover this: ADR-0017's predicate is about the loop succeeding, and a loop happily
  succeeding on last week's image is healthy by that definition and *is* healthy — just
  stale. Pairs with the push-notification upgrade the map already has in fog.
- **No staged rollout, because there is one host.** Nothing to stage against.
