"""Verified corpus snapshots (ADR-0018).

The corpus is two irreplaceable things — the curated `pacelab.db` and the pinned weather
cache, together ~1.8 MB. The FIT cache is 87% of the bytes and is deliberately excluded:
intervals.icu holds the authoritative copy, so losing it costs a re-download, not data.

Each snapshot is one `.tar.gz` whose members are relative to the data directory, so the
restore runbook is `tar -xzf latest.tar.gz -C <data>` and nothing else. It is named for the
`model_version` its corpus is stamped at — see ``_prune``, where that name is what makes
retention survive a trigger that fires more often than it should.

Two things here are load-bearing rather than incidental:

- The db is copied with the ``sqlite3`` backup API. A raw ``cp`` of a live SQLite file can
  capture a torn write and produce a file that opens cleanly and is wrong — the one place
  in this mechanism where the obvious approach is silently incorrect.
- The copy is **verified before the archive is written**: reopened, ``PRAGMA
  integrity_check``, and row counts asserted against the source. An unverified backup is a
  hypothesis, and write time is the moment to falsify it. A snapshot that fails
  verification raises; it never leaves a plausible-looking archive behind.
"""

import os
import re
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

KEEP = 10  # recency: the last few states, whatever produced them
KEEP_VERSIONS = 5  # depth: the corpus as it last stood at each of the last five versions
LATEST = "latest.tar.gz"

# `2026-08-03T051719Z-0.2.1.tar.gz` — a UTC stamp, then the corpus version it carries.
_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{6}Z(?:-(?P<version>.+))?\.tar\.gz$")
_UNSAFE = re.compile(r"[^A-Za-z0-9._]")


class SnapshotError(RuntimeError):
    """The snapshot could not be written or did not verify.

    Raised, not warned: a snapshot guards a rewrite of the whole corpus, so its failure
    fails the tick and the recompute does not run (ADR-0018).
    """


def write_snapshot(db_path: Path, weather_dir: Path, out_dir: Path,
                   keep: int = KEEP, keep_versions: int = KEEP_VERSIONS,
                   now: datetime | None = None) -> Path:
    """Write one verified snapshot to ``out_dir``, then prune (see ``_prune``).

    Returns the archive path. ``latest.tar.gz`` is repointed at it by a *relative* symlink,
    so the link still resolves on the Pi's host side of the bind mount.
    """
    db_path, weather_dir, out_dir = Path(db_path), Path(weather_dir), Path(out_dir)
    if not db_path.exists():
        raise SnapshotError(f"no database at {db_path} — nothing to snapshot")
    if keep < 1:
        raise SnapshotError(f"keep must be at least 1, got {keep} — "
                            "a snapshot that prunes itself is not a snapshot")
    out_dir.mkdir(parents=True, exist_ok=True)
    # Seconds, not just minutes: a hand-run snapshot straight after an automatic one is
    # the expected case (curate, then snapshot), and it must not silently replace it.
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H%M%SZ")
    version = _corpus_version(db_path)
    archive = out_dir / (f"{stamp}-{version}.tar.gz" if version else f"{stamp}.tar.gz")

    # Stage inside out_dir so the copy, the verification and the archive all land on one
    # filesystem, and so a crash mid-snapshot leaves a temp dir rather than a half archive.
    with tempfile.TemporaryDirectory(dir=out_dir, prefix=".staging-") as staging:
        copy = Path(staging) / db_path.name
        _copy_db(db_path, copy)
        verify_copy(copy, db_path)
        members = [(copy, db_path.name)]
        if weather_dir.is_dir():
            staged_weather = Path(staging) / weather_dir.name
            shutil.copytree(weather_dir, staged_weather)
            members.append((staged_weather, _member_name(weather_dir, db_path.parent)))
        _write_archive(archive, members)

    _prune(out_dir, keep, keep_versions)
    _point_latest(out_dir, archive)
    return archive


def verify_copy(copy_path: Path, source_path: Path) -> None:
    """Assert a copied database is intact and complete, or raise ``SnapshotError``.

    Integrity alone is not enough — a structurally perfect database missing half the
    corpus passes ``PRAGMA integrity_check`` and is still not a backup — so the activity
    and segment counts are compared against the source too.
    """
    try:
        with sqlite3.connect(copy_path) as conn:
            check = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if check != "ok":
                raise SnapshotError(f"copied database failed integrity_check: {check}")
            copied = _counts(conn)
    except sqlite3.DatabaseError as e:
        raise SnapshotError(f"copied database is unreadable: {e}") from e

    with sqlite3.connect(source_path) as conn:
        source = _counts(conn)
    for table, n_source in source.items():
        if copied[table] != n_source:
            raise SnapshotError(
                f"copied database has {copied[table]} {table[:-1]} rows, source has {n_source}"
            )


def _member_name(path: Path, data_root: Path) -> str:
    """Where ``path`` lands when the archive is extracted with ``-C <data root>``.

    The db defines the data root, since it is the one file whose location the restore
    must reproduce exactly. A weather cache kept somewhere else entirely still restores
    to the layout the running container expects, rather than to an absolute path or one
    escaping upwards with ``..``.
    """
    try:
        return str(path.resolve().relative_to(data_root.resolve()))
    except ValueError:
        return str(Path(".cache") / path.name)


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("activities", "segments")}


def _copy_db(source: Path, dest: Path) -> None:
    """Copy a live SQLite database consistently (never a filesystem copy — ADR-0018)."""
    src = sqlite3.connect(source)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    except sqlite3.DatabaseError as e:
        raise SnapshotError(f"could not copy {source}: {e}") from e
    finally:
        src.close()


def _write_archive(archive: Path, members: list[tuple[Path, str]]) -> None:
    try:
        with tarfile.open(archive, "w:gz") as tar:
            for path, arcname in members:
                tar.add(path, arcname=arcname)
    except OSError as e:
        archive.unlink(missing_ok=True)  # never leave a truncated archive to be restored
        raise SnapshotError(f"could not write {archive}: {e}") from e


def _snapshots(out_dir: Path) -> list[Path]:
    """Existing snapshots, oldest first. Names are UTC stamps, so name order is time order."""
    return sorted(p for p in out_dir.glob("*.tar.gz") if p.name != LATEST)


def _version_of(archive: Path) -> str | None:
    """The corpus ``model_version`` an archive carries, or None if its name predates it."""
    match = _NAME.match(archive.name)
    return match.group("version") if match else None


def _corpus_version(db_path: Path) -> str | None:
    """The model version most of the corpus is stamped at, or None if it has none.

    Most, not all: a snapshot is taken *before* a rewrite, so its corpus is whatever the
    last completed bump left — plus, straight after one, a handful of rows the archive's
    publication lag has not let through yet. The majority is what the archive is *of*.
    A bump only half-way through therefore still names the *old* version, which is what
    ``_prune`` relies on to tell it apart from the snapshot taken before the bump began.

    Unscoped by account, unlike everything in ``store``: the archive holds every account's
    rows, so its name has to describe all of them.
    """
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                # The tie-break is arbitrary but deterministic — versions sort as strings
                # here, which is not their order, and nothing downstream reads it as one.
                "SELECT model_version FROM activities WHERE model_version IS NOT NULL "
                "GROUP BY model_version ORDER BY COUNT(*) DESC, model_version DESC LIMIT 1"
            ).fetchone()
    except sqlite3.DatabaseError:
        return None  # an unreadable db still fails loudly in verification, not here
    return _UNSAFE.sub("_", row[0]) if row and row[0] else None


def _prune(out_dir: Path, keep: int, keep_versions: int) -> None:
    """Keep the last ``keep`` archives, plus the *first* archive of each recent version.

    The count alone made retention depend on the trigger being rare, and #37 showed what
    that costs: a trigger bug fired the guard every fifteen minutes and the pre-bump
    archive — the single snapshot the mechanism exists to produce — was evicted by the
    noise it had caused, inside three hours. Bounded at ``keep + keep_versions``, so it
    still cannot fill the card.

    **First**, not last, and the difference is the whole value of the slot. A snapshot is
    taken before a rewrite, so the first archive stamped version V holds the corpus as it
    stood before anything at V had been touched. A bump does not land in one pass — rows
    inside the archive's publication lag are rewritten over the following days, and each
    of those rewrites snapshots a half-bumped corpus that still counts as V. Giving the
    slot to the newest would hand it to one of those and evict the untouched one.

    It also makes the two rules complement rather than overlap: the version slot protects
    the old archive, which is exactly the one the recency count cannot.
    """
    archives = _snapshots(out_dir)  # oldest first
    survivors = set(archives[-keep:])  # keep >= 1 (checked before anything is written)
    first_at: dict[str | None, Path] = {}
    for archive in archives:
        first_at.setdefault(_version_of(archive), archive)
    if keep_versions > 0:  # name order is time order, so the last slots are the recent ones
        survivors.update(sorted(first_at.values())[-keep_versions:])
    for old in archives:
        if old not in survivors:
            old.unlink()


def _point_latest(out_dir: Path, archive: Path) -> None:
    link = out_dir / LATEST
    link.unlink(missing_ok=True)
    os.symlink(archive.name, link)  # relative: the pull is one stable path on either side
