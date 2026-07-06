# v0.2 heat model: closed-form WBGT, which makes wind cooling intrinsic

The heat-stress index becomes **outdoor WBGT** (Wet-Bulb Globe Temperature), computed by the
**Dimiceli & Piltz (2011) closed-form** — the scheme NOAA runs operationally in the NDFD —
from air temperature, humidity, wind, and solar irradiance. Not the v1 Heat Index, not the
full iterative Liljegren solver, not the shade-only (humidity-only) simplified WBGT.
`WBGT = 0.7·Tnw + 0.2·Tg + 0.1·Ta`; Stull (2011) gives the wet-bulb, and solar/wind enter the
globe term `Tg`. Formulas, coefficients, and sources in `docs/research/wbgt-heat-model.md`.

**Why closed-form-with-solar-and-wind.** It is the only tier that delivers what WBGT exists
for. Shade WBGT (T + humidity only) discards radiant load and wind, leaving it barely
distinct from the v1 Heat Index — a pointless upgrade. Full Liljegren is an iterative
heat-balance solver: reference-grade but disproportionate for a single-user tool. The
closed form captures the radiant load and the wind cooling without the solver.

## The wind→heat coupling dissolves

ADR-0001 deferred a "wind→heat cooling" coefficient (0 in v1, on in v0.2). WBGT makes it
**intrinsic, not a bolt-on**: WBGT's natural-wet-bulb term falls as wind rises, so more wind
→ lower WBGT → smaller heat penalty, from the physics. There is no separate coupling
coefficient to tune. Wind still feeds the *mechanical* penalty as drag (ADR-0001); it now
also feeds heat, through WBGT.

## Solar input

Fetch Open-Meteo **`shortwave_radiation`** (W/m², surface irradiance, already cloud-adjusted)
for WBGT's globe term. This makes `cloud_cover` redundant for heat; it drops off the fetch.
Available in the pinned ERA5 archive back decades, so history stays reproducible (ADR-0004).

## Re-anchoring the penalty curve

The curve keeps its form `p_heat = a·max(0, WBGT − WBGT_ref)^b`, but WBGT is a *different
scale* than air temperature (even dry/calm/shade, WBGT ≠ T_air), so the coefficients must move:

- **WBGT_ref is analytic**, not fit: the WBGT at reference conditions (10 °C, 50% RH, no wind,
  **no sun**) = **7.2 °C** (Stull `Tw = 5.10`, `Tnw = 5.95`, `Tg = Ta = 10` in shade → 7.17).
  Penalty is zero there by construction; it sits inside the literature's 5–10 °C WBGT optimum.
- **`a`, `b` re-fit by porting El Helou (2012) to the WBGT axis** — keeping the one evidence
  base we trust rather than WBGT safety thresholds (which answer "can you race", not "how much
  slower"). El Helou's fit is explicitly **quadratic**, so `b = 2.0` (a firmer anchor than v1's
  placeholder 1.5); transforming its air-temp curvature to the WBGT axis via `dWBGT/dTa ≈ 0.72`
  gives `a ≈ 0.0007`. Provisional pending Phase-3 calibration (ADR-0006).

## Implementation hazards (from the research)

- **Unit trap:** in Dimiceli's scheme wind is **m/s** in `Tnw` but **m/hr** in `Tg` — convert
  per-term or the globe temperature is wildly wrong.
- **Solar sub-coefficient:** Dimiceli's `h = a·S^b·cos(z)^c` regression constants aren't
  published numerically; use NDFD's fixed daytime `h ≈ 0.228`.
- **Sun double-count:** El Helou regressed on *air temperature* with no per-race irradiance,
  so a run's solar load may be partly baked into its `a` already. Watch for over-penalising
  sunny runs; calibration (ADR-0006) is the corrective.

## Fallback & versioning

WBGT is primary; when `shortwave_radiation` is unavailable (a gap, or streams-sourced data),
fall back to the v1 **Heat Index**, confidence-tagged — both stay behind the one
`heat_penalty(conditions)` interface. Switching the index is a model change, so
**`model_version` → 0.2.0**; the store's idempotency recomputes history under WBGT (FR-10.2).

## Consequences

- Amends ADR-0002 (reference gains "no solar radiation") and supersedes ADR-0001's deferred
  wind→heat coefficient (now intrinsic).
- Adds one fetched weather variable and a WBGT computation; removes `cloud_cover` from heat.
