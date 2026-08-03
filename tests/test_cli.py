"""CLI surface for the reconciliation pass (ADR-0016) and the health command (ADR-0017)."""

import logging
import time

import pytest

from pacelab.analyze import ActivityResult, SegmentResult
from pacelab.cli import main
from pacelab.config import Config
from pacelab.store import ResultStore

ACCOUNT = "intervals-i399426"


@pytest.fixture(autouse=True)
def _account(monkeypatch):
    monkeypatch.setenv("INTERVALS_API_KEY", "test-key")
    monkeypatch.setenv("INTERVALS_ATHLETE_ID", "i399426")


def _result(start_time):
    seg = SegmentResult(0, 100.0, 0.0, 30.0, 12.0, 55.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                        300.0, 298.0, False, None, 140.0)
    return ActivityResult(observed_pace=300.0, np_pace=298.0, cost_grade=2.0, cost_heat=1.0,
                          cost_wind=0.0, distance_m=100.0, segments=[seg],
                          start_time=start_time)


def test_calibrate_shouts_when_the_corpus_spans_model_versions(tmp_path, capsys):
    # A pipeline bump genuinely invalidates the fit, so a mixed corpus must never be
    # silent — but calibrate still fits (a coefficient bump is provably harmless).
    db = tmp_path / "pacelab.db"
    store = ResultStore(db)
    store.save("i1", _result(1.0), Config().model_version, account_id=ACCOUNT)
    store.save("i2", _result(2.0), "0.2.0", account_id=ACCOUNT)

    assert main(["calibrate", "--db", str(db)]) == 0

    out = capsys.readouterr().out
    assert "0.2.0 (1)" in out and f"{Config().model_version} (1)" in out
    assert "MIXED MODEL VERSIONS" in out
    assert "pacelab recompute" in out
    assert "report only" in out  # still fits


def test_calibrate_states_the_single_version_quietly(tmp_path, capsys):
    db = tmp_path / "pacelab.db"
    store = ResultStore(db)
    store.save("i1", _result(1.0), Config().model_version, account_id=ACCOUNT)

    assert main(["calibrate", "--db", str(db)]) == 0

    out = capsys.readouterr().out
    assert f"model version {Config().model_version}" in out
    assert "MIXED" not in out


def test_calibrate_compares_fits_against_the_configured_coefficient(tmp_path, capsys):
    # Once calibration has moved a coefficient off its ported default, "keeping default
    # 0.0007" is a lie: an abstention keeps whatever config carries, which is now 0.0001.
    db = tmp_path / "pacelab.db"
    ResultStore(db).save("i1", _result(1.0), Config().model_version, account_id=ACCOUNT)

    assert main(["calibrate", "--db", str(db)]) == 0

    out = capsys.readouterr().out
    assert str(Config().wbgt_a) in out
    assert "0.0007" not in out


def test_recompute_command_runs_the_pass(tmp_path, capsys, monkeypatch):
    calls = {}

    def fake_recompute(provider, service, store, config, account_id, force=False,
                       before_rewrite=None):
        calls["account_id"] = account_id
        calls["force"] = force
        return [("i1", "ok"), ("i2", "publish-failed")]

    monkeypatch.setattr("pacelab.cli.recompute", fake_recompute)

    assert main(["recompute", "--db", str(tmp_path / "pacelab.db"),
                 "--cache-dir", str(tmp_path)]) == 0

    out = capsys.readouterr().out
    assert calls == {"account_id": ACCOUNT, "force": False}
    assert "i1" in out and "publish-failed" in out
    assert "recomputed 1 / 2" in out


def test_recompute_force_walks_the_whole_corpus(tmp_path, monkeypatch):
    seen = {}

    def fake_recompute(*args, force=False, **kwargs):
        seen["force"] = force
        return []

    monkeypatch.setattr("pacelab.cli.recompute", fake_recompute)

    assert main(["recompute", "--force", "--db", str(tmp_path / "pacelab.db"),
                 "--cache-dir", str(tmp_path)]) == 0
    assert seen["force"] is True


def test_a_settled_corpus_prints_nothing(tmp_path, capsys, monkeypatch):
    # The pass runs every 15 minutes forever; when there is no drift it must go quiet.
    monkeypatch.setattr("pacelab.cli.recompute", lambda *a, **kw: [])

    assert main(["recompute", "--db", str(tmp_path / "pacelab.db"),
                 "--cache-dir", str(tmp_path)]) == 0
    assert capsys.readouterr().out == ""


def test_watch_recomputes_unless_told_not_to(tmp_path, monkeypatch):
    passed = {}

    def fake_watch(sync_fn, interval_s, window_days, ticks, recompute_fn=None,
                   record_fn=None):
        passed["recompute_fn"] = recompute_fn

    monkeypatch.setattr("pacelab.watch.watch", fake_watch)
    argv = ["watch", "--ticks", "1", "--db", str(tmp_path / "pacelab.db"),
            "--cache-dir", str(tmp_path)]

    assert main(argv) == 0
    assert passed["recompute_fn"] is not None

    assert main([*argv, "--no-recompute"]) == 0
    assert passed["recompute_fn"] is None


def test_snapshot_command_writes_a_verified_archive(tmp_path, capsys):
    # The manual half of ADR-0018: run it by hand after curating, since curation between
    # bumps is exactly what the automatic trigger does not capture.
    db = tmp_path / "pacelab.db"
    store = ResultStore(db)
    store.save("i1", _result(1.0), Config().model_version, account_id=ACCOUNT)
    weather = tmp_path / ".cache" / "weather"
    weather.mkdir(parents=True)
    (weather / "48.0_9.0_2026-07-04.json").write_text("[]")

    assert main(["snapshot", "--db", str(db), "--cache-dir", str(tmp_path / ".cache"),
                 "--snapshots-dir", str(tmp_path / "snapshots")]) == 0

    archives = list((tmp_path / "snapshots").glob("*.tar.gz"))
    assert len(archives) == 2  # the stamped archive plus the latest.tar.gz symlink
    assert "snapshot" in capsys.readouterr().out


def test_a_failed_snapshot_is_a_failed_command(tmp_path, capsys):
    # Reporting success for a backup that was never written is the worst outcome here.
    assert main(["snapshot", "--db", str(tmp_path / "absent.db"),
                 "--cache-dir", str(tmp_path / ".cache"),
                 "--snapshots-dir", str(tmp_path / "snapshots")]) == 1
    assert "absent.db" in capsys.readouterr().err


def test_the_recompute_pass_is_handed_a_snapshot_to_take(tmp_path, monkeypatch):
    # The wiring ADR-0018 asks for: the trigger lives inside the pass, so both the watch
    # loop and a manual `pacelab recompute` are protected by the same code path.
    seen = {}

    def fake_recompute(*args, force=False, before_rewrite=None, **kwargs):
        seen["before_rewrite"] = before_rewrite
        return []

    monkeypatch.setattr("pacelab.cli.recompute", fake_recompute)
    assert main(["recompute", "--db", str(tmp_path / "pacelab.db"),
                 "--cache-dir", str(tmp_path),
                 "--snapshots-dir", str(tmp_path / "snapshots")]) == 0

    db = tmp_path / "pacelab.db"
    ResultStore(db).save("i1", _result(1.0), Config().model_version, account_id=ACCOUNT)
    seen["before_rewrite"]()  # what the pass calls before it rewrites the first row

    assert list((tmp_path / "snapshots").glob("*.tar.gz"))


def test_a_failed_snapshot_fails_the_recompute_command(tmp_path, capsys, monkeypatch):
    # The manual half of "the recompute must not run": exit non-zero, say why, and say
    # plainly that nothing was recomputed.
    from pacelab.snapshot import SnapshotError

    def failing_snapshot(*args, **kwargs):
        raise SnapshotError("no space left on device")

    monkeypatch.setattr("pacelab.cli.write_snapshot", failing_snapshot)
    db = tmp_path / "pacelab.db"
    store = ResultStore(db)
    store.save("i1", _result(1.0), "0.2.0", account_id=ACCOUNT)  # stale: a bump to rewrite

    assert main(["recompute", "--db", str(db), "--cache-dir", str(tmp_path),
                 "--snapshots-dir", str(tmp_path / "snapshots")]) == 1

    err = capsys.readouterr().err
    assert "no space left on device" in err
    assert "nothing was recomputed" in err


# --- health and logging (ADR-0017) ---------------------------------------------------


def test_health_needs_no_account(tmp_path, capsys, monkeypatch):
    # The point of an unkeyed heartbeat: broken credentials are exactly the failure the
    # health command has to be able to report, so it must not resolve an account itself.
    monkeypatch.delenv("INTERVALS_API_KEY")
    monkeypatch.delenv("INTERVALS_ATHLETE_ID")
    db = tmp_path / "pacelab.db"
    ResultStore(db).record_tick(True, summary="3 listed, 1 ok, 2 skip", interval_s=900)

    assert main(["health", "--db", str(db)]) == 0
    assert "healthy" in capsys.readouterr().out


def test_health_exits_non_zero_on_a_stale_loop(tmp_path, capsys):
    # The exit code is the whole interface for the compose HEALTHCHECK.
    db = tmp_path / "pacelab.db"
    store = ResultStore(db)
    store.record_tick(True, summary="0 listed", interval_s=900, now=time.time() - 90_000)
    store.record_tick(False, error="RateLimited: 429", interval_s=900)

    assert main(["health", "--db", str(db)]) == 1

    out = capsys.readouterr().out
    assert "UNHEALTHY" in out
    assert "RateLimited: 429" in out


def test_health_on_a_loop_that_never_ran(tmp_path, capsys):
    assert main(["health", "--db", str(tmp_path / "pacelab.db")]) == 1
    assert "never" in capsys.readouterr().out


def test_watch_hands_tick_a_heartbeat_writer_bound_to_the_interval(tmp_path, monkeypatch):
    # The interval is recorded rather than assumed, so the staleness threshold tracks
    # whatever cadence this container was started with.
    passed = {}

    def fake_watch(sync_fn, interval_s, window_days, ticks, recompute_fn=None,
                   record_fn=None):
        passed["record_fn"] = record_fn

    monkeypatch.setattr("pacelab.watch.watch", fake_watch)
    db = tmp_path / "pacelab.db"

    assert main(["watch", "--ticks", "1", "--interval", "60", "--db", str(db),
                 "--cache-dir", str(tmp_path)]) == 0

    passed["record_fn"](True, summary="0 listed")
    assert ResultStore(db).read_heartbeat().interval_s == 60


def test_the_log_level_comes_from_the_environment(tmp_path, monkeypatch):
    # How the container is turned up: PACELAB_LOG_LEVEL in .env, no image rebuild.
    monkeypatch.setenv("PACELAB_LOG_LEVEL", "DEBUG")
    monkeypatch.setattr("pacelab.watch.watch", lambda *a, **kw: None)

    assert main(["watch", "--ticks", "1", "--db", str(tmp_path / "pacelab.db"),
                 "--cache-dir", str(tmp_path)]) == 0
    assert logging.getLogger().level == logging.DEBUG


def test_watch_collapses_a_synced_activity_to_one_log_line(tmp_path, capsys, caplog,
                                                           monkeypatch):
    # `_emit`'s eight-line block per activity is unreadable in `docker logs` at 96 ticks a
    # day; report commands keep it, the daemon does not.
    db = tmp_path / "pacelab.db"
    store = ResultStore(db)
    store.save("i1", _result(1.0), Config().model_version, account_id=ACCOUNT)
    monkeypatch.setattr("pacelab.cli.sync", lambda *a, **kw: [("i1", "ok"), ("i2", "skip")])

    def fake_watch(sync_fn, interval_s, window_days, ticks, recompute_fn=None,
                   record_fn=None):
        sync_fn("2026-06-23", "2026-07-07")

    monkeypatch.setattr("pacelab.watch.watch", fake_watch)
    with caplog.at_level(logging.INFO, logger="pacelab.cli"):
        assert main(["watch", "--ticks", "1", "--db", str(db),
                     "--cache-dir", str(tmp_path)]) == 0

    logged = [r.getMessage() for r in caplog.records]
    assert any("i1" in m and "NP" in m for m in logged)
    assert any("skip" in m and "i2" in m for m in logged)
    assert not any("Environmental cost" in m for m in logged)
    # The log handler writes to stdout too, so the check that matters is that nothing
    # bypassed it: no `_emit` block reached the terminal untimestamped.
    assert "Environmental cost" not in capsys.readouterr().out


def test_health_does_not_create_the_database_it_probes(tmp_path, capsys):
    # The probe runs every five minutes forever. Opening a ResultStore would create an
    # empty db under /data — state manufactured by the thing that only claims to read it.
    db = tmp_path / "pacelab.db"

    assert main(["health", "--db", str(db)]) == 1
    assert not db.exists()
