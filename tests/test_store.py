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
