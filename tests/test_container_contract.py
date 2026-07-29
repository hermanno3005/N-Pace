"""The build-and-publish contract, asserted against the files that encode it.

ADR-0015 fixes what the image is allowed to do; issue #15 fixes when it may be published.
Both are unattended — the Pi always runs `:latest` — so the invariants are checked here
rather than left to review. A regression in either file is a bad build reaching an
always-on loop with nobody watching.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = (ROOT / "Dockerfile").read_text()
WORKFLOW_TEXT = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
WORKFLOW = yaml.safe_load(WORKFLOW_TEXT)
JOBS = WORKFLOW["jobs"]
COMPOSE = yaml.safe_load((ROOT / "compose.yaml").read_text())

# `FROM image@sha256:...` and `COPY --from=image@sha256:...` alike. A bare `COPY --from=build`
# names an earlier stage rather than a registry image, so it carries neither `/` nor `:`.
_IMAGE_REF = re.compile(r"^\s*(?:FROM|COPY\s+--from=)\s*(\S+)", re.MULTILINE)
IMAGE_REFS = [ref for ref in _IMAGE_REF.findall(DOCKERFILE) if "/" in ref or ":" in ref]


def _publish_step():
    return next(s for s in JOBS["image"]["steps"] if "build-push-action" in s.get("uses", ""))


def _needs(job):
    # `needs:` is a string when there is one dependency, a list when there are several.
    declared = JOBS[job]["needs"]
    return [declared] if isinstance(declared, str) else list(declared)


def test_every_base_image_is_digest_pinned():
    # ADR-0015: same commit, byte-identical image, forever. A floating tag lets a bad
    # point release reach the Pi.
    assert IMAGE_REFS, "no image references found in the Dockerfile"
    for ref in IMAGE_REFS:
        assert "@sha256:" in ref, f"{ref} is not digest-pinned"


def test_both_stages_share_one_base_digest():
    # ADR-0015: building the venv against one interpreter and running it against another
    # works today only because the deps are pure Python, and breaks silently when one isn't.
    python_stages = [ref for ref in IMAGE_REFS if ref.startswith("python:")]
    assert len(python_stages) == 2, "expected a build stage and a runtime stage"
    assert len({ref.split("@")[1] for ref in python_stages}) == 1


def test_the_image_is_built_from_python_and_uv_alone():
    # Anything else pinned in here is a third base nobody decided on.
    assert len({ref.split("@")[1] for ref in IMAGE_REFS}) == 2


def test_dependencies_come_from_the_lockfile_not_a_fresh_resolve():
    # ADR-0015: uv.lock is the single source of truth; --frozen fails the build on drift.
    assert "uv sync --frozen" in DOCKERFILE
    assert "pip install" not in DOCKERFILE
    assert "uv.lock" in DOCKERFILE, "the lockfile is never copied into the build"


def test_dependency_layer_is_installed_before_the_project():
    # Two-phase sync: editing src/ must not reinstall every dependency.
    deps_phase = DOCKERFILE.index("--no-install-project")
    assert deps_phase < DOCKERFILE.index("COPY src")


def test_the_container_runs_as_uid_1000():
    # ADR-0015: /data is a bind mount, so a root container leaves root-owned files on the Pi.
    assert re.search(r"^USER\s+1000(:1000)?\s*$", DOCKERFILE, re.MULTILINE)


def test_the_image_ships_no_healthcheck():
    # ADR-0015: Compose does not restart unhealthy containers, and a liveness probe is
    # green in the failure mode that matters. The probe belongs in compose.yaml.
    assert "HEALTHCHECK" not in DOCKERFILE


def test_data_is_a_bind_mount_not_a_named_volume():
    # ADR-0015 / map decision 1: the corpus stays an ordinary file sqlite3 and scp can reach.
    # Any host path will do — #16 picks the real one on the Pi — but a bare name is a
    # named volume, which is the thing being ruled out.
    service = COMPOSE["services"]["pacelab"]
    assert "volumes" not in COMPOSE, "a top-level volumes: block means a named volume"
    sources = [str(v).rsplit(":/data", 1)[0] for v in service["volumes"] if ":/data" in str(v)]
    assert sources, "nothing is mounted at /data"
    assert all(s.startswith((".", "/", "$")) for s in sources), f"{sources} is not a host path"
    # Not the directory holding this file: .env sits next to it, and /data is the one
    # place the container writes.
    assert all(s.rstrip("/") not in (".", "./") for s in sources), f"{sources} mounts .env"


def test_publication_is_downstream_of_green_tests():
    # Issue #15's hard requirement: a red test suite must never produce a pullable tag.
    # Asserted exactly — `needs: smoke-test` would satisfy a substring check while the
    # real gate was gone.
    assert _needs("image") == ["test"]


def test_only_main_publishes():
    # Every branch builds the image; only main pushes tags for it.
    push = _publish_step()["with"]["push"]
    assert "refs/heads/main" in push
    assert push != "true"


def test_the_image_job_builds_natively_on_arm64():
    # The Pi is arm64 (C-4); ubuntu-24.04-arm is free for public repos, so no QEMU.
    assert JOBS["image"]["runs-on"] == "ubuntu-24.04-arm"


def test_both_a_rolling_and_an_immutable_tag_are_published():
    # `:latest` is what the Pi follows; `:<sha>` is what "what is running?" and
    # "roll back to that one" are answered with.
    tags = _publish_step()["with"]["tags"].split("\n")
    assert "ghcr.io/hermanno3005/pacelab:latest" in tags
    assert "ghcr.io/hermanno3005/pacelab:${{ github.sha }}" in tags


def test_the_package_is_labelled_with_its_source_repo():
    # Without org.opencontainers.image.source, GHCR never links the package to this repo,
    # and the package the Pi is supposed to pull unauthenticated lands orphaned.
    labels = _publish_step()["with"]["labels"]
    assert "org.opencontainers.image.source=https://github.com/${{ github.repository }}" in labels


def test_the_test_job_runs_the_suite_from_the_lockfile():
    steps = str(JOBS["test"]["steps"])
    assert "--frozen" in steps
    assert "pytest" in steps


def test_the_image_job_may_write_packages_and_nothing_else():
    # The publish job uses the built-in GITHUB_TOKEN; keep its scope minimal.
    assert JOBS["image"]["permissions"] == {"contents": "read", "packages": "write"}
    assert WORKFLOW["permissions"] == {"contents": "read"}, "the default must stay read-only"


def test_a_publish_to_main_is_never_cancelled():
    # Cancelling one mid-push would leave `:latest` behind the newest green commit — and
    # `:latest` is what the Pi follows, unattended.
    assert "refs/heads/main" in str(WORKFLOW["concurrency"]["cancel-in-progress"])


def test_every_action_is_pinned_to_a_commit_sha():
    # A mutable tag on an action with packages: write is a supply-chain hole.
    uses = re.findall(r"uses:\s*(\S+)", WORKFLOW_TEXT)
    assert uses
    for ref in uses:
        assert re.search(r"@[0-9a-f]{40}$", ref), f"{ref} is not pinned to a commit sha"
