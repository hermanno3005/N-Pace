# The container image is lockfile-pinned, digest-pinned, and non-root

The `pacelab watch` container (ADR-0013) is about to be published automatically by CI to
GHCR, and the Pi will always run latest. That makes the image's build contract load-bearing:
whatever it does, it does unattended. This ADR fixes that contract before automation starts.

The container files landed in `d9ea6a4` but have **never been built** — Docker is not
installed on the athlete's laptop. They are a design sketch. This ADR is the contract they
must be rewritten against; the rewrite itself is CI's work, not this decision's.

## `uv.lock` is the single source of truth for dependencies

The sketch runs `pip install --no-cache-dir .`, which re-resolves from PyPI at build time and
**ignores `uv.lock` entirely** — so two builds of the same commit can ship different
`certifi`. NFR-3 requires reproducibility. Instead:

    uv sync --frozen --no-dev

run in two phases — dependencies from `pyproject.toml` + `uv.lock`, then the project from
`src`. `--frozen` fails the build if the lock has drifted from `pyproject.toml`, so drift
surfaces in CI rather than on the Pi.

Both the build and runtime stages use the **identical** `python:3.13-slim`, with the `uv`
binary copied in from `ghcr.io/astral-sh/uv`. Using a different base for the build stage
would build the venv against one interpreter and run it against another; the deps are pure
Python so it would work today, and break silently the moment one isn't. The app runs from
`/app/.venv` via `PATH`.

Rejected: exporting `uv.lock` to a `requirements.lock` and using `pip --require-hashes`. It
keeps `uv` out of the image, but adds a second generated file that can go stale against
`uv.lock` without anything noticing.

## Base images are digest-pinned

All three image references — both `python:3.13-slim` stages and `ghcr.io/astral-sh/uv` — are
pinned by sha256 digest, each with its human-readable tag in the comment line directly above
it — Dockerfiles have no trailing comments, `#` only starts one at the beginning of a line. A
manifest-list digest is still multi-arch, so arm64 resolution on the Pi is unaffected. Same
commit, byte-identical image, forever.

The cost is recorded honestly: this repo has no Renovate or Dependabot, so Debian and Python
patch updates land only when someone bumps the digest by hand. Accepted because the
alternative — floating tags — lets a bad point release reach an always-on loop with nobody
watching, and the deployment's exposure is outbound HTTPS to intervals.icu and ERA5 only.
**Who bumps the digests, and on what trigger,** belonged with the CI design rather than this
decision; it is settled below.

## The container runs as uid 1000, not root

`/data` is a **bind mount** to a Pi host path, not a named volume, so that the corpus stays
an ordinary file `sqlite3` and `scp` can reach. That makes file ownership a real consequence:
files a root container creates are root-owned on the Pi's filesystem.

The image therefore bakes a `pacelab` user at `1000:1000` and sets `USER`. Raspberry Pi OS
gives its first login account uid 1000, so the common case needs no host `chown`. `compose.yaml`
carries a commented `user: "${PUID}:${PGID}"` override for a host that differs; if the uid is
wrong the container fails loudly on first write rather than corrupting anything.

This is safe because **every write in `src/` is a relative path under the working directory** —
`pacelab.db` and `.cache/` — with no `$HOME`, no `/tmp`, and no `expanduser`. The non-root user
needs write access to exactly one place: `/data`.

## The image ships no `HEALTHCHECK`

Two reasons.

`restart: unless-stopped` reacts to a container *exiting*, not to it being `unhealthy` — Compose
does not restart unhealthy containers. A `HEALTHCHECK` with nothing consuming it colours
`docker ps` and does nothing else.

And a liveness-style probe is green in exactly the failure mode that matters. The watch loop is
deliberately built never to die (failures are contained per tick), so "the process is running"
carries almost no information; a hung or silently-failing loop looks perfectly healthy.

Instead the contract guarantees the image is **probe-ready**: Python with stdlib `sqlite3` on
`PATH`, state at a known location, and no additional packages required for any plausible probe.
The health surface — what the heartbeat is and what reads it — is designed separately, and the
probe belongs in `compose.yaml`, where its interval and predicate are tunable without
republishing the image.

## Who bumps the digests (settled by the CI design, #15)

By hand, in the Dockerfile, as an ordinary commit — no Renovate, no Dependabot, no scheduled
job that opens PRs against a single-user repo nobody is watching. The trigger is either
touching the image for another reason, or a Debian/Python advisory that actually reaches this
deployment's surface (outbound HTTPS to intervals.icu and ERA5).

The bump is safe to make blind because it goes through the same gate as everything else: CI
builds the image on every branch and PR, and only main publishes a tag. A digest that breaks
the build fails the PR rather than the Pi.

## Layer caching

The two-phase `uv sync` improves on the sketch rather than merely preserving it: editing
`src/pacelab/cli.py` reruns only the final sync, where `pip install .` reinstalled every
dependency. No BuildKit cache mount — the runtime dependency surface is two pure-Python
wheels (`certifi`, `fitdecode`), which does not justify a CI cache dependency.
