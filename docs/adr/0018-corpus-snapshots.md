# The corpus snapshots itself before it rewrites itself

Once HermiPi owns `pacelab.db`, it holds the only copy of something expensive: 55 curated
activities, 5041 enriched segments, and every ERA5 response ever fetched. ADR-0016 then points
an unattended loop at it that, on a `model_version` bump, rewrites every row and republishes
55 public activity descriptions. Nothing backs any of it up, and `/home` is on an SD card
manufactured in 2022 that already carries Home Assistant's own SQLite recorder.

This ADR decides what is protected, how, and what happens when the protection fails.

## The corpus is three things, not one file

Measured, rather than assumed:

| | size | replaceable? |
|---|---|---|
| `pacelab.db` | 1.1 MB | **no** — curated by hand |
| `.cache/weather/` | 700 KB, 175 files | **not faithfully** |
| `.cache/activities/` | 12 MB, 144 FITs | yes, from intervals.icu |

The db is irreplaceable in its *curated* form. `55d2d99` filtered to runs, stripped
annotations and deleted non-run rows; a re-sync would faithfully bring every one of them back.
Curation is the one thing in the corpus that exists nowhere else and cannot be re-derived.

The weather cache is *nominally* re-fetchable, but ADR-0004 pins the model precisely so
results stay reproducible — a re-fetch is not guaranteed to return identical values, and
would burn API budget to find out. It is treated as precious.

The FIT cache is 87% of the bytes and is the one part with an authoritative copy elsewhere.
Losing it costs a slow re-download, not data.

**So the backup set is `pacelab.db` + `.cache/weather/` — about 1.8 MB.** That number decides
most of what follows: at 1.8 MB there is no incremental-versus-full question, no compression
economics, and no reason to keep fewer copies than is convenient.

## Snapshots stay on the Pi; going off-Pi is a manual pull

This is the deliberate limit of this ADR, chosen with its consequence understood.

Every automatic off-Pi option was rejected for the same reason: it depends on something that
isn't reliably there. Pushing to the laptop needs the laptop awake, which is precisely the
dependency this deployment exists to remove — the destination is "annotated with the laptop
closed". A scheduled pull from the laptop has the same defect and adds a scheduler nobody
wants running. A private git repo and cloud object storage both work, but each costs an
account and a credential on the Pi for a payload this small.

So: `pacelab snapshot` writes to the Pi's own disk, and the operator copies one file off when
they choose to:

    scp hermi@192.168.1.104:/home/hermi/docker/pacelab/snapshots/latest.tar.gz .

**What this protects against:** a bad recompute, a corrupt write, an accidental deletion — the
software failure modes, which are also the likely ones.

**What it does not protect against:** the SD card dying, or the Pi being lost, stolen or
dropped. Between pulls there is exactly one physical copy of the corpus.

That gap is real and is accepted for now, not overlooked. Closing it is an upgrade — an
`rclone` push to object storage is the obvious shape — and needs no change to anything here
beyond a second destination for a file that already exists.

## `pacelab snapshot`, not a host script

The Pi has no `sqlite3` CLI, and installing one needs `sudo`. A host shell script on `cron`
would also live outside the repo, so CI never tests it and it drifts silently from the schema
it copies.

A subcommand inside the image needs nothing installed, no `sudo` and no scheduler entry. It
versions with the image, it is covered by the test suite, and the red-suite gate that protects
every other pullable tag protects it too.

It costs one thing worth naming: a snapshot cannot run while the container is broken. The
trade is accepted because the trigger below is *inside* the loop anyway — a container too
broken to snapshot is also too broken to recompute, which is the event being guarded.

## One `.tar.gz` per snapshot, verified at write time

    /data/snapshots/2026-07-28T2015Z.tar.gz     # host: /home/hermi/docker/pacelab/snapshots/
    /data/snapshots/latest.tar.gz -> ...

The db is copied with Python's `sqlite3` backup API. A raw `cp` of a live SQLite file is not a
backup — it can capture a torn write mid-transaction and produce a file that opens cleanly and
is wrong. This is the one part of the mechanism where the obvious approach is silently
incorrect.

A single archive means the pull is one `scp` of one stable path, and a truncated copy is
obvious rather than plausible — the failure mode a directory-per-snapshot layout invites, where
a half-copied tree looks exactly like a whole one. Both the db and 175 JSON files compress hard,
so ~1.8 MB lands closer to a few hundred KB.

**Written snapshots are verified, not assumed.** The command reopens the copy it just made,
runs `PRAGMA integrity_check`, and asserts the activity and segment counts match the source. An
unverified backup is a hypothesis, and the moment to falsify it is at write time — not at 2am
on the day it is needed.

The last **10** are kept, oldest pruned at write time. Bounded, so this can never fill the card;
deep enough to walk back several bumps, which matters because a bad recompute is typically
noticed late, after further bumps have buried it.

## The trigger is a recompute that has work to do

ADR-0016's store-driven pass runs on every tick but almost always finds nothing. The snapshot
fires only when it finds rows to rewrite — that is, on a `model_version` bump.

This is rare, so every snapshot is meaningful and retention costs nothing, and it lands exactly
where the damage would be maximal: all 55 activities rewritten and all 55 public descriptions
republished, unattended.

Rejected: snapshotting every tick, which would write to the aged SD card 96 times a day to
capture nothing. Rejected: a daily timer, which mostly protects data intervals.icu already
holds — ordinary `sync` only *adds* replaceable rows.

The residual gap is hand-curation between bumps, which is not captured until the next bump.
Since curation is the irreplaceable part, the mitigation is procedural: run `pacelab snapshot`
by hand after curating. It is the same command.

## Snapshot failure fails the tick

If the snapshot cannot be written or does not verify, the exception propagates. ADR-0017's
handler logs it, `consecutive_failures` climbs, and health goes unhealthy after 3 × `interval_s`.
The recompute does not run. The corpus is left untouched at the old `model_version`, and the
next tick retries.

Nothing is lost by stopping — ADR-0016's pass is derived from the store, so a skipped pass is
indistinguishable from one that hasn't started yet. Progress halts; state does not corrupt.

Rejected: logging the failure and recomputing anyway. That removes the protection at the single
moment it was built for.

Rejected: skipping only the recompute while letting `sync` continue, reporting through
`last_tick_summary` in the `publish-failed` style. It keeps annotations flowing, but a Pi that
cannot write 1.8 MB is broken in a way that should be loud, and it muddies ADR-0017's clean
predicate that a successful tick is one that raised nothing.

## Restore is a runbook, not a command

    docker compose stop pacelab
    tar -xzf latest.tar.gz -C /home/hermi/docker/pacelab/
    docker compose start pacelab

A `pacelab restore` subcommand was rejected. Its entire job is to overwrite the live corpus —
a standing hazard that would exist for years and be used twice. The runbook does the same work
and carries no risk when nobody is restoring.

The procedure is rehearsed for real once, during the first version bump, because its untested
parts are the boring ones that bite: uid-1000 ownership, container-stopped sequencing, and
whether the extracted tree lands where the bind mount expects it.

## Surface

    pacelab snapshot          # write a verified snapshot, prune to the last 10
