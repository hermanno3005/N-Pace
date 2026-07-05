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

## Status

The **0.45 default is provisional** (eyeballed to land a 6% climb near empirical GAP);
worth grounding against published GAP tables before it hardens.
