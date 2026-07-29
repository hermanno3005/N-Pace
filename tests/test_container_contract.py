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
WORKFLOW = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
COMPOSE = yaml.safe_load((ROOT / "compose.yaml").read_text())

# `FROM image@sha256:...` and `COPY --from=image@sha256:...` alike.
_IMAGE_REF = re.compile(r"^\s*(?:FROM|COPY\s+--from=)\s*(\S+)", re.MULTILINE)


def _jobs():
    return WORKFLOW["jobs"]


def _publish_step():
    steps = _jobs()["image"]["steps"]
    return next(s for s in steps if "build-push-action" in s.get("uses", ""))


def test_every_base_image_is_digest_pinned():
    # ADR-0015: same commit, byte-identical image, forever. A floating tag lets a bad
    # point release reach the Pi.
    refs = [
        ref
        for ref in _IMAGE_REF.findall(DOCKERFILE)
        # `COPY --from=build` names an earlier stage, not a registry image.
        if "/" in ref or ":" in ref
    ]
    assert refs, "no image references found in the Dockerfile"
    for ref in refs:
        assert "@sha256:" in ref, f"{ref} is not digest-pinned"


def test_both_stages_share_one_base_digest():
    # ADR-0015: building the venv against one interpreter and running it against another
    # works today only because the deps are pure Python, and breaks silently when one isn't.
    digests = {ref.split("@")[1] for ref in _IMAGE_REF.findall(DOCKERFILE) if "@sha256:" in ref}
    python_stages = [ref for ref in _IMAGE_REF.findall(DOCKERFILE) if ref.startswith("python:")]
    assert len(python_stages) == 2, "expected a build stage and a runtime stage"
    assert len({ref.split("@")[1] for ref in python_stages}) == 1
    assert len(digests) == 2, "expected exactly two distinct images: python and uv"


def test_dependencies_come_from_the_lockfile_not_a_fresh_resolve():
    # ADR-0015: uv.lock is the single source of truth; --frozen fails the build on drift.
    assert "uv sync --frozen" in DOCKERFILE
    assert "pip install" not in DOCKERFILE
    assert "COPY uv.lock" in DOCKERFILE or "uv.lock ./" in DOCKERFILE


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
    service = COMPOSE["services"]["pacelab"]
    assert "volumes" not in COMPOSE, "a top-level volumes: block means a named volume"
    assert any(str(v).endswith(":/data") and str(v).startswith(".") for v in service["volumes"])


def test_publication_is_downstream_of_green_tests():
    # Issue #15's hard requirement: a red test suite must never produce a pullable tag.
    assert _jobs()["image"]["needs"] == "test" or "test" in _jobs()["image"]["needs"]


def test_only_main_publishes():
    # Every branch builds the image; only main pushes tags for it.
    push = _publish_step()["with"]["push"]
    assert "refs/heads/main" in push
    assert push != "true"


def test_the_image_job_builds_natively_on_arm64():
    # The Pi is arm64 (C-4); ubuntu-24.04-arm is free for public repos, so no QEMU.
    assert _jobs()["image"]["runs-on"] == "ubuntu-24.04-arm"


def test_both_a_rolling_and_an_immutable_tag_are_published():
    # `:latest` is what the Pi follows; `:<sha>` is what "what is running?" and
    # "roll back to that one" are answered with.
    tags = _publish_step()["with"]["tags"].split("\n")
    assert "ghcr.io/hermanno3005/pacelab:latest" in tags
    assert "ghcr.io/hermanno3005/pacelab:${{ github.sha }}" in tags


def test_the_test_job_runs_the_suite_from_the_lockfile():
    steps = str(_jobs()["test"]["steps"])
    assert "--frozen" in steps
    assert "pytest" in steps


def test_the_image_job_may_write_packages_and_nothing_else():
    # The publish job uses the built-in GITHUB_TOKEN; keep its scope minimal.
    assert _jobs()["image"]["permissions"] == {"contents": "read", "packages": "write"}


def test_every_action_is_pinned_to_a_commit_sha():
    # A mutable tag on an action with packages: write is a supply-chain hole.
    uses = re.findall(r"uses:\s*(\S+)", (ROOT / ".github" / "workflows" / "ci.yml").read_text())
    assert uses
    for ref in uses:
        assert re.search(r"@[0-9a-f]{40}$", ref), f"{ref} is not pinned to a commit sha"
