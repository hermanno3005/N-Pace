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
