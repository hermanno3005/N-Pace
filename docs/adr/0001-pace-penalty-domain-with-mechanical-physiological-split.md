# Combine environmental effects in the pace-penalty domain, split mechanical vs physiological

Grade, heat, and wind are reduced to a common currency — a **pace penalty** (fractional
slowing at constant effort) — and combined in pace space rather than in energy space.
Energy-based models (grade via Minetti, wind via drag) are converted to a pace penalty via
the constant-power relation `speed ∝ 1 / cost-of-transport`; heat's penalty is empirical
(Ely / El Helou) and used directly.

The combination is a **hybrid**, not a uniform rule, because the three effects are not the
same kind of thing:

- **Grade + wind** are independent, additive *energy* demands → combined additively into a
  single mechanical penalty `p_mech`.
- **Heat** is a *capacity* limit (it scales sustainable pace, it does not add joules/meter)
  → applied multiplicatively on top: `NP = observed / [ (1 + p_mech) × (1 + p_heat) ]`.
- **Wind** feeds two models: drag (inside `p_mech`) and convective cooling (which *reduces*
  `p_heat`). The cooling coupling coefficient starts at 0 in v0.1 and is enabled in v0.2.

> **Update (v0.2, ADR-0010):** the wind→heat coupling is no longer a separate coefficient.
> Adopting WBGT as the heat-stress index makes it *intrinsic* — WBGT's wet-bulb term falls
> as wind rises, so wind cooling is baked into the index. There is nothing to tune.

## Considered options

- **Uniform additive** (`1 + p_g + p_h + p_w`, the SRS's original lean) — under-counts
  compounding and models heat as additive rather than scaling.
- **Uniform multiplicative** (`Π(1 + p_i)`) — correct-ish but ignores that grade and wind
  energies add, and drops the wind→heat coupling.

## Consequences

- Forward (AP) and backward (NP) are exact inverses by construction, satisfying the
  round-trip identity (V-2).
- This is the highest-leverage modeling choice (R-4); the hybrid structure is fixed even
  though individual coefficients remain tunable (NFR-4).
