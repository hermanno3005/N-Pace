# Wind is computed and reported, but excluded from the applied NP in v1

The wind penalty is calculated and shown in every activity's cost decomposition, but by
default it is **not** removed from observed pace when computing the headline Normalized
Pace in v1. NP is adjusted for **grade + heat only**; wind is informational. A config flag
can opt wind into the applied NP.

NP exists to *reduce* variance by stripping condition noise (V-3). Grade (own baro
elevation) and heat (temperature, smooth over the weather grid) are high-confidence. Wind
is derived from a ~25 km reanalysis grid with no terrain sheltering and is explicitly
low-confidence (FR-6.4, R-1); applying it risks *injecting* variance into NP rather than
removing it. So wind must *earn* its place in the headline number: V-3 becomes the test —
promote wind into applied NP only once including it is shown to reduce NP variance on real
data.

Forward AP (race planning) is unaffected: there a known forecast wind is included
explicitly. This decision governs only the retrospective NP default.

## Consequences

- "Environmental cost" now has two scopes: the **applied cost** (grade + heat) removed to
  produce NP, and the fuller **reported decomposition** (grade + heat + wind). Outputs must
  keep the distinction visible so NP is never silently conflated with the full decomposition.
