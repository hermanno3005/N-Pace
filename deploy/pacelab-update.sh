#!/usr/bin/env bash
# Follow :latest on the Pi, unattended (map decision 5, ADR-0019).
#
# Deployed to /home/hermi/docker/pacelab/pacelab-update.sh and run from hermi's crontab.
# Cron gives you almost no environment, so everything here is absolute and nothing is
# inherited: no PATH assumptions, no working directory, no shell profile.
#
# Quiet by design. A run that changes nothing prints nothing, so the log this appends to
# only ever grows when something actually happened — which is what keeps it off the
# rotation problem that ADR-0017 left open for the container's own logs.
set -euo pipefail

readonly DIR=/home/hermi/docker/pacelab
readonly COMPOSE=$DIR/compose.yaml
readonly IMAGE=ghcr.io/hermanno3005/pacelab:latest
readonly DOCKER=/usr/bin/docker

say() { echo "$(date -Is) $*"; }

# One updater at a time. A pull over a slow link can outlast the hour between runs, and
# two `up -d` calls racing to recreate the same container is how you end up with none.
# -n rather than a wait: if the previous run is still going, this one has nothing to add.
exec 9>"$DIR/.update.lock"
flock -n 9 || exit 0

before=$($DOCKER image inspect --format '{{.Id}}' "$IMAGE" 2>/dev/null || echo none)

if ! pull_output=$($DOCKER compose -f "$COMPOSE" pull --quiet 2>&1); then
  say "pull failed — staying on the running image"
  say "$pull_output"
  exit 1
fi

# Guarded the same way `before` is. The pull can legitimately succeed without leaving this
# tag behind: the documented rollback pins compose to a `:<sha>`, and then the pull fetches
# that instead and `:latest` may not be present at all. Unguarded, `set -e` would abort here
# with a raw docker error and no line in the log — the one failure this script would not
# narrate, in exactly the situation someone is already debugging something else.
after=$($DOCKER image inspect --format '{{.Id}}' "$IMAGE" 2>/dev/null || echo none)
if [ "$after" = none ]; then
  say "pulled, but $IMAGE is not present — compose is pinned elsewhere; leaving it alone"
  exit 0
fi
[ "$before" = "$after" ] && exit 0

say "new image ${after#sha256:}"

# Recreates the container against the image just pulled. A tick may be mid-flight: that is
# safe by construction, because the corpus is SQLite (a killed write rolls back) and
# ADR-0016 made every pass resumable from stored state alone — save() clearing
# published_version *is* the crash-safety, so there is no in-memory progress to lose.
if ! up_output=$($DOCKER compose -f "$COMPOSE" up -d 2>&1); then
  say "up -d failed after a successful pull — the old container may be stopped"
  say "$up_output"
  exit 1
fi
say "restarted on the new image"

# Reclaim the image just superseded, by the id captured before the pull. Deliberately not
# `docker image prune`, even filtered: the superseded image has lost its tag, so it is
# indistinguishable by repository from Home Assistant's dangling layers — and this Pi is
# that box first (#11). The id is the only handle that is exactly this one image. The SD
# card is from 2022, so reclaiming is not optional either.
[ "$before" = none ] || $DOCKER rmi "$before" >/dev/null 2>&1 || true
