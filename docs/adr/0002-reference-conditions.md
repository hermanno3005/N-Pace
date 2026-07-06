# Freeze reference conditions at flat / 10 °C / 50% RH / no wind / home altitude

Normalized Pace normalizes to a fixed baseline where every pace penalty is zero:
**0% grade, 10 °C, 50% relative humidity, no wind, the athlete's home altitude.** Frozen
once — changing it would invalidate every historical NP number.

Reference temperature is **10 °C** (endurance thermal optimum, ~10–12 °C in the literature)
rather than the athlete's local median temperature. This makes NP mean "equivalent ideal
cool-weather pace" — directly comparable to PB / race-day conditions — which is the point
of NP: to strip condition noise and expose fitness (V-3). A local-median baseline was
rejected because, while it keeps corrections small, it makes NP incomparable across
athletes and against cool race conditions.

Home altitude (not sea level) is the reference so that running at home in still air incurs
no spurious air-density penalty; the home-elevation value lives in config.

## Amendment (v0.2, ADR-0010)

The reference gains **no solar radiation** (shade). WBGT depends on solar load, so the
reference needs a solar value to define the heat-penalty zero-point; "no sun" is also the
right meaning — an ideal cool race day isn't run in blazing sun. This extends the frozen set
without changing any existing term; WBGT_ref is then the WBGT at 10 °C / 50% RH / no wind /
no sun.
