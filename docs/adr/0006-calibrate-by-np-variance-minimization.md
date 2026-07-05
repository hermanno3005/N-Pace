# Calibrate personal coefficients by NP-variance minimization, not effort-proxy regression

Personal coefficients (Phase 3, FR-8) are fit primarily by **choosing the coefficient set
that minimizes Normalized Pace variance within windows of ~constant fitness** — a proxy-free
method — rather than by regressing pace residuals against an effort proxy as FR-8.1
originally specified. Power-based regression is retained as a secondary cross-check.

Both effort proxies are circular against the coefficient that most needs care:

- **HR** inflates with heat independent of pace (cardiac drift), so holding HR constant to
  define "same effort" contaminates the *heat* coefficient — the one R-4 flags as hardest.
- **COROS running power** is partly modeled from pace and slope, so it biases the *grade*
  coefficient.

Variance minimization sidesteps both: the correct coefficients are, by definition, the ones
that make NP most stable over a constant-fitness window (this is exactly V-3). It optimizes
the metric's own purpose directly.

## Consequences

- v0.1 must **persist per-segment conditions and per-segment observed vs normalized pace**,
  not just activity aggregates — the Phase-3 optimizer needs the raw material regardless of
  which method ultimately wins. This raises the bar on FR-9.1 storage.
- Still governed by FR-8.2: report fit quality and fall back to population defaults on
  sparse data or insufficient condition spread within a window.
