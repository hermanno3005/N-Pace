"""SQLite system of record for activity results (FR-9.1, FR-10.1/10.2).

One row per activity plus its per-segment rows (needed by Phase-3 calibration, ADR-0006).
Each activity is stamped with the model version so re-runs are idempotent — the same
version skips, a bumped version recomputes and replaces.
"""

import sqlite3
from pathlib import Path

from pacelab.analyze import ActivityResult, SegmentResult

# Rows are keyed by (account_id, activity_id) so the same activity id under different
# accounts never collides (ADR-0009). Local-file analysis uses the "local" account.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    account_id    TEXT,
    activity_id   TEXT,
    distance_m    REAL,
    observed_pace REAL,
    np_pace       REAL,
    cost_grade    REAL,
    cost_heat     REAL,
    cost_wind     REAL,
    model_version TEXT,
    PRIMARY KEY (account_id, activity_id)
);
CREATE TABLE IF NOT EXISTS segments (
    account_id    TEXT,
    activity_id   TEXT,
    idx           INTEGER,
    distance      REAL,
    grade         REAL,
    elapsed       REAL,
    temperature_c REAL,
    humidity_pct  REAL,
    wind_speed_ms REAL,
    wind_dir_deg  REAL,
    p_grade       REAL,
    p_heat        REAL,
    p_wind        REAL,
    pace_obs      REAL,
    pace_np       REAL,
    stopped       INTEGER,
    PRIMARY KEY (account_id, activity_id, idx)
);
"""


class ResultStore:
    def __init__(self, db_path: Path):
        self._path = str(db_path)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)

    def save(self, activity_id: str, result: ActivityResult, model_version: str,
             account_id: str = "local") -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM activities WHERE account_id = ? AND activity_id = ?",
                         (account_id, activity_id))
            conn.execute("DELETE FROM segments WHERE account_id = ? AND activity_id = ?",
                         (account_id, activity_id))
            conn.execute(
                "INSERT INTO activities VALUES (?,?,?,?,?,?,?,?,?)",
                (account_id, activity_id, result.distance_m, result.observed_pace,
                 result.np_pace, result.cost_grade, result.cost_heat, result.cost_wind,
                 model_version),
            )
            conn.executemany(
                "INSERT INTO segments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (account_id, activity_id, s.idx, s.distance, s.grade, s.elapsed,
                     s.temperature_c, s.humidity_pct, s.wind_speed_ms, s.wind_dir_deg,
                     s.p_grade, s.p_heat, s.p_wind, s.pace_obs, s.pace_np, int(s.stopped))
                    for s in result.segments
                ],
            )

    def is_current(self, activity_id: str, model_version: str, account_id: str = "local") -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT model_version FROM activities WHERE account_id = ? AND activity_id = ?",
                (account_id, activity_id),
            ).fetchone()
        return row is not None and row[0] == model_version

    def load(self, activity_id: str, account_id: str = "local") -> ActivityResult | None:
        with self._connect() as conn:
            act = conn.execute(
                "SELECT distance_m, observed_pace, np_pace, cost_grade, cost_heat, cost_wind "
                "FROM activities WHERE account_id = ? AND activity_id = ?",
                (account_id, activity_id),
            ).fetchone()
            if act is None:
                return None
            rows = conn.execute(
                "SELECT idx, distance, grade, elapsed, temperature_c, humidity_pct, "
                "wind_speed_ms, wind_dir_deg, p_grade, p_heat, p_wind, pace_obs, pace_np, "
                "stopped FROM segments WHERE account_id = ? AND activity_id = ? ORDER BY idx",
                (account_id, activity_id),
            ).fetchall()
        segments = [
            SegmentResult(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9],
                          r[10], r[11], r[12], bool(r[13]))
            for r in rows
        ]
        return ActivityResult(
            observed_pace=act[1], np_pace=act[2], cost_grade=act[3], cost_heat=act[4],
            cost_wind=act[5], distance_m=act[0], segments=segments,
        )
