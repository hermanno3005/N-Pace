from pacelab.analyze import ActivityResult
from pacelab.report import format_trend
from pacelab.store import ResultStore, TrendPoint


def make(np, obs, start_time, dist=10000.0):
    return ActivityResult(observed_pace=obs, np_pace=np, cost_grade=0.0, cost_heat=2.0,
                          cost_wind=0.0, distance_m=dist, segments=[],
                          start_time=start_time)


def test_np_trend_is_date_ordered_across_activities(tmp_path):
    store = ResultStore(tmp_path / "db")
    # Saved out of chronological order; the trend orders by activity start time.
    store.save("later", make(280.0, 300.0, 2_000_000.0), "0.2.0", account_id="acct")
    store.save("earlier", make(290.0, 310.0, 1_000_000.0), "0.2.0", account_id="acct",
               provisional=True)

    trend = store.np_trend(account_id="acct")

    assert [p.activity_id for p in trend] == ["earlier", "later"]
    first = trend[0]
    assert isinstance(first, TrendPoint)
    assert first.start_time == 1_000_000.0
    assert first.np_pace == 290.0
    assert first.observed_pace == 310.0
    assert first.distance_m == 10000.0
    assert first.provisional is True


def test_start_time_survives_a_store_round_trip(tmp_path):
    store = ResultStore(tmp_path / "db")
    store.save("a", make(280.0, 300.0, 1_720_000_000.0), "0.2.0", account_id="acct")
    assert store.load("a", account_id="acct").start_time == 1_720_000_000.0


def test_format_trend_renders_dates_paces_and_provisional_mark():
    points = [
        TrendPoint("a", 1748736000.0, 10000.0, 310.0, 290.0, False),  # 2025-06-01
        TrendPoint("b", 1749340800.0, 10000.0, 305.0, 286.0, False),  # 2025-06-08
        TrendPoint("c", 1749945600.0, 12000.0, 300.0, 282.0, True),   # 2025-06-15
    ]
    out = format_trend(points)
    lines = out.splitlines()
    assert "date" in lines[0] and "NP" in lines[0]
    assert "2025-06-01" in lines[1] and "4:50" in lines[1]  # NP 290 s/km
    assert "2025-06-15" in lines[3] and "~" in lines[3]  # provisional marked
    assert "12.0" in lines[3]  # distance in km