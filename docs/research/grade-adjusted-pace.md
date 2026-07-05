# Grade-adjusted pace and the `k_grade` damping coefficient

Grounding the grade-sensitivity factor `k_grade` (ADR-0007) against published GAP data.

## Question

PaceLab's grade pace penalty is `p_grade = k_grade · (C(i)/C(0) − 1)`, where `C(i)` is the
Minetti et al. (2002) running energy-cost polynomial and `(C(i)/C(0) − 1)` is the
constant-power pace penalty implied by `v ∝ 1/C`. Undamped (`k_grade = 1.0`) this gives
**+37% at +6% grade**, ~2× empirical GAP curves. What single `k_grade` best reconciles the
model with published GAP, is a scalar adequate, and what should the default be?

Convention: `p_grade` is the fractional slowing at constant effort — a runner's actual pace
is `(1 + p_grade)×` their flat-equivalent pace. Strava's "GAP adjustment" is the reciprocal
view (equivalent flat pace as a multiple of clock pace); the magnitudes are directly
comparable, e.g. `p_grade = +0.15` ⇔ a GAP ~15% faster than clock pace.

## Sources

### 1. Minetti et al. 2002, *J Appl Physiol* 93:1039–1046 (primary)

The paper this whole model rests on. The running-cost polynomial is stated verbatim
(p. 1042, [softrun mirror](http://www.softrun.fr/J%20Appl%20Physiol-2002-Minetti-1039-46.pdf),
[runscribe mirror](http://runscribe.com/wp-content/uploads/power/Minetti2002.pdf)):

> Cr*i* = 155.4*i*⁵ − 30.4*i*⁴ − 43.3*i*³ + 46.3*i*² + 19.5*i* + 3.6 (R² = 0.999)

Measured level cost `Cr = 3.40 ± 0.24 J·kg⁻¹·m⁻¹` (the polynomial *intercept* is 3.6;
PaceLab uses `C(0) = 3.6`, the regression value). Table 2 measured `Cr` (J·kg⁻¹·m⁻¹), and
the ratio vs the 3.6 intercept:

| slope | −0.45 | −0.20 | −0.10 | 0 | +0.10 | +0.20 | +0.45 |
|---|---|---|---|---|---|---|---|
| Cr measured | 3.92 | **1.73** | 1.93 | 3.40 | 5.77 | 8.92 | 18.93 |
| ratio vs 3.6 | 1.09 | 0.48 | 0.54 | (0.94) | 1.60 | 2.48 | 5.26 |

Key qualitative results, verbatim: *"Downhill, Cr was some 40% lower than reported in the
literature for sedentary subjects"* (these were fell-runners); the **minimum measured `Cr`
is at ≈ −0.20** (1.73), and the fitted polynomial minimum is at **−18.1% (ratio 0.495)**.
Note the measured downhill costs (min ratio ≈ 0.48) are *deeper* than the smoothed
polynomial — Minetti's subjects were unusually economical downhill.

**This is the undamped physiological ceiling: a −40% to −50% cost reduction at the best
downhill.** It is the "constant-power" number PaceLab inherits and the thing empirical GAP
curves dampen.

### 2. Strava — "An Improved GAP Model", Strava Engineering (primary, empirical)

Strava's data-driven GAP fit over **~6 million runs from 240k athletes**
([medium.com/strava-engineering](https://medium.com/strava-engineering/an-improved-gap-model-8b07ae8886c3)).
This is the single best empirical anchor because it is a large-N real-world regression, not
a treadmill lab. Verbatim numbers:

- Old (Minetti-shaped) model: *"minimum pace adjustment of about 0.5 at −18%"* — i.e. the
  old model was ≈ the **undamped** Minetti ratio.
- New (empirical) model: *"minimum pace adjustment of 0.88 at −9%, and by −18% the
  adjustment is back to 1.0"*.
- *"an ideal downhill running gradient would not give more than a 10% speed benefit."*

So Strava explicitly **abandoned the constant-power downhill shape**: the empirical best
downhill is only ~10–12% cheaper (adjustment 0.88), vs Minetti's ~40–50%, and the benefit
vanishes by −18% rather than peaking there. The methodology is *"inspired by … C.T.M. Davies
and Alberto Minetti"* but re-fit to data
([Strava Support](https://support.strava.com/hc/en-us/articles/216917067-Grade-Adjusted-Pace-GAP);
the support page also notes GAP *"is highly dependent on accurate elevation data"*).
Strava does **not** publish the full grade→coefficient table.

### 3. Strava GAP "per-1%-grade" rule of thumb (secondary, widely cited)

The commonly quoted linearisation — **+2.5% effort per 1% uphill; −1.5% per 1% downhill for
−1% to −10%, flattening past −10%** — appears across GAP calculators and explainers
([RunDida](https://rundida.com/tools/gap-calculator/),
[personalwellnesstracking](https://personalwellnesstracking.com/strava-gap-grade-adjusted-pace/)).
I could **not** verify these exact coefficients on a Strava-owned page (Strava's own pages
give only "peaks around −10%"), so treat them as a high-usage secondary reconstruction, not
a Strava primary. They are nonetheless the most concrete uphill anchor available and are
consistent with source 2's downhill magnitude (2.5×… no — 1.5%×9 ≈ 13.5% ≈ Strava's 0.88).

### 4. Running Writings GAP calculator — Minetti (2002) + Black et al. (2018) (primary method)

An independent, physiologically rigorous implementation
([apps.runningwritings.com/gap-calculator](https://apps.runningwritings.com/gap-calculator/)):
metabolic cost from Minetti, *"find equivalent flat-ground speed matching that power"* — i.e.
**exactly PaceLab's constant-power model, undamped (`k_grade = 1.0`)**. It deliberately does
*not* dampen, and its author argues Strava under-adjusts. It is therefore a witness for the
*undamped* column below, not an independent empirical target.

### 5. Breiner et al. 2021, *Front Physiol* 12:697315 (peer-reviewed, adequacy evidence)

*"Level, Uphill, and Downhill Running Economy Values Are Correlated Except on Steep Slopes"*
([PMC8281813](https://pmc.ncbi.nlm.nih.gov/articles/PMC8281813/)). Economy correlates across
level/uphill/downhill *"at all slopes"* **except +20%** (bouncing/elastic-return mechanisms
are lost), and the **optimum downhill slope ≈ −17.3%** (matching Minetti −18% and Strava
−18%). Read across to GAP: a single grade→pace mapping is defensible within ~±15% but a
fixed scaling *cannot* hold at ±20% because the underlying economy relationship itself
changes.

## The `k_grade` fit

PaceLab undamped (`k_grade = 1.0`), from the Minetti polynomial with `C(0)=3.6`, vs the
source-3 Strava-linear target, with the implied `k` = target ÷ undamped at each grade:

| grade | C(i) | ratio | **undamped p_grade** | Strava-linear target | **implied k** |
|---:|---:|---:|---:|---:|---:|
| −15% | 1.836 | 0.510 | −49.0% | −15.0%¹ | 0.31 |
| −10% | 2.152 | 0.598 | −40.2% | −15.0% | 0.37 |
| −8%  | 2.357 | 0.655 | −34.5% | −12.0% | 0.35 |
| −6%  | 2.606 | 0.724 | −27.6% | −9.0%  | 0.33 |
| −4%  | 2.897 | 0.805 | −19.5% | −6.0%  | 0.31 |
| −2%  | 3.229 | 0.897 | −10.3% | −3.0%  | 0.29 |
| +2%  | 4.008 | 1.113 | +11.3% | +5.0%  | 0.44 |
| +4%  | 4.451 | 1.236 | +23.7% | +10.0% | 0.42 |
| +6%  | 4.927 | 1.369 | **+36.9%** | +15.0% | 0.41 |
| +8%  | 5.433 | 1.509 | +50.9% | +20.0% | 0.39 |
| +10% | 5.968 | 1.658 | +65.8% | +25.0% | 0.38 |
| +15% | 7.417 | 2.060 | +106.0% | +37.5% | 0.35 |

¹ downhill target held flat past −10% per source 2/3. The +6% row reproduces the ADR-0007
"+37%, ~2× empirical" claim (37% vs Strava-linear 15%).

**Least-squares single `k`** (minimising Σ(target − k·undamped)², i.e. `k = Σ(u·t)/Σu²`):

- Uphill, 0 to +10%: **k = 0.39**
- Downhill, 0 to −10%: **k = 0.35**
- Independent check against source 2's empirical anchor (−9% → adjustment 0.88, i.e.
  target −0.12): `k = −0.12 / −0.375 = 0.32`.

Implied `k` sits in a **0.38–0.44 band uphill** (drifting down as grade rises, because the
Minetti penalty is convex while the empirical target is ~linear) and a **0.29–0.37 band
downhill**. A single scalar of **~0.40** is the honest uphill centre; **~0.33** the downhill
centre.

## Is a single scalar adequate?

**Uphill, 0–10% (the road range): yes.** Implied `k` varies only 0.38→0.44, and Breiner
confirms economy scales cleanly with level here. A scalar `k ≈ 0.40` fits with <±3
percentage-point pace error across the range — well inside GAP's own elevation-noise budget
(source 2). This is the regime PaceLab targets.

**Downhill: marginal-to-inadequate, for two independent reasons.**

1. **Asymmetric magnitude.** Downhill wants `k ≈ 0.33`, uphill `k ≈ 0.40` — a fixed
   multiplicative `k_grade` on a shape that is *already* asymmetric can't also correct an
   asymmetric *damping*. A single scalar tuned uphill over-predicts downhill benefit by
   ~15–20% (relative).
2. **Wrong shape past the minimum.** Even damped, the constant-power model keeps Minetti's
   deep U: at −18% it still shows a benefit (`0.40 × −50% = −20%`), whereas Strava's
   empirical curve is **back to ~0% by −18%** (source 2) and Breiner's optimum is −17.3%.
   Strava *deleted* exactly this shape when it moved off the Minetti downhill. No value of
   `k_grade` recovers it — the failure is in the shape, not the scale.

**Steep (>±15%): scalar fails.** Implied `k` keeps falling (0.35 at +15%), and Breiner shows
the economy relationship itself decorrelates by ±20%. Out of scope for road GAP, but a
hard ceiling for any scalar. ADR-0007's ±45% cap is the right guard here.

## Recommendation

**Default `k_grade` = 0.40**, defensible over **0 to +10% uphill road grades**.

- One-line justification: 0.40 is the least-squares fit of the damped Minetti penalty to the
  Strava-linear GAP target over 0–10% uphill (implied-`k` band 0.38–0.44), and lands a +6%
  climb at +16% — matching Strava's ~+15% rather than the undamped +37%.
- This trims the provisional 0.45 (ADR-0007), which sits at the top of the defensible band
  and runs ~1–2 pp hot at common road grades; 0.40 is better centred. 0.45 is not *wrong*,
  just the upper edge.
- **Downhill caveat:** a single scalar over-states downhill benefit. If downhill accuracy
  matters, either use a lower downhill `k ≈ 0.33`, or (better) replace the sub-minimum
  branch with an empirical clamp toward 0 by −18% (Strava/Breiner), since no scalar fixes
  the shape. Flagged for v0.2; the ADR-0006 variance-minimisation calibration will also pull
  `k_grade` toward each athlete's realised value.
- **Hard bounds:** trust only within ±15%; keep the ±45% cap. `k_grade = 1.0` recovers the
  pure constant-power (Running Writings / undamped-Minetti) model.
