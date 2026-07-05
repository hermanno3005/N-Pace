# PaceLab v0.1 — Implementation Plan

Scope (SRS §7): FR-1 (FIT), FR-2, FR-3 (historical), FR-4, basic FR-5, naive FR-6,
FR-7 (NP + decomposition), FR-9 minimal. Design decisions are recorded in `docs/adr/`
and the domain language in `CONTEXT.md`; this plan turns them into code.

## Architecture — pluggable pipeline (NFR-8)

```
FIT/GPX ──▶ Track ──▶ Segments ──▶ +Weather ──▶ Penalties ──▶ NP + decomposition ──▶ SQLite
  ingest    preprocess  (100 m)     weather      models[]       engine              store
```

```
pacelab/
  ingest/     base.py (Track, Trackpoint, SourceAdapter protocol) · fit.py · gpx.py
  preprocess/ smoothing.py (Savitzky–Golay, grade cap ±45%) · segment.py (100 m resample, grade/bearing/time, stoppage flag)
  weather/    openmeteo.py (pinned ERA5-Land→ERA5) · cache.py ((cell,hour) key) · interpolate.py (linear-time, nearest-cell)
  models/     base.py (ImpactModel: cost(segment, weather) → PacePenalty) · grade.py · heat.py · wind.py · air_density.py
  engine/     combine.py (hybrid) · normalize.py (NP backward / AP forward, applied-vs-reported)
  store/      schema.sql · repo.py (SQLite + JSON export)
  config.py · cli.py · report.py
```

The `ImpactModel` protocol (`cost(segment, weather) → PacePenalty`) is the deep-module seam:
grade/heat/wind are interchangeable behind it, and Phase-3 calibration swaps coefficients
without touching the engine.

## The math (each decision → code)

**Grade** (Minetti 2002, `i` = grade fraction, capped ±0.45):
`C(i) = 155.4 i⁵ − 30.4 i⁴ − 43.3 i³ + 46.3 i² + 19.5 i + 3.6` J/kg/m.
Excess energy `ΔC_grade = C(i) − C(0)`, with `C(0) = 3.6`.

**Wind** → headwind `w = wind_speed · cos(θ_wind − θ_bearing)` (meteorological convention:
wind direction is where it blows *from*). Excess aero energy
`ΔC_wind = ½ · ρ · (C_dA/m) · [(v + w)² − v²]`, `C_dA/m ≈ 0.0058` (config). Signed, so a
tailwind saves less than a headwind of the same magnitude costs — the `2w²` Pugh/Davies
asymmetry is automatic, no artificial factor.

**Mechanical penalty** (ADR-0001, additive in energy):
`p_mech = (C(0) + ΔC_grade + ΔC_wind) / C(0) − 1`. (Energy ratio → pace penalty via the
constant-power relation `speed ∝ 1/C`, so pace scales as the cost ratio.)

**Heat** (Heat Index from T + RH → El Helou/Ely curve):
`p_heat = a · max(0, HI − 10 °C)^b`, `a, b` config, cold penalty 0 above freezing.

**Air density** `ρ = P / (R · T_kelvin)` from Open-Meteo surface pressure (humidity
correction optional in v1).

**Normalize** (ADR-0001 + ADR-0005):
- **Applied NP**: `pace_ref = pace_obs / [ (1 + p_grade) · (1 + p_heat) ]` — wind excluded by
  default (`apply_wind = False`).
- **Reported decomposition**: `p_grade`, `p_heat`, `p_wind` all stored per segment.
- **Activity NP** = `Σ dist / Σ t_normalized`; **AP** (forward) = exact inverse
  (`× (1 + p_i)`), so the V-2 round-trip holds by construction.

## Config surface (NFR-4 — all parameters in config, not code)

Reference conditions (frozen, ADR-0002); Minetti coefficients; `C_dA/m`; heat `a, b`;
segment step (100 m); **home elevation** (user-supplied); pinned weather model; `apply_wind`
flag (default off); drafting flag (default off).

## Storage (per-segment, ADR-0006)

- `activities(id, source, start_time, model_version, …)`
- `segments(activity_id, idx, dist, grade, bearing, elapsed, T, RH, wind_speed, wind_dir,
  p_grade, p_heat, p_wind, pace_obs, pace_norm)`
- `results(activity_id, np, observed_pace, cost_grade, cost_heat, cost_wind)`

Idempotent on `(activity_id, model_version)` (FR-10.1). Per-activity JSON export; optional
Parquet analytics dumps.

## Build order (test-first; V-1 and V-2 are the gates)

1. **Data model + config** — dataclasses, SQLite schema, frozen reference conditions.
2. **Grade + engine** — Minetti, combine, normalize. Prove **V-1** (flat & 10 °C & no wind
   → factors ≈ 1.0; known Minetti points within tolerance) and **V-2** (forward∘backward =
   identity) with zero I/O. The mathematical core, locked first.
3. **FIT ingest + preprocess** — parse → smooth → 100 m segments on a real activity.
4. **Weather** — pinned Open-Meteo client + cache + interpolation.
5. **Heat + wind models** — plug in behind the `ImpactModel` protocol.
6. **CLI + report + store** — end-to-end on one activity; then a **V-4** stress trio
   (hot / windy / hilly), checking each decomposition's dominant term and sign.

Milestone 2 is the crux: the engine is fully testable with no external dependencies, so the
physics is validated before FIT parsing or the network is ever involved.
