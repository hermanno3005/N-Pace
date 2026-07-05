# Dampen the Minetti grade penalty with a grade-sensitivity factor

The grade pace penalty is the raw Minetti energy ratio scaled by a **grade-sensitivity
factor `k_grade`** (default 0.45), not the undamped constant-power value.

Minetti (2002) gives the *energy* cost of running vs gradient, and the constant-power
relation `v ∝ 1/C` converts it to a pace penalty exactly — *if* metabolic power is held
constant. But real runners hold something between constant power and constant pace on
hills, so pace is less grade-sensitive than `1/C` implies. Undamped, a 6% climb produced a
+37% pace penalty — roughly 2× empirical grade-adjusted-pace curves — which violates NFR-1
(magnitudes should match sport-science expectations) and makes every hilly run's NP look
implausibly fast.

`k_grade` keeps Minetti's *shape* (asymmetry, the slightly-downhill minimum, the ±45% cap)
while scaling magnitude to the empirical neighbourhood; `k_grade = 1.0` recovers the pure
model. It is exactly the "athlete hill strength" coefficient FR-4.3 calls for, and the
parameter ADR-0006's variance-minimisation calibration will personalise. A data-driven
empirical GAP curve was rejected as less transparent (NFR-2).

## Grounded default: k_grade = 0.40

Fit against published GAP (`docs/research/grade-adjusted-pace.md`): **0.40** is the
least-squares fit of `k·(C(i)/C(0)−1)` to empirical GAP over 0–10% uphill (implied-k band
0.38–0.44), landing a +6% climb at +16% to match Strava's ~+15%. Trimmed from the
provisional 0.45, which sat at the top of the band and ran slightly hot. Primary anchors:
Minetti 2002 (polynomial + Table 2), Strava Engineering "An Improved GAP Model" (6M runs).

## Known limitation: the scalar is uphill-only

A single multiplicative `k_grade` is adequate **uphill 0–10%** but not downhill:

- Downhill wants a lower k (~0.33) — an uphill/downhill asymmetry a scalar can't express.
- Worse, past the ~−18% Minetti cost minimum the constant-power *shape* is wrong: Strava's
  empirical curve returns to ~0% benefit by −18% while damped-Minetti still shows ~−20%. No
  value of k fixes the shape, so **steep descents are over-credited** (NP too slow there).
- The whole grade model decorrelates from economy past ±20% (Breiner 2021).

Acceptable for v1 road running (gentle profiles). A proper fix — an empirical downhill cap
or a separate downhill treatment — is deferred; flagged here so it isn't mistaken for a bug.
