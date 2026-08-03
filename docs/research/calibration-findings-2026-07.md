# First real calibration run — findings (July 2026, 55 runs / 27 steady)

`pacelab calibrate` on the athlete's cleaned 2026 season (model 0.2.1). Report-only; nothing
applied. Method per ADR-0006: steadiness-filtered, within-run k_grade regression,
between-run WBGT regression, plus the HR-conditioned heat fit of ADR-0014.

Two runs are folded in here: the original (which this document was written from) and a
**rerun on 2026-07-29** that ADR-0014's fit and the `63c33f2` normalisation fix made
necessary. Every number below is from the rerun unless it says otherwise — with one standing
exception: `pacelab calibrate` ships three fits (`fit_k_grade`, `fit_wbgt_a`,
`fit_hr_conditioned_wbgt_a`), so the **21-day pairing** row has no shipped implementation and
is carried over from the original run unreproduced.

## k_grade: not identifiable from this terrain — keep the default 0.40

Within-run fit says pace responds to grade-energy at only **+0.020** (IQR 0.038 — the full
inter-quartile width, as `Fit.spread` reports it — over 27 runs; it read +0.017, spread 0.019,
on the corpus as it stood in the first run — same verdict either way) vs
the researched default 0.40 (ADR-0007). The HR cross-check exposes why this is *not* a real
athlete coefficient: **HR's response to grade is also ≈0 (−0.043)** — and constant pace at
constant effort on a real climb is physically impossible. Conclusion: on gentle, short
Munich rollers the measured grade signal is too small and too smeared to identify k —
baro noise is ~1–2% grade per 100 m segment, HR lags 30–60 s across segment boundaries, and
the hills are shorter than the smoothing horizon. The tight IQR reflects systematic
attenuation (errors-in-variables + smearing), not precision. **FR-8.2 verdict: data
insufficient; population default stands.** A mountain race / hill-repeats would identify it.

## wbgt_a: real signal, season-confounded; over-penalized once effort is held constant

Four estimates of the same coefficient (default 0.0007):

| estimate | value | meaning |
|---|---|---|
| no time term | 0.00046 | raw hot-slower signal, fitness change included |
| linear drift term | 0.00063 | **reran** — see the note below |
| 21-day hot/cool pairs (n=38) | 0.00014 | nearby-in-time contrast (carried over) |
| **at equal HR (n=26 / 1910 seg)** | **0.00009** | intent-proof cut: effort held constant |

> **The withdrawn 0.00008 row is now 0.00063.** `fit_wbgt_a` used to normalise the heat
> coefficient by the regression intercept — pace extrapolated back to 1 Jan 1970, wrong by
> decades of drift. Normalising against the mean heat-removed pace instead (`63c33f2`) moves
> the row *up*, past the raw no-time-term figure, to sit level with the ported default. So the
> correction did not merely rescale a low estimate: the linear-drift fit is now the highest of
> the four, having previously been the lowest. **A single linear drift term over one monotonic
> season attributes the heat/fitness split essentially arbitrarily**, and its number should
> not be read as evidence in either direction.
>
> The observed move is ~8×, against the "roughly 4×" the fix's commit message predicted from a
> synthetic probe (planted `a=0.001` came back `0.000227`). Both are right: 4× is how far the
> bug displaced a known coefficient, 8× is how far this corpus's estimate actually travelled —
> the gap is the drift term reattributing variance once the baseline stopped being wrong.

One season's WBGT rises monotonically with date, so heat and fitness drift are nearly
collinear — a single season cannot fully separate them (El Helou had 60 marathons). The two
cuts that *do* control the confound rather than model it — 21-day pairing (0.00014, carried
over unreproduced) and the HR-conditioned fit (0.00009, rerun) — land **5× and 8× below the
ported default**, and agree with
each other far more closely than either between-run fit agrees with anything. That points the
same way as ADR-0010's sun-double-count caveat: the WBGT curve over-penalizes this athlete.

### The HR-conditioned fit: ran, did not abstain

Run against the athlete's database on 2026-07-29 (55 analysed runs, 27 steady, model 0.2.1).
ADR-0014's guards all passed — this is a reported estimate, not an abstention:

| diagnostic | value | reading |
|---|---|---|
| `wbgt_a` at equal HR | **0.00009** | 8× below the 0.0007 default |
| run-mean sensitivity refit | 0.00004 | autocorrelation-robust; *lower* still, not higher |
| HR coefficient | −1.95 s/km per bpm | right sign and plausible size — higher HR, faster |
| corr(HR, heat) | **−0.31** | well clear of the 0.80 abstain threshold |
| R² | 0.42 | optimistic — segments within a run are autocorrelated |
| residual | ±26.4 s/km | comparable to the between-run fits |

The correlation is the number this fit existed to produce. At **−0.31** effort and heat are
not collinear here, so the guard never fired and the two are separable — and the sign says
the athlete ran hot days at *slightly lower* HR, i.e. backed off. That is exactly the
behaviour a raw hot-slower regression would misread as a heat penalty and this fit does not:
it is why 0.00009 sits below 0.00046, and why the low figure is the trustworthy one.

**Robustness.** Both heat fits take `k_grade` from the within-run fit (0.020), which the
`k_grade` section above says is not identifiable. Refitting with the population default 0.40
instead moves the HR-conditioned estimate 0.00009 → 0.00006 and the drift row 0.00063 →
0.00062, so nothing here rests on the unidentified `k`. The corpus carries **3 runs still at
`model_version` 0.2.0** (also still provisional, i.e. forecast-tier weather); one of them is
steady and enters the between-run fit. Excluding it moves the drift row to 0.00069 and leaves
the HR fit untouched (it was never in it).

**Continuity.** `pacelab.db` is not versioned, so there is no way to diff the corpus against
the one the original run saw — and `k_grade` did move 0.017 → 0.020 between the two runs, so
it did change. The available check is the no-time-term estimate: refitting it ad hoc from the
same library (there is no shipped fit for it) still gives **0.00046**, matching the original
to both its significant figures. That is weak evidence of an unchanged corpus and strong
evidence that whatever changed does not move the heat coefficient.

**Fit window:** 2026-01-03 → 2026-07-05, run-mean WBGT −5.4 °C to 23.4 °C, 16 of 27 runs
above the 7.2 °C reference — a real spread, not a summer-only sliver.

### What this licenses

A `wbgt_a` reduction is now defensible. The two confound-controlled cuts bracket it at
**0.00009–0.00014** — 5× to 8× below the ported 0.0007 — and anything inside that range is
supportable; the midpoint of roughly **0.0001** is the obvious candidate.

One caveat on the bracket's provenance: only its lower bound was rerun. The upper bound
(0.00014) is the 21-day pairing, which has no shipped fit and is carried over from the
original run, so the bracket is **mixed evidence** rather than a single reproduced result.
This does not weaken the direction — the reproduced cut is the *lower* of the two, so a
5–8× reduction is if anything conservative — but #27 should not read 0.00014 as freshly
confirmed. Reproducing it means shipping a windowed-pairing fit. It is deliberately
not the 0.00004 run-mean figure: that refit is the sensitivity check, not the estimate.
Changing the coefficient, bumping `model_version`, and letting the recompute path republish
the corpus is #27's call, not this document's.

**#27 acted on this.** `wbgt_a` is now **0.0001** — the bracket midpoint — in `Config`, with
`model_version` at **0.3.0**. The ported 0.0007 stays as `DEFAULT_WBGT_A` in `models/heat.py`,
the population default the athlete's value departs from (ADR-0009). The bump makes every
stored row stale, so ADR-0016's recompute pass rewrites and republishes the corpus, snapshot
first (ADR-0018).

## Method lessons folded back

- Junk micro-segments and a solar-less weather cache were both caught *by* the calibration
  run itself (fixed in 0.2.1) — variance-minimization doubles as a data-quality audit.
- A single linear drift term is the wrong deconfounder for one monotonic season; windowed
  pairing is the honest structure for the heat fit. The rerun above makes this sharper than
  the original diagnosis did: **an estimator that unstable is reporting the arbitrariness of
  the heat/fitness split, not the split.**
- **Conditioning on effort beat modelling the confounder.** Holding HR constant separated
  heat from fitness where a time term could not, and it came with its own falsifier: the
  HR–heat correlation says whether the separation was possible at all (−0.31: yes).
- A coefficient expressed as a *fraction* needs an explicit, origin-free baseline. Dividing
  by a regression intercept quietly imports whatever the other covariates extrapolate to at
  zero — here, the athlete's pace half a century before he was running.
