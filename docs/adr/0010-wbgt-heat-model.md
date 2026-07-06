# v0.2 heat model: closed-form WBGT, which makes wind cooling intrinsic

The heat-stress index becomes **outdoor WBGT** (Wet-Bulb Globe Temperature), computed by a
**closed-form approximation** from air temperature, humidity, wind, and solar irradiance —
not the v1 Heat Index, not the full iterative Liljegren solver, not the shade-only
(humidity-only) simplified WBGT.

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
  **no sun**). Penalty is zero there by construction.
- **`a`, `b` are re-fit by porting El Helou (2012) to the WBGT axis** — reconstruct the WBGT of
  its marathon conditions and re-fit, keeping the one evidence base we already trust rather
  than adopting WBGT safety thresholds (which answer "can you race", not "how much slower").
  See `docs/research/wbgt-heat-model.md`. Provisional pending Phase-3 calibration (ADR-0006).

## Fallback & versioning

WBGT is primary; when `shortwave_radiation` is unavailable (a gap, or streams-sourced data),
fall back to the v1 **Heat Index**, confidence-tagged — both stay behind the one
`heat_penalty(conditions)` interface. Switching the index is a model change, so
**`model_version` → 0.2.0**; the store's idempotency recomputes history under WBGT (FR-10.2).

## Consequences

- Amends ADR-0002 (reference gains "no solar radiation") and supersedes ADR-0001's deferred
  wind→heat coefficient (now intrinsic).
- Adds one fetched weather variable and a WBGT computation; removes `cloud_cover` from heat.
