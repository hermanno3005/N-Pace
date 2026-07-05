"""Human-readable summary + per-segment table, and JSON export (FR-9.2/9.1)."""

from pacelab.analyze import ActivityResult


def pace(sec_per_km: float) -> str:
    m, s = divmod(round(sec_per_km), 60)
    return f"{m}:{s:02d}"


def format_summary(activity_id: str, result: ActivityResult) -> str:
    lines = [
        f"PaceLab — {activity_id}",
        f"  Distance      : {result.distance_m / 1000:.2f} km",
        f"  Observed pace : {pace(result.observed_pace)}/km",
        f"  Normalized    : {pace(result.np_pace)}/km   (grade + heat removed)",
        "  Environmental cost (s/km):",
        f"    grade : {result.cost_grade:+.1f}",
        f"    heat  : {result.cost_heat:+.1f}",
        f"    wind  : {result.cost_wind:+.1f}   (reported, not applied)",
    ]
    return "\n".join(lines)


def format_segments(result: ActivityResult) -> str:
    header = f"{'#':>3} {'dist':>5} {'grade':>6} {'obs':>6} {'NP':>6} {'temp':>5} {'wind':>5} {'stop':>4}"
    rows = [header]
    for s in result.segments:
        rows.append(
            f"{s.idx:>3} {s.distance:>5.0f} {s.grade:>+6.1%} {pace(s.pace_obs):>6} "
            f"{pace(s.pace_np):>6} {s.temperature_c:>4.0f}C {s.wind_speed_ms:>4.1f} "
            f"{'yes' if s.stopped else '':>4}"
        )
    return "\n".join(rows)


def to_dict(activity_id: str, result: ActivityResult, model_version: str) -> dict:
    return {
        "activity_id": activity_id,
        "model_version": model_version,
        "distance_m": result.distance_m,
        "observed_pace_s_per_km": result.observed_pace,
        "np_pace_s_per_km": result.np_pace,
        "cost_s_per_km": {
            "grade": result.cost_grade,
            "heat": result.cost_heat,
            "wind": result.cost_wind,
        },
        "segments": [
            {
                "idx": s.idx, "distance": s.distance, "grade": s.grade, "elapsed": s.elapsed,
                "temperature_c": s.temperature_c, "humidity_pct": s.humidity_pct,
                "wind_speed_ms": s.wind_speed_ms, "wind_dir_deg": s.wind_dir_deg,
                "p_grade": s.p_grade, "p_heat": s.p_heat, "p_wind": s.p_wind,
                "pace_obs": s.pace_obs, "pace_np": s.pace_np, "stopped": s.stopped,
            }
            for s in result.segments
        ],
    }
