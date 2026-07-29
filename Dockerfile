# PaceLab watch container (ADR-0013) — runs on HermiPi (arm64, C-4).
#
# Build contract: ADR-0015. uv.lock is the single source of truth for dependencies, every
# base image is digest-pinned, and the container runs as uid 1000 because /data is a bind
# mount on the Pi. Digests are bumped by hand — the tag in each trailing comment names the
# thing pinned, it is not a fallback the build can drift to.

# --- build stage: resolve the venv from the lockfile ---
# python:3.13-slim
FROM python:3.13-slim@sha256:6771159cd4fa5d9bba1258caf0b82e6b73458c694d178ad97c5e925c2d0e1a91 AS build

# The uv binary only — the build stage stays the same image as the runtime stage, so the
# venv is built against the interpreter that will run it. uv 0.11.33
COPY --from=ghcr.io/astral-sh/uv@sha256:77280f2f771df71f90786c314fe1bbc1e023feac652969bbf139c280babf2eb7 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Phase 1: dependencies only. This layer survives every edit under src/.
# --frozen fails the build if uv.lock has drifted from pyproject.toml, so drift surfaces
# in CI rather than on the Pi.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Phase 2: the project itself.
COPY src ./src
RUN uv sync --frozen --no-dev

# --- runtime stage: identical base, without uv ---
# python:3.13-slim
FROM python:3.13-slim@sha256:6771159cd4fa5d9bba1258caf0b82e6b73458c694d178ad97c5e925c2d0e1a91

# Raspberry Pi OS gives its first login account uid 1000, so the common case needs no host
# chown. compose.yaml carries an override for a host that differs.
RUN groupadd --gid 1000 pacelab \
 && useradd --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin pacelab

COPY --from=build --chown=1000:1000 /app /app
ENV PATH="/app/.venv/bin:$PATH"

USER 1000:1000

# All state (results db, weather + FIT caches) lives under /data — bind-mount a host
# directory there. Every write in src/ is a relative path under the working directory.
WORKDIR /data
ENTRYPOINT ["pacelab"]
CMD ["watch"]
