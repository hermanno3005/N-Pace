"""Verified corpus snapshots (ADR-0018)."""

import sqlite3
import tarfile
import threading

import pytest

from pacelab.analyze import ActivityResult, SegmentResult
from pacelab.snapshot import SnapshotError, verify_copy, write_snapshot
from pacelab.store import ResultStore


def _result(np_pace=298.0):
    segs = [
        SegmentResult(i, 100.0, 0.01, 30.0, 12.0, 55.0, 1.0, 90.0, 0.01, 0.0, 0.0,
                      300.0, np_pace, False, None, 140.0)
        for i in range(3)
    ]
    return ActivityResult(observed_pace=300.0, np_pace=np_pace, cost_grade=2.0,
                          cost_heat=1.0, cost_wind=0.0, distance_m=300.0,
                          segments=segs, start_time=1.0)


def _corpus(root, n_activities=2):
    """A data directory shaped like the Pi's: pacelab.db + .cache/weather."""
    db = root / "pacelab.db"
    store = ResultStore(db)
    for i in range(n_activities):
        store.save(f"i{i}", _result(), "0.2.1", account_id="intervals-i1")
    weather = root / ".cache" / "weather"
    weather.mkdir(parents=True)
    (weather / "48.0_9.0_2026-07-04.json").write_text('[[0.0, 12.0, 55.0, 1.0, 90.0, 0, 1013.0, 0]]')
    return db, weather


def _snapshots(root):
    return root / "snapshots"


def test_a_snapshot_carries_the_db_and_the_weather_cache(tmp_path):
    # The backup set is the two irreplaceable parts (ADR-0018); the 12 MB FIT cache is
    # deliberately absent because intervals.icu holds the authoritative copy.
    db, weather = _corpus(tmp_path)
    (tmp_path / ".cache" / "activities").mkdir()
    (tmp_path / ".cache" / "activities" / "i0.fit").write_bytes(b"x" * 1000)

    archive = write_snapshot(db, weather, _snapshots(tmp_path))

    with tarfile.open(archive) as tar:
        names = tar.getnames()
    assert "pacelab.db" in names
    assert ".cache/weather/48.0_9.0_2026-07-04.json" in names
    assert not any("activities" in n for n in names)


def test_the_archive_extracts_straight_over_the_data_directory(tmp_path):
    # The restore runbook is `tar -xzf latest.tar.gz -C <data>`, so member paths must be
    # relative to the data root — not absolute, and not nested under a snapshot folder.
    db, weather = _corpus(tmp_path)
    archive = write_snapshot(db, weather, _snapshots(tmp_path))

    restored = tmp_path / "restored"
    restored.mkdir()
    with tarfile.open(archive) as tar:
        tar.extractall(restored, filter="data")

    assert (restored / "pacelab.db").exists()
    assert (restored / ".cache" / "weather" / "48.0_9.0_2026-07-04.json").exists()
    store = ResultStore(restored / "pacelab.db")
    assert store.activity_ids("intervals-i1") == ["i0", "i1"]
    assert store.load("i0", account_id="intervals-i1") == _result()


def test_a_snapshot_taken_mid_write_restores_to_a_consistent_corpus(tmp_path):
    # The reason for the sqlite3 backup API: a raw `cp` can capture a torn write and
    # produce a file that opens cleanly and is wrong. An uncommitted writer must leave
    # no trace in the copy, and the copy must still be internally consistent.
    db, weather = _corpus(tmp_path)
    writing = threading.Event()
    release = threading.Event()

    def half_written():
        conn = sqlite3.connect(db, isolation_level=None)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO activities VALUES "
                     "('intervals-i1','torn',1,1,1,1,1,1,'0.2.1',NULL,0,9)")
        writing.set()
        release.wait(5)
        conn.rollback()
        conn.close()

    writer = threading.Thread(target=half_written)
    writer.start()
    try:
        writing.wait(5)
        archive = write_snapshot(db, weather, _snapshots(tmp_path))
    finally:
        release.set()
        writer.join()

    restored = tmp_path / "restored"
    restored.mkdir()
    with tarfile.open(archive) as tar:
        tar.extractall(restored, filter="data")
    with sqlite3.connect(restored / "pacelab.db") as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        ids = [r[0] for r in conn.execute("SELECT activity_id FROM activities ORDER BY 1")]
    assert ids == ["i0", "i1"]  # the uncommitted row is not in the backup


def test_verification_rejects_a_corrupted_copy(tmp_path):
    # Without this the verification step is decoration: a snapshot nobody can restore
    # must fail at write time, not at 2am on the day it is needed.
    db, _ = _corpus(tmp_path)
    copy = tmp_path / "copy.db"
    copy.write_bytes(db.read_bytes())
    with copy.open("r+b") as f:
        f.seek(4096)  # scribble over page 2: the header still parses, the content doesn't
        f.write(b"\xff" * 2048)

    with pytest.raises(SnapshotError):
        verify_copy(copy, db)


def test_verification_rejects_a_copy_that_lost_rows(tmp_path):
    # Integrity alone is not enough — a structurally perfect db missing half the corpus
    # passes PRAGMA integrity_check and is still not a backup.
    db, _ = _corpus(tmp_path)
    copy = tmp_path / "copy.db"
    copy.write_bytes(db.read_bytes())
    with sqlite3.connect(copy) as conn:
        conn.execute("DELETE FROM segments WHERE activity_id = 'i0'")

    with pytest.raises(SnapshotError, match="segment"):
        verify_copy(copy, db)

    with sqlite3.connect(copy) as conn:
        conn.execute("DELETE FROM activities WHERE activity_id = 'i0'")
    with pytest.raises(SnapshotError, match="activit"):
        verify_copy(copy, db)


def test_a_verified_copy_passes(tmp_path):
    db, _ = _corpus(tmp_path)
    copy = tmp_path / "copy.db"
    copy.write_bytes(db.read_bytes())

    verify_copy(copy, db)  # no raise


def test_a_snapshot_that_fails_verification_leaves_nothing_behind(tmp_path, monkeypatch):
    # A failed snapshot must not leave a plausible-looking archive to be restored later.
    db, weather = _corpus(tmp_path)

    def truncating_copy(source, dest):
        dest.write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)

    monkeypatch.setattr("pacelab.snapshot._copy_db", truncating_copy)

    with pytest.raises(SnapshotError):
        write_snapshot(db, weather, _snapshots(tmp_path))

    assert list(_snapshots(tmp_path).glob("*.tar.gz")) == []


def test_pruning_keeps_the_last_ten_and_latest_follows(tmp_path):
    from datetime import datetime, timedelta, timezone

    db, weather = _corpus(tmp_path)
    start = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    written = [write_snapshot(db, weather, _snapshots(tmp_path), now=start + timedelta(hours=i))
               for i in range(12)]

    kept = sorted(p.name for p in _snapshots(tmp_path).glob("*.tar.gz")
                  if p.name != "latest.tar.gz")
    assert kept == sorted(p.name for p in written[2:])  # the two oldest are gone
    assert len(kept) == 10

    latest = _snapshots(tmp_path) / "latest.tar.gz"
    assert latest.is_symlink()
    assert latest.resolve() == written[-1].resolve()


def test_latest_is_relative_so_it_survives_being_moved(tmp_path):
    # The Pi's snapshots directory is a bind mount; an absolute symlink into the
    # container's /data would dangle on the host.
    db, weather = _corpus(tmp_path)
    write_snapshot(db, weather, _snapshots(tmp_path))

    import os
    target = os.readlink(_snapshots(tmp_path) / "latest.tar.gz")
    assert not os.path.isabs(target)


def test_a_missing_weather_cache_is_not_a_failure(tmp_path):
    # A fresh Pi has a db before it has ever fetched weather; that is still worth a
    # snapshot, and the db is the irreplaceable half.
    db, weather = _corpus(tmp_path)
    import shutil
    shutil.rmtree(weather)

    archive = write_snapshot(db, weather, _snapshots(tmp_path))

    with tarfile.open(archive) as tar:
        assert tar.getnames() == ["pacelab.db"]


def test_a_missing_database_fails_loudly(tmp_path):
    # Snapshotting nothing and reporting success is the worst possible outcome.
    with pytest.raises(SnapshotError):
        write_snapshot(tmp_path / "absent.db", tmp_path / "weather", _snapshots(tmp_path))
