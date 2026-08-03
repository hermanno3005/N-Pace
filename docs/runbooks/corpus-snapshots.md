# Runbook — corpus snapshots: pull, restore, verify

The corpus is `pacelab.db` (curated by hand, irreplaceable) plus `.cache/weather/` (pinned
to a model, so a re-fetch is not guaranteed identical). Together ~1.8 MB. The FIT cache is
**not** backed up — intervals.icu holds the authoritative copy. See ADR-0018 for why.

Paths below assume the Pi's bind mount:

    host       /home/hermi/docker/pacelab/data/
    container  /data/

The bind mount is live as of #16, so `scp` reaches the snapshots directly — no
`docker compose cp` hop needed.

## What writes a snapshot

Automatically, inside the watch loop: a recompute pass snapshots immediately before the first
row it **rewrites at a new `model_version`**. Nothing else does — not an ordinary tick, not a
publish retry, not a provisional finalizing, and not a pass that only *finds* stale rows and
then skips them all `no-weather` (which is what the days after a bump look like, #37).

By hand, whenever you want one — in particular **after curating the corpus** (deleting rows,
editing types), because curation between version bumps is the one thing the automatic
trigger does not capture:

    docker compose exec pacelab pacelab snapshot

It prints the archive it wrote and its size, prunes, and repoints `snapshots/latest.tar.gz`.
If it fails, it says so and exits non-zero — a failed snapshot is never reported as a success.

Archives are named `<UTC stamp>-<model_version>.tar.gz` for the version the corpus was at when
they were taken. Pruning keeps the last 10 archives **plus** the newest archive of each of the
last 5 versions — so the state before a bump survives however many snapshots follow it. To find
the corpus as it last stood at 0.2.1, take the newest `*-0.2.1.tar.gz`.

## Pull one off the Pi

There is no automatic off-Pi copy (ADR-0018, stated as an accepted limitation). Between
pulls the SD card holds the only copy, so pull after any bump you care about:

    scp hermi@192.168.1.104:/home/hermi/docker/pacelab/data/snapshots/latest.tar.gz .

## Restore

Stop the container first. Restoring under a running watch loop races a live writer, and the
loop will happily rewrite what you just restored.

    docker compose stop pacelab
    tar -xzf latest.tar.gz -C /home/hermi/docker/pacelab/data/
    docker compose start pacelab

Three things to check, because they are the boring parts that actually bite:

1. **Ownership.** The container runs as uid 1000 (ADR-0015). If you extracted as another
   user, `chown -R 1000:1000 /home/hermi/docker/pacelab/data/` before starting.
2. **Landing place.** The archive's members are `pacelab.db` and `.cache/weather/…`,
   relative to the data root — so `-C` must be the directory the bind mount points at, not
   the snapshots directory.
3. **The loop was stopped**, not just idle.

Then confirm the corpus came back:

    docker compose start pacelab
    docker compose exec pacelab pacelab trend | tail -5

A restored corpus will re-publish annotations for any row whose stored version is behind
the running image's `model_version` — that is the recompute pass doing its job, not a fault.

## If a snapshot fails

The watch loop treats it as a failed tick: the recompute does **not** run, the corpus is
left untouched at the old version, and the next tick retries (ADR-0018). Nothing is lost by
stopping; progress halts, state does not corrupt.

It is a failed tick in the heartbeat's sense too (ADR-0017), so it surfaces without anyone
reading logs: the container goes unhealthy in `docker ps` once no tick has succeeded for
3× the configured `--interval` (45 minutes at the default 900s), and this names the error
that did it —

    docker compose exec pacelab pacelab health

The two failures worth expecting:

- **`no space left on device`** — check `df -h /`. Snapshots are bounded at 15 (~10 MB), so the
  culprit is usually the FIT cache or Home Assistant's own recorder, not this.
- **`copied database failed integrity_check` / row-count mismatch** — the *source* db is
  damaged. Do not overwrite the latest good snapshot by re-running by hand; restore from
  `snapshots/latest.tar.gz` using the procedure above.
