# PaceLab — Environment-Adjusted Pace Engine

The domain language for a single-user tool that takes a recorded run and computes what
the athlete's pace *would* have been under reference conditions at the same effort, by
estimating and removing the slowing effect of grade, heat, and wind.

## Language

### Core metrics

**Normalized Pace (NP)**:
The retrospective metric: observed pace with the estimated environmental cost removed —
the pace the athlete would have held under reference conditions at the *same effort*.
_Avoid_: adjusted pace (that's the forward metric), corrected pace.

**Adjusted Pace (AP)**:
The forward/planning metric: a reference or goal pace projected *into* a given set of
conditions, to predict actual pace and splits. The inverse transform of NP.
_Avoid_: predicted pace, target pace.

**Effort**:
The physiological work rate held constant across the normalization — the thing that is
assumed equal between the observed run and its normalized counterpart. NP answers "same
effort, reference conditions, what pace?"
_Avoid_: intensity, exertion (when the specific held-constant quantity is meant).

### Ingestion

**Activity**:
One recorded run — the unit of ingestion, normalization, and storage. NP and the cost
decomposition are computed per activity.
_Avoid_: workout (COROS's term), session, run (when the record is meant).

**Trackpoint**:
One sample of the canonical per-point record `(t, lat, lon, ele, dist, speed, hr?)`. The
ordered stream of trackpoints is the **track**. Every input source (FIT, GPX, an API) is an
adapter that must yield this record, or it cannot feed the grade and wind models.
_Avoid_: fix, sample, waypoint.

### The cost model

**Pace Penalty**:
The common currency of the engine. A fractional increase in pace (a slowing) attributed
to one condition on one segment, at constant effort. Grade, heat, and wind each produce a
pace penalty; the engine combines penalties in pace space, never in mixed units. Energy-
based models (grade, wind) are converted to a pace penalty via the constant-power relation
`speed ∝ 1 / cost-of-transport` before combining.
_Avoid_: cost factor, slowdown, handicap.

**Mechanical Penalty**:
The pace penalty from the two genuine *energy* costs — grade and wind drag — combined
additively in energy (they are independent power draws). Written `p_mech`. Heat is not part
of it; heat scales the result rather than adding to it.
_Avoid_: energy penalty, physical cost.

**Applied Cost**:
The subset of penalties actually removed from observed pace to produce NP. In v1 this is
grade + heat only — wind is computed and reported but excluded by default (see ADR-0005).
_Avoid_: total cost, environmental cost (those name the fuller reported set).

**Environmental Cost** (a.k.a. the decomposition):
The full estimated slowing from grade + heat + wind together, reported per activity even
when not all of it is applied. NP removes only the *applied cost*; the decomposition shows
everything. Keep the two distinct in output — NP is never the whole decomposition.
_Avoid_: correction, penalty (when the aggregate is meant).

**Heat-Stress Index**:
The scalar fed into the heat penalty curve — in v1, **Heat Index** (from air temperature and
relative humidity, wind excluded). Distinct from the penalty itself: the index measures the
environment, the curve maps it to a slowing. v0.2 target: WBGT.
_Avoid_: feels-like, apparent temperature (that's the wind-inclusive v0.2 variant).

**Headwind Component**:
The signed projection of the wind vector onto a segment's bearing: positive against the
runner (a headwind, costly), negative behind (a tailwind, assisting). The only wind quantity
the wind model consumes.
_Avoid_: relative wind, effective wind.

**Segment**:
A consecutive pair (or short window) of track points over which grade, bearing, and
conditions are treated as locally constant. The unit every model operates on.
_Avoid_: split, lap, interval (those are athlete-facing groupings, not the model's unit).

**Reference Conditions**:
The frozen baseline NP normalizes to, at which every pace penalty is zero by definition:
**0% grade, 10 °C, 50% RH, no wind, home altitude**. Chosen so NP reads as "equivalent
ideal cool-weather pace." Frozen — see ADR-0002.
_Avoid_: ideal conditions, baseline (unqualified).
