# Canonical input is FIT/GPX per-point files; COROS MCP is a secondary adapter

Probed the COROS Training Hub MCP directly (July 2026): `get_activity_detail` returns
per-lap GPS (start/end, ~500 m granularity), a derived slope segmentation, and rich
summaries — but **no per-point `(t, lat, lon, ele)` track**, and no MCP tool exposes one.
Grade and wind models need a dense track, so the COROS API cannot be the primary source.

**Decision:** ingest **FIT/GPX files** (exported from the COROS app or Strava) as the
canonical per-point input. Every source is an adapter onto the internal per-point record
`(t, lat, lon, ele, dist, speed, hr?)`; the FIT adapter is the load-bearing one.

The COROS MCP is kept as a **secondary adapter** for activity discovery, summary metrics,
and validation/calibration inputs it uniquely offers: **running power** (a candidate effort
proxy), COROS's own **`adjustedPace`** (a baseline to sanity-check NP/AP against), and its
attached **`weather`** block (a cross-check, though we prefer Open-Meteo's moving-position
interpolation over COROS's single AccuWeather reading).

This confirms R-2 as resolved rather than open, and prevents re-attempting to derive a
track from the API.
