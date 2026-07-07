# Grounding the v0.2 heat model on outdoor WBGT

Porting PaceLab's heat penalty `p_heat = a·max(0, index − ref)^b` from the NWS Heat Index
axis (ADR-0001/0002, `src/pacelab/models/heat.py`) to an outdoor **Wet Bulb Globe
Temperature** axis. Two questions: (1) a published *closed-form* (non-iterative) outdoor
WBGT from standard weather variables; (2) re-express El Helou (2012) on that axis and
recommend provisional `a`, `b`, and `WBGT_ref`.

## Chosen formula: Dimiceli & Piltz (NWS Tulsa) outdoor WBGT

The **Dimiceli, Piltz & Amburn (2011)** globe-temperature approximation plus the **NDFD
natural-wet-bulb** regression give a fully closed-form outdoor WBGT from routine variables:
air temperature `Ta`, dew point `Td` (⇒ humidity), wind speed `u`, **solar irradiance `S`
(W/m²)**, and pressure `P`. This is the scheme NOAA/NWS runs operationally in the NDFD, so
it is a primary, maintained, and validated target — not a textbook toy. It is non-iterative:
Dimiceli linearises the 4th-degree globe-temperature heat balance to a closed algebraic
solution (their whole point).

Primary sources:
- Dimiceli, Piltz, Amburn (2011), *Estimation of Black Globe Temperature for Calculation of
  the WBGT Index*, Proc. WCECS 2011 Vol II
  ([iaeng.org PDF](https://www.iaeng.org/publication/WCECS2011/WCECS2011_pp591-599.pdf)) —
  globe temperature `Tg`, verbatim below.
- Boyer / NWS-MDL (2013/2021), *NDFD Wet Bulb Globe Temperature Algorithm and Software
  Design*
  ([vlab.noaa.gov PDF](https://vlab.noaa.gov/documents/6609493/7858379/NDFD+WBGT+Description+Document.pdf)) —
  the operational natural-wet-bulb regression and composite, verbatim below.

### (c) Composite — OSHA / Dimiceli, verbatim

From Dimiceli §I (the OSHA outdoor-with-solar-load form) and NDFD *Methodology*:

> WBGT = 0.7·NWB + 0.2·GT + 0.1·DB

where `NWB` = natural wet-bulb temperature, `GT` = globe temperature, `DB` = dry-bulb (air)
temperature — i.e. the standard `WBGT = 0.7·Tnw + 0.2·Tg + 0.1·Ta`, all in °C. (Indoors /
no solar load the weighting collapses to `0.7·NWB + 0.3·GT`; the 0.2 globe term is where
solar and wind enter, so shade ≈ that collapse.)

### (a) Natural wet-bulb temperature `Tnw` — NDFD, verbatim

NDFD's improved regression (a wet-bulb-depression correction over Hunter & Minyard 1999),
NDFD doc *Calculation of the natural wet bulb temperature*:

> Tnwb = Tw + 0.001651·S − 0.09555·u + 0.13235·Twd + 0.20249

with `Tw` = thermodynamic (psychrometric) wet-bulb temp (°C), `S` = solar radiation flux
(W/m²), **`u` = wind speed (m/s)**, `Twd` = wet-bulb depression = `Ta − Tw`. The original
Hunter & Minyard (1999) form NDFD started from is also stated verbatim:

> Tnwb = Tw + 0.0021·S − 0.43·u + 1.93

Both carry **`+`(solar)** and **`−`(wind)** signs. `Tw` itself is obtained closed-form from
`Ta` and RH via **Stull (2011)** (empirical, gene-expression fit; MAE < 0.3 °C over
−20…50 °C, RH 5–99 %; [Stull 2011, *JAMC* 50:2267](https://doi.org/10.1175/JAMC-D-11-0143.1)):

> Tw = T·atan[0.151977·(RH + 8.313659)^½] + atan(T + RH) − atan(RH − 1.676331)
>      + 0.00391838·RH^(3/2)·atan(0.023101·RH) − 4.686035

(`T` in °C, `RH` in %, arctangents in radians).

### (b) Globe temperature `Tg` — Dimiceli & Piltz eq. (11), verbatim

This is where **solar irradiance and wind** enter. Dimiceli's closed-form (their eq. 11 /
Algorithm step 5):

> Tg = (B + C·Ta + 7 680 000) / (C + 256 000)

with (eqs. 2, 4–8, and Algorithm steps 3–4; `Ta` in °C):

> B = S·( f_db / (4·σ·cos(z)) + (1.2/σ)·f_dif ) + ε_a·Ta⁴
> C = h·u^0.58 / (5.3865×10⁻⁸)
> h = a·(S^b)·(cos(z))^c            (convective heat-transfer coeff., multiple-power regression)
> ε_a = 0.575·e_a^(1/7)             (atmospheric thermal emissivity)
> e_a = exp(17.67·(Td−Ta)/(Td+243.5)) · (1.0007 + 0.00000346·P) · 6.112·exp(17.502·Ta/(240.97+Ta))

Units/notes:
- `S` = solar irradiance (W/m²); `f_db`, `f_dif` = direct-beam and diffuse fractions of `S`;
  `z` = solar zenith angle; `σ = 5.67×10⁻⁸` Stefan-Boltzmann; `e_a` = vapour pressure (hPa);
  `P` = barometric pressure (hPa); `Td` = dew point (°C).
- **Wind `u` here is in metres per *hour*** (Dimiceli appendix Table 1 lists e.g. 6 mph =
  9654 m/hr) — *different unit from the `Tnw` regression's m/s*. This unit split is a live
  porting hazard; unify carefully in code.
- `h` is a fitted convective coefficient. NDFD uses a fixed daytime `h ≈ 0.228` (0 at night,
  switch at 87° zenith); the TSA tool used 0.315. Globe albedo `α = 0.05`, globe emissivity
  `ε = 0.95`, grass albedo `α_es = 0.2`.
- For sky-cover attenuation of `S`, NDFD applies Kasten & Czeplak (1980):
  `R = R₀·(1 − 0.75·n^3.4)`, `n` = fractional sky cover.
- Dimiceli validated `Tg` to within ≈0.67 °C vs an official black-globe sensor (their
  Tables 1–2), so the 0.2-weighted globe term contributes <0.15 °C error to WBGT.

An even simpler **wind-free** globe fallback (Carter et al. 2020, *GeoHealth*, cross-site
regression, [PMC7240860](https://pmc.ncbi.nlm.nih.gov/articles/PMC7240860/)):
`Tg = 0.009624·SR + 1.102·Ta − 0.00404·RH − 2.2776` — shows the same `+`(solar) sign but
drops wind, so it can't deliver the cooling coupling we want.

### Directionality check: wind ↓, solar ↑ (this is the coupling we want)

- **`Tnw`**: `−0.09555·u` (wind lowers) and `+0.001651·S` (solar raises). Direct.
- **`Tg`**: `C = h·u^0.58/… ` grows with `u`. As `u→∞`, `Tg → (B + C·Ta)/C → Ta`; as `u→0`,
  `Tg → (B + 7.68e6)/256000` (hot). So **more wind pulls `Tg` toward air temperature** (a
  drop, whenever the sun has driven the globe above air temp). More `S` raises `B` and hence
  `Tg`. Dimiceli explicitly warns the formula "is very sensitive to the value of the wind
  speed."
- **Composite**: `Ta` fixed, both `Tnw` and `Tg` fall with wind and rise with solar ⇒
  **WBGT decreases with wind, increases with solar**. Confirmed. This is exactly the
  wind→heat cooling coupling ADR-0001 defers to v0.2.

### Counter-example: the BOM / ACSM "simplified WBGT" has no wind or solar

The Australian BOM / sports-medicine simplified index (sWBGT) is **shade-and-moderate-sun
only** — it takes *just* `Ta` and humidity, no wind, no solar
([BOM thermal stress](https://www.bom.gov.au/info/thermal_stress/)):

> sWBGT = 0.567·Ta + 0.393·e + 3.94,   e = (RH/100)·6.105·exp(17.27·Ta/(237.7+Ta))

(`Ta` °C, `e` hPa). Dimiceli themselves cite it as the thing to beat: the BOM equation
"does not take into account variations in the intensity of solar radiation or of wind speed"
(Dimiceli 2011, §VII, quoting Commonwealth of Australia 2010). It bakes in an *assumed*
moderate-sun/light-wind load, so it runs hot in shade and can't move with wind — unusable
for PaceLab's coupling. Kept here only as the explicit counter-example.

## El Helou et al. (2012) — the performance anchor

*Impact of Environmental Parameters on Marathon Running Performance*, PLoS ONE 7(5):e37407
([PMC3359364](https://pmc.ncbi.nlm.nih.gov/articles/PMC3359364/),
[journal](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0037407)).
6 marathons (Berlin, Boston, Chicago, London, NY, Paris) × 2001–2010 = 60 races,
1 791 972 finishers. Weather (air temp °C, humidity %, dew point °C, sea-level pressure hPa)
**averaged over the first 4 h after each start**.

Key extractions (verbatim / from Table 1, Fig. 3):
- **Air-temperature range: 1.7 °C (Chicago 2009) → 25.2 °C (Boston 2004).**
- **Running speed vs air temperature is a quadratic** (2nd-degree polynomial): "running
  speed at all levels is linked to temperature through a quadratic model." Fig. 3: Women P1
  fit `r²=0.27, max = 9.9 °C`; Men Q1 `r²=0.24, max = 6 °C`.
- **Optimum varies 3.8 → 9.9 °C by performance level** (elites optimise nearer 10 °C, faster
  amateurs lower). "the optimal temperatures to run at maximal speed for men and women,
  varied from 3.8 °C to 9.9 °C according to each level of performance."
- **Slope at the optimum (their headline number):** "the optimal temperature at which
  women's P1 maximal running speed was attained was 9.9 °C, and an increase of 1 °C from this
  optimal temperature will result in a speed loss of 0.03 %." Because the fit is quadratic
  and this is *at the vertex*, 0.03 % is the **quadratic coefficient** itself:
  `Δspeed_frac ≈ 0.0003·(Ta − Ta_opt)²` for elite women. (Fig. 3's wing — ~3.9→3.5 m/s over
  10→25 °C, ≈10 % — implies a steeper `k ≈ 0.00044` for the visually-fit curve; slower groups
  are steeper still. So `k ∈ ~0.0003–0.00045` fractional per °C².)
- **Humidity** is the 2nd-ranked parameter (significant for Women P1 and Men's all levels;
  Table 2); dew point and pressure only marginal. Per-race means are in Table 1 (e.g. Boston
  mean 11.8 °C / DP 3.9 °C / RH 62.6 %; Chicago 12.1 / 4.9 / 62.8; London 12.4 / 6.0 / 66.9).
- **WBGT: El Helou did *not* compute it.** They regressed on *air temperature* and only cite
  others' WBGT optima — "these optimal temperatures … are comprised in the optimal
  temperature range of 5–10 °C WBGT found in previous studies … other studies stated that a
  weather of 10–12 °C WBGT is the norm for fast field performance," and (Roberts) medical
  encounters/dropouts "begin to rise" once **WBGT > 13 °C**. This is the crux for the port:
  the air-temp coefficient already *implicitly averages* the sun/humidity of those races, so
  a clean WBGT re-fit needs per-race WBGT they never published (see caveat).

Withdrawal quadratic (secondary, for context): `%withdrawals = −0.59·Ta + 0.02·Ta² + 5.75`
(`r²=0.36`), minimum near 14.75 °C.

## WBGT_ref at PaceLab's reference conditions (arithmetic)

Reference (ADR-0002): **air 10 °C, 50 % RH, wind ≈ 0, solar 0 (shade)**. With `S=0` there is
no radiative load, so the black globe equilibrates to air: **`Tg = Ta = 10 °C`** (the globe
term's solar/wind drivers vanish). Then:

1. **`Tw` (Stull, 10 °C / 50 %):**
   `Tw = 10·atan(0.151977·√58.3137) + atan(60) − atan(48.3237) + 0.00391838·50^1.5·atan(1.15505) − 4.686035`
   `= 8.5910 + 1.55413 − 1.54911 + 1.18753 − 4.686035 = ` **5.10 °C** ⇒ `Twd = 10 − 5.10 = 4.90`.
2. **`Tnw` (NDFD, `S=0`, `u=0`):** `Tnw = Tw + 0.13235·Twd + 0.20249`
   `= 5.10 + 0.13235·4.90 + 0.20249 = 5.10 + 0.6485 + 0.2025 = ` **5.95 °C**.
3. **Composite:** `WBGT_ref = 0.7·5.95 + 0.2·10 + 0.1·10 = 4.166 + 2.0 + 1.0 = ` **7.17 °C**.

**`WBGT_ref ≈ 7.2 °C`.** Cross-checks: it sits squarely inside the literature "5–10 °C WBGT"
optimum El Helou cites — reassuring, since PaceLab's 10 °C air reference is meant to *be* the
thermal optimum. The BOM sWBGT at the same point gives `0.567·10 + 0.393·6.13 + 3.94 =
12.0 °C` — ~4.8 °C hotter, precisely because it assumes a moderate solar load PaceLab's
shade reference does not have. Do **not** use BOM to set `WBGT_ref`.

## Recommended provisional `a`, `b`, `WBGT_ref`

To carry El Helou's *air-temperature* quadratic onto the WBGT axis we need the local slope
`s = dWBGT/dTa` along realistic conditions. In shade (`Tg=Ta`), `WBGT = 0.7·Tnw + 0.3·Ta`;
with `dTw/dTa ≈ 0.6` at fixed 50 % RH, `s ≈ 0.7·0.6 + 0.3 ≈ 0.72`. Substituting
`(Ta − 10) = (WBGT − 7.2)/0.72` into `p = k·(Ta − 10)²`:

`p = k/0.72²·(WBGT − 7.2)² = k/0.5184·(WBGT − 7.2)²`.

- Elite `k = 0.0003` ⇒ `a = 0.00058`.
- Steeper/whole-field `k = 0.00044` ⇒ `a = 0.00085`.

**Recommendation (provisional, flagged for ADR-0006 calibration):**

| param | value | basis |
|---|---|---|
| `WBGT_ref` | **7.2 °C** | Dimiceli/Stull at 10 °C/50 %/shade (arithmetic above) |
| `b` | **2.0** | El Helou's fit is explicitly quadratic — the strongest primary anchor for curvature (supersedes the placeholder 1.5) |
| `a` | **0.0007** | mid-band of the 0.00058–0.00085 transform; ≈ current model magnitude |

Check: a hot shade race (air 25 °C ⇒ WBGT ≈ 7.2 + 0.72·15 = 18 °C) gives
`p = 0.0007·(18 − 7.2)² = 0.0007·116.6 = 8.2 %` — consistent with El Helou's ~7 % (elite) to
~10 % (Fig. 3) and with today's model (`0.0018·15^1.5 = 10.5 %`). Keeping `b=1.5` instead,
with `a ≈ 0.006`, reproduces a similar curve and is acceptable; the `b=2` choice is the more
defensible one because it *is* El Helou's shape.

### Caveats (be honest)

- **Sun double-count risk.** El Helou regressed on *air temperature*; that coefficient
  already averages in whatever sun/humidity those morning races had. If v0.2 feeds *actual*
  WBGT (which explicitly adds a solar load) into a penalty fit on the shade transform above,
  strong-sun races will be penalised *twice*. The clean fix — per-race WBGT recomputed from
  El Helou's Table 1 + solar — is not possible from the paper alone (no per-race irradiance).
  So `a`, `b` here are **provisional**; ADR-0006 variance-minimisation against each athlete's
  own runs is the real calibrator.
- **`s = 0.72` is an estimate**, not measured — it depends on RH and the sun assumption; it
  is the largest single source of uncertainty in `a`.
- **Unit trap:** wind is m/s in the `Tnw` regression but m/hr in the Dimiceli `Tg` formula.
- Dimiceli's `h = a·S^b·cos(z)^c` regression coefficients are *not* published numerically in
  the 2011 paper (only NDFD's fixed `h≈0.228` daytime); treat `h` as the one coefficient we
  cannot fully verify from a primary source.
