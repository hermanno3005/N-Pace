# Runbook — corpus snapshots: pull, restore, verify

The corpus is `pacelab.db` (curated by hand, irreplaceable) plus `.cache/weather/` (pinned
to a model, so a re-fetch is not guaranteed identical). Together ~1.8 MB. The FIT cache is
**not** backed up — intervals.icu holds the authoritative copy. See ADR-0018 for why.

Paths below assume the Pi's bind mount:

    host       /home/hermi/docker/pacelab/
    container  /data/

> `compose.yaml` in this repo still declares a named volume; the bind mount is part of
> ADR-0015's rewrite and has not landed yet. Until it does, `scp` cannot reach the
> snapshots directly — copy it out with
> `docker compose cp pacelab:/data/snapshots/latest.tar.gz .` first.

## What writes a snapshot

Automatically, inside the watch loop: a recompute pass that is about to **rewrite rows at a
new `model_version`** snapshots first. Nothing else does — not an ordinary tick, not a
publish retry, not a provisional finalizing.

By hand, whenever you want one — in particular **after curating the corpus** (deleting rows,
editing types), because curation between version bumps is the one thing the automatic
trigger does not capture:

    docker compose exec pacelab pacelab snapshot

It prints the archive it wrote and its size, keeps the last 10, and repoints
`snapshots/latest.tar.gz`. If it fails, it says so and exits non-zero — a failed snapshot is
never reported as a success.

## Pull one off the Pi

There is no automatic off-Pi copy (ADR-0018, stated as an accepted limitation). Between
pulls the SD card holds the only copy, so pull after any bump you care about:

    scp hermi@192.168.1.104:/home/hermi/docker/pacelab/snapshots/latest.tar.gz .

## Restore

Stop the container first. Restoring under a running watch loop races a live writer, and the
loop will happily rewrite what you just restored.

    docker compose stop pacelab
    tar -xzf latest.tar.gz -C /home/hermi/docker/pacelab/
    docker compose start pacelab

Three things to check, because they are the boring parts that actually bite:

1. **Ownership.** The container runs as uid 1000 (ADR-0015). If you extracted as another
   user, `chown -R 1000:1000 /home/hermi/docker/pacelab/` before starting.
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

The two failures worth expecting:

- **`no space left on device`** — check `df -h /`. Snapshots are bounded at 10, so the
  culprit is usually the FIT cache or Home Assistant's own recorder, not this.
- **`copied database failed integrity_check` / row-count mismatch** — the *source* db is
  damaged. Do not overwrite the latest good snapshot by re-running by hand; restore from
  `snapshots/latest.tar.gz` using the procedure above.
