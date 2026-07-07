# First real calibration run — findings (July 2026, 55 runs / 27 steady)

`pacelab calibrate` on the athlete's cleaned 2026 season (model 0.2.1). Report-only; nothing
applied. Method per ADR-0006: steadiness-filtered, within-run k_grade regression,
between-run WBGT regression.

## k_grade: not identifiable from this terrain — keep the default 0.40

Within-run fit says pace responds to grade-energy at only **+0.017** (IQR ±0.019, 27 runs) vs
the researched default 0.40 (ADR-0007). The HR cross-check exposes why this is *not* a real
athlete coefficient: **HR's response to grade is also ≈0 (−0.043)** — and constant pace at
constant effort on a real climb is physically impossible. Conclusion: on gentle, short
Munich rollers the measured grade signal is too small and too smeared to identify k —
baro noise is ~1–2% grade per 100 m segment, HR lags 30–60 s across segment boundaries, and
the hills are shorter than the smoothing horizon. The tight IQR reflects systematic
attenuation (errors-in-variables + smearing), not precision. **FR-8.2 verdict: data
insufficient; population default stands.** A mountain race / hill-repeats would identify it.

## wbgt_a: real signal, season-confounded; likely over-penalized

Three estimates of the same coefficient:

| estimate | value | meaning |
|---|---|---|
| no time term | 0.00046 | raw hot-slower signal, fitness change included |
| linear drift term | 0.00008 | drift term eats the heat signal (collinear) |
| **21-day hot/cool pairs (n=38)** | **0.00014** | cleanest causal cut: nearby-in-time contrast |

One season's WBGT rises monotonically with date, so heat and fitness drift are nearly
collinear — a single season cannot fully separate them (El Helou had 60 marathons). But the
windowed estimate sitting **~5× below the ported default (0.0007)** points the same way as
ADR-0010's sun-double-count caveat: the WBGT curve likely over-penalizes this athlete.

**Decisive next test before changing anything: the HR-conditioned fit** — pace at equal HR
on hot vs cool days (intent-proof: deliberately jogging in heat can't masquerade as a heat
penalty). HR is persisted per segment as of model 0.2.1, so this is now computable.

## Method lessons folded back

- Junk micro-segments and a solar-less weather cache were both caught *by* the calibration
  run itself (fixed in 0.2.1) — variance-minimization doubles as a data-quality audit.
- A single linear drift term is the wrong deconfounder for one monotonic season; windowed
  pairing is the honest structure for the heat fit.
