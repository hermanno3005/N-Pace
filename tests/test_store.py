import sqlite3

from pacelab.analyze import ActivityResult, SegmentResult
from pacelab.store import ResultStore


def make_result():
    segs = [
        SegmentResult(0, 100.0, 0.05, 40.0, 12.0, 55.0, 3.0, 180.0, 0.02, 0.01, 0.0, 400.0, 390.0, False),
        SegmentResult(1, 100.0, -0.02, 30.0, 12.0, 55.0, 3.0, 180.0, -0.01, 0.01, 0.0, 300.0, 302.0, True),
    ]
    return ActivityResult(
        observed_pace=350.0, np_pace=346.0, cost_grade=5.0, cost_heat=3.0,
        cost_wind=-1.0, distance_m=200.0, segments=segs,
    )


def test_save_and_load_round_trip(tmp_path):
    store = ResultStore(tmp_path / "pacelab.db")
    store.save("act1", make_result(), model_version="0.1.0")
    assert store.load("act1") == make_result()


def test_is_current_tracks_the_model_version(tmp_path):
    store = ResultStore(tmp_path / "pacelab.db")
    store.save("act1", make_result(), model_version="0.1.0")
    assert store.is_current("act1", "0.1.0")
    assert not store.is_current("act1", "0.2.0")  # a re-tune must recompute (FR-10.2)
    assert not store.is_current("missing", "0.1.0")


def test_recompute_replaces_rather_than_duplicates(tmp_path):
    store = ResultStore(tmp_path / "pacelab.db")
    store.save("act1", make_result(), model_version="0.1.0")
    store.save("act1", make_result(), model_version="0.2.0")
    loaded = store.load("act1")
    assert len(loaded.segments) == 2  # not 4
    assert store.is_current("act1", "0.2.0")


V01_SCHEMA = """
CREATE TABLE activities (
    activity_id   TEXT PRIMARY KEY,
    distance_m    REAL, observed_pace REAL, np_pace REAL,
    cost_grade    REAL, cost_heat REAL, cost_wind REAL,
    model_version TEXT
);
CREATE TABLE segments (
    activity_id TEXT, idx INTEGER, distance REAL, grade REAL, elapsed REAL,
    temperature_c REAL, humidity_pct REAL, wind_speed_ms REAL, wind_dir_deg REAL,
    p_grade REAL, p_heat REAL, p_wind REAL, pace_obs REAL, pace_np REAL,
    stopped INTEGER,
    PRIMARY KEY (activity_id, idx)
);
"""


def test_opening_a_v01_database_migrates_it(tmp_path):
    # A pre-account-id (v0.1) database must not crash the store (regression: it did,
    # with "no such column: account_id"). Old rows migrate under the "local" account.
    import sqlite3

    db = tmp_path / "pacelab.db"
    conn = sqlite3.connect(db)
    conn.executescript(V01_SCHEMA)
    conn.execute("INSERT INTO activities VALUES ('old1', 5000.0, 300.0, 295.0, 3.0, 2.0, 0.0, '0.1.0')")
    conn.execute(
        "INSERT INTO segments VALUES ('old1', 0, 100.0, 0.01, 30.0, 12.0, 55.0, 2.0, 180.0,"
        " 0.005, 0.01, 0.0, 300.0, 295.0, 0)"
    )
    conn.commit()
    conn.close()

    store = ResultStore(db)  # must not raise
    migrated = store.load("old1")  # old rows land under the default "local" account
    assert migrated is not None
    assert migrated.np_pace == 295.0
    assert len(migrated.segments) == 1
    assert migrated.segments[0].solar_radiation_wm2 is None  # column didn't exist in v0.1
    assert store.is_current("old1", "0.1.0")
    # And the store is fully writable post-migration.
    store.save("new1", make_result(), model_version="0.2.0")
    assert store.load("new1") == make_result()


def test_segment_heart_rate_round_trips(tmp_path):
    store = ResultStore(tmp_path / "pacelab.db")
    seg = SegmentResult(0, 100.0, 0.0, 30.0, 20.0, 50.0, 2.0, 180.0, 0.0, 0.01, 0.0,
                        300.0, 297.0, False, 650.0, avg_hr=152.5)
    result = ActivityResult(300.0, 297.0, 0.0, 3.0, 0.0, 100.0, [seg])
    store.save("hr", result, model_version="0.2.0")
    assert store.load("hr").segments[0].avg_hr == 152.5


def test_segment_solar_radiation_round_trips(tmp_path):
    # Per-segment solar is persisted (ADR-0006: per-segment conditions); NULL marks the
    # Heat Index fallback (ADR-0010's confidence tag).
    store = ResultStore(tmp_path / "pacelab.db")
    seg = SegmentResult(0, 100.0, 0.0, 30.0, 20.0, 50.0, 2.0, 180.0, 0.0, 0.01, 0.0,
                        300.0, 297.0, False, solar_radiation_wm2=650.0)
    result = ActivityResult(300.0, 297.0, 0.0, 3.0, 0.0, 100.0, [seg])
    store.save("sunny", result, model_version="0.2.0")
    assert store.load("sunny").segments[0].solar_radiation_wm2 == 650.0


def test_provisional_flag_round_trips_and_clears_on_final_save(tmp_path):
    # A forecast-tier analysis is stored provisional; the ERA5 recompute overwrites it
    # as final (ADR-0012).
    store = ResultStore(tmp_path / "pacelab.db")
    store.save("act1", make_result(), model_version="0.2.0", account_id="acct", provisional=True)
    assert store.is_provisional("act1", account_id="acct")

    store.save("act1", make_result(), model_version="0.2.0", account_id="acct")
    assert not store.is_provisional("act1", account_id="acct")
    assert not store.is_provisional("ghost", account_id="acct")  # unknown → not provisional


def test_delete_removes_activity_and_segment_rows(tmp_path):
    store = ResultStore(tmp_path / "pacelab.db")
    store.save("act1", make_result(), model_version="0.2.0", account_id="acct")

    store.delete("act1", account_id="acct")

    assert store.load("act1", account_id="acct") is None
    assert not store.is_current("act1", "0.2.0", account_id="acct")


def test_publish_state_tracks_the_model_version(tmp_path):
    # An activity needs publishing until marked; a recompute (save) resets the mark so
    # sync republishes exactly when it reanalyses (ADR-0011).
    store = ResultStore(tmp_path / "pacelab.db")
    store.save("act1", make_result(), model_version="0.2.0", account_id="acct")
    assert store.needs_publish("act1", "0.2.0", account_id="acct")

    store.mark_published("act1", "0.2.0", account_id="acct")
    assert not store.needs_publish("act1", "0.2.0", account_id="acct")

    store.save("act1", make_result(), model_version="0.3.0", account_id="acct")  # recompute
    assert store.needs_publish("act1", "0.3.0", account_id="acct")


def test_unknown_activity_does_not_need_publish(tmp_path):
    # Nothing analysed → nothing to annotate.
    store = ResultStore(tmp_path / "pacelab.db")
    assert not store.needs_publish("ghost", "0.2.0", account_id="acct")


def test_v02_database_without_publish_column_migrates(tmp_path):
    # A db created before the published_version column must gain it transparently.
    import sqlite3

    store = ResultStore(tmp_path / "pacelab.db")
    store.save("act1", make_result(), model_version="0.2.0", account_id="acct")
    conn = sqlite3.connect(tmp_path / "pacelab.db")
    conn.executescript(
        "ALTER TABLE activities DROP COLUMN published_version;"
    )
    conn.close()

    reopened = ResultStore(tmp_path / "pacelab.db")
    assert reopened.needs_publish("act1", "0.2.0", account_id="acct")
    assert reopened.load("act1", account_id="acct") == make_result()


def test_results_are_isolated_by_account(tmp_path):
    # ADR-0009: the same activity id under two accounts must not collide.
    store = ResultStore(tmp_path / "pacelab.db")
    alice = make_result()
    bob = ActivityResult(observed_pace=400.0, np_pace=395.0, cost_grade=0.0,
                         cost_heat=0.0, cost_wind=0.0, distance_m=100.0, segments=[])
    store.save("i100", alice, model_version="0.1.0", account_id="alice")
    store.save("i100", bob, model_version="0.1.0", account_id="bob")

    assert store.load("i100", account_id="alice") == alice
    assert store.load("i100", account_id="bob") == bob
    assert store.is_current("i100", "0.1.0", account_id="alice")
    assert not store.is_current("i100", "0.1.0", account_id="carol")


def _seed_corpus(store):
    """One row of each state the recompute enumeration must classify (ADR-0016)."""
    store.save("settled", make_result(), "0.2.1", account_id="acct")
    store.mark_published("settled", "0.2.1", account_id="acct")
    store.save("stale", make_result(), "0.2.0", account_id="acct")
    store.mark_published("stale", "0.2.0", account_id="acct")
    store.save("prov", make_result(), "0.2.1", account_id="acct", provisional=True)
    store.mark_published("prov", "0.2.1", account_id="acct")
    store.save("unpublished", make_result(), "0.2.1", account_id="acct")
    store.save("elsewhere", make_result(), "0.2.0", account_id="local")


def test_needs_recompute_enumerates_every_kind_of_drift(tmp_path):
    # ADR-0016: stale version, provisional preview, or stored-but-never-annotated.
    store = ResultStore(tmp_path / "pacelab.db")
    _seed_corpus(store)

    assert store.needs_recompute("0.2.1", "acct") == ["prov", "stale", "unpublished"]


def test_needs_recompute_is_scoped_to_one_account(tmp_path):
    # Rows under other accounts (e.g. "local" files) have no provider to recompute from.
    store = ResultStore(tmp_path / "pacelab.db")
    _seed_corpus(store)

    assert store.needs_recompute("0.2.1", "local") == ["elsewhere"]


def test_needs_recompute_goes_quiet_on_a_settled_corpus(tmp_path):
    store = ResultStore(tmp_path / "pacelab.db")
    store.save("act1", make_result(), "0.2.1", account_id="acct")
    store.mark_published("act1", "0.2.1", account_id="acct")

    assert store.needs_recompute("0.2.1", "acct") == []


def test_activity_ids_lists_the_whole_account_corpus(tmp_path):
    # What --force walks: every row, drifted or not.
    store = ResultStore(tmp_path / "pacelab.db")
    _seed_corpus(store)

    assert store.activity_ids("acct") == ["prov", "settled", "stale", "unpublished"]


def test_version_counts_reports_the_corpus_breakdown(tmp_path):
    # calibrate's header: is this fit reading one model version or several (ADR-0016)?
    store = ResultStore(tmp_path / "pacelab.db")
    _seed_corpus(store)

    assert store.version_counts("acct") == [("0.2.1", 3), ("0.2.0", 1)]


def test_has_stale_version_sees_only_rows_that_need_rewriting(tmp_path):
    # ADR-0018's snapshot trigger. A row that owes an annotation is drifted but not
    # stale — it is rewritten by nothing, and it recurs on every pass.
    store = ResultStore(tmp_path / "pacelab.db")
    store.save("act1", make_result(), model_version="0.2.1")
    assert not store.has_stale_version("0.2.1")
    assert store.needs_recompute("0.2.1") == ["act1"]  # drifted: never published

    store.mark_published("act1", "0.2.1")
    assert not store.has_stale_version("0.2.1")

    store.save("act2", make_result(), model_version="0.2.0")
    assert store.has_stale_version("0.2.1")


def test_an_unversioned_row_counts_as_stale(tmp_path):
    # NULL is the most drifted a row can be; `!=` would silently not match it.
    store = ResultStore(tmp_path / "pacelab.db")
    store.save("act1", make_result(), model_version="0.2.1")
    with sqlite3.connect(tmp_path / "pacelab.db") as conn:
        conn.execute("UPDATE activities SET model_version = NULL")

    assert store.has_stale_version("0.2.1")


# --- the heartbeat (ADR-0017) -------------------------------------------------------


def test_the_heartbeat_starts_absent(tmp_path):
    # Nothing has ticked yet, and an empty row would be a lie: `pacelab health` must be
    # able to tell "never ran" apart from "ran and succeeded".
    assert ResultStore(tmp_path / "pacelab.db").read_heartbeat() is None


def test_a_successful_tick_records_a_heartbeat(tmp_path):
    store = ResultStore(tmp_path / "pacelab.db")

    store.record_tick(True, summary="5 listed, 1 ok, 4 skip", interval_s=900, now=100.0)

    beat = store.read_heartbeat()
    assert beat.last_tick_at == 100.0
    assert beat.last_success_at == 100.0
    assert beat.consecutive_failures == 0
    assert beat.last_error is None
    assert beat.last_tick_summary == "5 listed, 1 ok, 4 skip"
    assert beat.interval_s == 900


def test_a_failed_tick_climbs_the_counter_and_leaves_the_last_success_alone(tmp_path):
    # The whole point of the row: a loop that keeps ticking and keeps failing must look
    # different from one that is quietly working.
    store = ResultStore(tmp_path / "pacelab.db")
    store.record_tick(True, summary="0 listed", interval_s=900, now=100.0)

    assert store.record_tick(False, error="RateLimited: 429", interval_s=900, now=200.0) == 1
    assert store.record_tick(False, error="RateLimited: 429", interval_s=900, now=300.0) == 2

    beat = store.read_heartbeat()
    assert beat.last_tick_at == 300.0
    assert beat.last_success_at == 100.0  # untouched by the failures
    assert beat.consecutive_failures == 2
    assert beat.last_error == "RateLimited: 429"
    assert beat.last_error_at == 300.0


def test_a_clean_tick_resets_the_counter_but_keeps_the_last_error(tmp_path):
    # The error stays readable after recovery — "it broke at 03:00 and came back" is the
    # thing a human wants from a heartbeat they only look at after the fact.
    store = ResultStore(tmp_path / "pacelab.db")
    store.record_tick(False, error="boom", interval_s=900, now=100.0)

    assert store.record_tick(True, summary="0 listed", interval_s=900, now=200.0) == 0

    beat = store.read_heartbeat()
    assert beat.consecutive_failures == 0
    assert beat.last_error == "boom"
    assert beat.last_error_at == 100.0


def test_only_a_tick_that_recomputed_moves_last_recompute_at(tmp_path):
    # The pass runs every tick and is silent when the corpus is settled; recording it as
    # a recompute anyway would make the field mean "the loop is alive", which is already
    # what last_success_at means.
    store = ResultStore(tmp_path / "pacelab.db")
    store.record_tick(True, summary="0 listed", recomputed=True, interval_s=900, now=100.0)
    store.record_tick(True, summary="0 listed", recomputed=False, interval_s=900, now=200.0)

    assert store.read_heartbeat().last_recompute_at == 100.0


def test_the_heartbeat_is_one_overwritten_row(tmp_path):
    # No append-only tick log (ADR-0017): history is the logs' job, and an unbounded
    # table on the Pi's SD card buys a second retention problem.
    db = tmp_path / "pacelab.db"
    store = ResultStore(db)
    for i in range(5):
        store.record_tick(True, summary="0 listed", interval_s=900, now=float(i))

    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM health").fetchone()[0] == 1


def test_the_heartbeat_needs_no_account(tmp_path):
    # Unkeyed by account_id on purpose: it describes the watch process, so `pacelab
    # health` can report broken credentials without needing valid credentials itself.
    store = ResultStore(tmp_path / "pacelab.db")
    store.record_tick(False, error="Account: INTERVALS_API_KEY is not set", interval_s=900,
                      now=100.0)

    assert store.read_heartbeat().last_error.startswith("Account:")


def test_the_heartbeat_survives_an_older_database(tmp_path):
    # The table is added to an existing corpus, not a fresh one — the Pi's db predates it.
    db = tmp_path / "pacelab.db"
    ResultStore(db).save("act1", make_result(), model_version="0.2.1")
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE health")

    reopened = ResultStore(db)
    reopened.record_tick(True, summary="1 listed, 1 ok", interval_s=900, now=100.0)

    assert reopened.read_heartbeat().last_success_at == 100.0
    assert reopened.load("act1") == make_result()


def test_a_failed_tick_clears_the_summary_rather_than_carrying_it_forward(tmp_path):
    # It describes *this* tick, and a failed tick synced nothing. Keeping the old one
    # would show a broken loop the last work it managed as if it had just done it — the
    # error and the untouched last_success_at are what tell the story instead.
    store = ResultStore(tmp_path / "pacelab.db")
    store.record_tick(True, summary="5 listed, 1 ok, 4 skip", interval_s=900, now=100.0)

    store.record_tick(False, error="RuntimeError: unreachable", interval_s=900, now=200.0)

    assert store.read_heartbeat().last_tick_summary is None
