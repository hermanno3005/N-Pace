"""SQLite system of record for activity results (FR-9.1, FR-10.1/10.2).

One row per activity plus its per-segment rows (needed by Phase-3 calibration, ADR-0006).
Each activity is stamped with the model version so re-runs are idempotent — the same
version skips, a bumped version recomputes and replaces.
"""

import sqlite3
import time
from dataclasses import dataclass
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
    published_version TEXT,
    provisional   INTEGER DEFAULT 0,
    start_time    REAL,
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
    solar_radiation_wm2 REAL,
    avg_hr        REAL,
    PRIMARY KEY (account_id, activity_id, idx)
);
-- The watch loop's heartbeat (ADR-0017): exactly one row, overwritten every tick. It is
-- deliberately *not* keyed by account_id — it describes the process, not an account, so
-- `pacelab health` can report broken credentials without needing credentials itself.
CREATE TABLE IF NOT EXISTS health (
    id                   INTEGER PRIMARY KEY CHECK (id = 1),
    last_tick_at         REAL,
    last_success_at      REAL,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_error           TEXT,
    last_error_at        REAL,
    last_recompute_at    REAL,
    last_tick_summary    TEXT,
    interval_s           INTEGER
);
"""


class ResultStore:
    def __init__(self, db_path: Path):
        self._path = str(db_path)
        with self._connect() as conn:
            self._migrate_v01(conn)
            conn.executescript(_SCHEMA)
            self._migrate_add_columns(conn)

    @staticmethod
    def _migrate_add_columns(conn: sqlite3.Connection) -> None:
        """Add columns introduced after a table already existed (additive, no PK change)."""
        columns = {r[1] for r in conn.execute("PRAGMA table_info(activities)")}
        if "published_version" not in columns:
            conn.execute("ALTER TABLE activities ADD COLUMN published_version TEXT")
        if "provisional" not in columns:
            conn.execute("ALTER TABLE activities ADD COLUMN provisional INTEGER DEFAULT 0")
        if "start_time" not in columns:
            conn.execute("ALTER TABLE activities ADD COLUMN start_time REAL")
        seg_columns = {r[1] for r in conn.execute("PRAGMA table_info(segments)")}
        if "avg_hr" not in seg_columns:
            conn.execute("ALTER TABLE segments ADD COLUMN avg_hr REAL")

    @staticmethod
    def _migrate_v01(conn: sqlite3.Connection) -> None:
        """Rebuild a pre-account-id (v0.1) database into the current schema.

        v0.1 tables had no account_id (or solar) column and a different primary key, so
        CREATE TABLE IF NOT EXISTS alone would leave them broken. Old rows are preserved
        under the default "local" account; solar (absent in v0.1) migrates as NULL.
        """
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "activities" not in tables:
            return  # fresh database
        columns = {r[1] for r in conn.execute("PRAGMA table_info(activities)")}
        if "account_id" in columns:
            return  # already current
        conn.executescript(
            "ALTER TABLE activities RENAME TO activities_v01;"
            "ALTER TABLE segments RENAME TO segments_v01;"
            + _SCHEMA +
            "INSERT INTO activities SELECT 'local', *, NULL, 0, NULL FROM activities_v01;"
            "INSERT INTO segments SELECT 'local', s.*, NULL, NULL FROM segments_v01 s;"
            "DROP TABLE activities_v01;"
            "DROP TABLE segments_v01;"
        )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)

    def save(self, activity_id: str, result: ActivityResult, model_version: str,
             account_id: str = "local", provisional: bool = False) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM activities WHERE account_id = ? AND activity_id = ?",
                         (account_id, activity_id))
            conn.execute("DELETE FROM segments WHERE account_id = ? AND activity_id = ?",
                         (account_id, activity_id))
            # published_version starts NULL — a recompute resets it, so sync republishes
            # exactly when it reanalyses (ADR-0011).
            conn.execute(
                "INSERT INTO activities VALUES (?,?,?,?,?,?,?,?,?,NULL,?,?)",
                (account_id, activity_id, result.distance_m, result.observed_pace,
                 result.np_pace, result.cost_grade, result.cost_heat, result.cost_wind,
                 model_version, int(provisional), result.start_time),
            )
            conn.executemany(
                "INSERT INTO segments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (account_id, activity_id, s.idx, s.distance, s.grade, s.elapsed,
                     s.temperature_c, s.humidity_pct, s.wind_speed_ms, s.wind_dir_deg,
                     s.p_grade, s.p_heat, s.p_wind, s.pace_obs, s.pace_np, int(s.stopped),
                     s.solar_radiation_wm2, s.avg_hr)
                    for s in result.segments
                ],
            )

    def delete(self, activity_id: str, account_id: str = "local") -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM activities WHERE account_id = ? AND activity_id = ?",
                         (account_id, activity_id))
            conn.execute("DELETE FROM segments WHERE account_id = ? AND activity_id = ?",
                         (account_id, activity_id))

    def is_provisional(self, activity_id: str, account_id: str = "local") -> bool:
        """True when the stored result came from forecast-tier weather (ADR-0012)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT provisional FROM activities WHERE account_id = ? AND activity_id = ?",
                (account_id, activity_id),
            ).fetchone()
        return row is not None and bool(row[0])

    def needs_publish(self, activity_id: str, model_version: str, account_id: str = "local") -> bool:
        """True when a stored result hasn't been annotated under this model version."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT published_version FROM activities WHERE account_id = ? AND activity_id = ?",
                (account_id, activity_id),
            ).fetchone()
        return row is not None and row[0] != model_version

    def mark_published(self, activity_id: str, model_version: str, account_id: str = "local") -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE activities SET published_version = ? "
                "WHERE account_id = ? AND activity_id = ?",
                (model_version, account_id, activity_id),
            )

    def needs_recompute(self, model_version: str, account_id: str = "local") -> list[str]:
        """Activity ids whose stored row disagrees with itself (ADR-0016).

        Drift is a query, not a stored marker, so it cannot go stale and it describes a
        half-finished pass correctly for free. Three ways a row drifts: it was stamped at
        an older model version, it is a forecast-tier preview awaiting the archive, or it
        is stored current but was never annotated at this version.
        """
        with self._connect() as conn:
            rows = conn.execute(
                # IS NOT, not !=, on both version columns: a NULL version is the most
                # drifted a row can be, and != would silently not match it.
                "SELECT activity_id FROM activities WHERE account_id = ? "
                "AND (model_version IS NOT ? OR provisional = 1 OR published_version IS NOT ?) "
                "ORDER BY start_time, activity_id",
                (account_id, model_version, model_version),
            ).fetchall()
        return [r[0] for r in rows]

    def has_stale_version(self, model_version: str, account_id: str = "local") -> bool:
        """True when any stored row was stamped at a different model version.

        The narrow half of drift: rows that must be *rewritten*, as opposed to rows that
        merely still owe an annotation. What ADR-0018's snapshot trigger asks about.
        """
        with self._connect() as conn:
            row = conn.execute(
                # IS NOT, as in needs_recompute: a NULL version is stale, and != misses it.
                "SELECT 1 FROM activities WHERE account_id = ? AND model_version IS NOT ? "
                "LIMIT 1", (account_id, model_version),
            ).fetchone()
        return row is not None

    def activity_ids(self, account_id: str = "local") -> list[str]:
        """Every stored activity for an account — what a forced recompute walks."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT activity_id FROM activities WHERE account_id = ? "
                "ORDER BY start_time, activity_id", (account_id,),
            ).fetchall()
        return [r[0] for r in rows]

    def version_counts(self, account_id: str = "local") -> list[tuple[str | None, int]]:
        """Rows per model version, most common first — calibrate's mixed-corpus check."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT model_version, COUNT(*) FROM activities WHERE account_id = ? "
                "GROUP BY model_version ORDER BY COUNT(*) DESC, model_version DESC",
                (account_id,),
            ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def is_current(self, activity_id: str, model_version: str, account_id: str = "local") -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT model_version FROM activities WHERE account_id = ? AND activity_id = ?",
                (account_id, activity_id),
            ).fetchone()
        return row is not None and row[0] == model_version

    def record_tick(self, ok: bool, summary: str | None = None, error: str | None = None,
                    recomputed: bool = False, interval_s: int | None = None,
                    now: float | None = None) -> int:
        """Overwrite the heartbeat with this tick, and return `consecutive_failures`.

        `ok` means the tick raised nothing (ADR-0017) — a pass that completed while every
        publish failed is a success that reports its degradation through `summary`. The
        returned count is what `watch` uses to log a traceback once per streak.
        """
        at = time.time() if now is None else now
        with self._connect() as conn:
            row = conn.execute(
                "SELECT last_success_at, consecutive_failures, last_error, last_error_at, "
                "last_recompute_at FROM health WHERE id = 1"
            ).fetchone()
            last_success_at, failures, last_error, last_error_at, last_recompute_at = (
                row if row else (None, 0, None, None, None)
            )
            if ok:
                last_success_at, failures = at, 0
            else:
                failures += 1
                last_error, last_error_at = error, at
            conn.execute(
                "INSERT OR REPLACE INTO health VALUES (1,?,?,?,?,?,?,?,?)",
                (at, last_success_at, failures, last_error, last_error_at,
                 at if recomputed else last_recompute_at, summary, interval_s),
            )
        return failures

    def read_health(self) -> "Heartbeat | None":
        """The watch loop's last tick, or None when it has never run."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT last_tick_at, last_success_at, consecutive_failures, last_error, "
                "last_error_at, last_recompute_at, last_tick_summary, interval_s "
                "FROM health WHERE id = 1"
            ).fetchone()
        return Heartbeat(*row) if row else None

    def np_trend(self, account_id: str = "local") -> list["TrendPoint"]:
        """NP over time (FR-9.3): one point per stored activity, date-ordered."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT activity_id, start_time, distance_m, observed_pace, np_pace, "
                "provisional FROM activities WHERE account_id = ? "
                "ORDER BY start_time", (account_id,),
            ).fetchall()
        return [TrendPoint(r[0], r[1] or 0.0, r[2], r[3], r[4], bool(r[5])) for r in rows]

    def load(self, activity_id: str, account_id: str = "local") -> ActivityResult | None:
        with self._connect() as conn:
            act = conn.execute(
                "SELECT distance_m, observed_pace, np_pace, cost_grade, cost_heat, cost_wind, "
                "start_time FROM activities WHERE account_id = ? AND activity_id = ?",
                (account_id, activity_id),
            ).fetchone()
            if act is None:
                return None
            rows = conn.execute(
                "SELECT idx, distance, grade, elapsed, temperature_c, humidity_pct, "
                "wind_speed_ms, wind_dir_deg, p_grade, p_heat, p_wind, pace_obs, pace_np, "
                "stopped, solar_radiation_wm2, avg_hr "
                "FROM segments WHERE account_id = ? AND activity_id = ? ORDER BY idx",
                (account_id, activity_id),
            ).fetchall()
        segments = [
            SegmentResult(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9],
                          r[10], r[11], r[12], bool(r[13]), r[14], r[15])
            for r in rows
        ]
        return ActivityResult(
            observed_pace=act[1], np_pace=act[2], cost_grade=act[3], cost_heat=act[4],
            cost_wind=act[5], distance_m=act[0], segments=segments,
            start_time=act[6] or 0.0,
        )


@dataclass(frozen=True)
class Heartbeat:
    """What one watch tick left behind (ADR-0017). Timestamps are epoch seconds.

    Derivable state (unpublished backlog, stale-version count) is deliberately absent: it
    is a live query against `activities`, and a second copy here could disagree with it.
    """

    last_tick_at: float | None
    last_success_at: float | None
    consecutive_failures: int
    last_error: str | None
    last_error_at: float | None
    last_recompute_at: float | None
    last_tick_summary: str | None
    interval_s: int | None


@dataclass(frozen=True)
class TrendPoint:
    """One activity on the NP-over-time axis (FR-9.3)."""

    activity_id: str
    start_time: float  # epoch seconds
    distance_m: float
    observed_pace: float  # s/km
    np_pace: float  # s/km
    provisional: bool
