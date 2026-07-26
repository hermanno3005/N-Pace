# For heat calibration, effort is defined as heart rate

The HR-conditioned heat fit (part of `pacelab calibrate`) estimates `wbgt_a` by holding
**heart rate** constant: the heat penalty is *how much you slow to sustain a given HR as
WBGT rises*. Model, over warmed-up steady-run segments:

    pace_gc = b₀ + b_HR·HR + b_t·time_in_run + b_W·(WBGT − 7.2)²

`a` derives from `b_W`; the HR term holds effort fixed, `time_in_run` absorbs within-run
cardiac drift, and WBGT² carries only the between-run heat contrast.

## Why this doesn't contradict ADR-0006

ADR-0006 *rejected* HR as the calibration effort-proxy: "HR inflates with heat independent
of pace (cardiac drift), so holding HR constant contaminates the heat coefficient." That
objection assumes effort means **metabolic rate**, for which HR is a biased proxy in heat.
Here we make a different, deliberate choice: **effort *is* HR.** Under that definition
"pace at a given HR" is exactly what NP should preserve, and the pace-at-fixed-HR decrement
in heat is the penalty by construction — not a contamination. The cardiovascular strain of
heat is *included in* the penalty on purpose, because for a runner "the pace I can hold at
my tempo HR" is the meaningful quantity.

The trade-off recorded honestly: HR ≠ VO₂, so this coefficient reflects cardiovascular heat
cost, not pure metabolic cost; the two differ by cardiac drift. We do not try to model drift
out (fragile, and drift is partly the heat signal). This is why the fit is **intent-proof**:
an easy hot jog lands at low HR and is absorbed by the HR term, so it cannot masquerade as a
heat penalty — the property variance-minimization alone could not guarantee.

## Guards (FR-8.2)

Report-only. Abstains — keeping the current `wbgt_a` — when HR and WBGT are too **collinear**
to separate (running easy-when-hot, hard-when-cool), when WBGT spread is too small, or on
thin data. Always reports diagnostics (HR-coefficient sign, WBGT–HR correlation, R² flagged
optimistic for segment autocorrelation, and a per-run-mean sensitivity refit). Applying a
fitted value (FR-8.3 persisted calibration) is a separate block, built only if the estimate
earns trust.
