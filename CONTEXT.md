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
effort, reference conditions, what pace?" **In heat calibration, effort is operationalised
as heart rate** (ADR-0014): the heat penalty is the pace decrement needed to hold a given HR
as conditions worsen. This is a calibration measurement choice, not a redefinition of NP,
which is still computed from the physics.
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

**Source Adapter**:
Parses one activity *file* (FIT, GPX) into a track. Knows file formats, never the network.
_Avoid_: parser, reader, loader.

**Provider**:
A remote platform PaceLab fetches activities from (v1: intervals.icu). Distinct from a
Source Adapter: a Provider *lists* activities and *downloads* their original files by id; it
knows the network and credentials, never file formats. It downloads into the FIT cache, then
Source Adapters take over. Scoped to one **Account** (credentials injected), so multiple
users are multiple Providers, not a rewrite.
_Avoid_: client, connector, integration (when the role is meant).

**Activity Reference**:
The lightweight identity of a remote activity from a Provider's listing — its id, date, and
type — before its file is downloaded. Distinct from the full Activity.
_Avoid_: stub, summary, header.

**Account**:
One athlete's credentials and identity on a Provider (an API key + athlete id). The unit of
scoping for storage and cache: every stored result and cached file belongs to an Account.
v1 has exactly one; the seam keeps additional ones data, not a redesign.
_Avoid_: user, profile, login.

### Publishing

**Annotation**:
The marker-delimited PaceLab block written into an activity's public description/note,
showing NP, observed pace, and the per-component decomposition. Not a Strava comment —
comments cannot be created via Strava's API; editing the description is the mechanism.
_Avoid_: comment, post.

**Publish**:
Writing an activity's annotation to its publish targets. Ambient once authorised (happens
during sync), idempotent (re-publishing replaces PaceLab's own block, never stacks it,
never touches the athlete's own text).
_Avoid_: share, upload, sync (that's ingestion).

**Publish Target**:
A remote surface an annotation is written to — v1: the intervals.icu activity description,
which doubles as the Strava surface via intervals.icu's push-to-Strava bridge (ADR-0011).
_Avoid_: destination, sink.

**Watch**:
The always-on polling loop that keeps annotations current without manual syncs: every tick
it **recomputes** the drifted corpus, then syncs a rolling window, so new runs get
annotated within minutes and provisional analyses finalize as the archive catches up.
Runs as a container on the home server.
_Avoid_: daemon, cron job, webhook (we poll; see ADR-0013).

**Heartbeat**:
The single overwritten row **watch** leaves behind each tick (ADR-0017): last tick, last
success, the consecutive-failure count, the last error, and the interval it is running at.
Current state, not history — the log is the history. Unkeyed by **Account**, because it
describes the process rather than an athlete, which is what lets `pacelab health` report
broken credentials without needing valid ones. **Unhealthy** is one clause read off it: no
successful tick within 3 × the recorded interval.
_Avoid_: status, ping, liveness (it is a last-success probe, not a liveness one).

**Model Version**:
What produced a stored number, stamped on every row: a declared version bumped by hand for
a pipeline change, plus a digest of the effective coefficients (ADR-0021) —
`0.2.1+<digest>`, or the bare `0.2.1` when every coefficient is its shipped default. Derived
from the values, never declared by an installation, so editing `pacelab.toml` drifts the
corpus by itself and the next **Recompute** reconciles it. The reference altitude is
excluded: it changes no stored number, so it must invalidate none.
_Avoid_: schema version, release version (it versions the model's outputs, not the code).

**Recompute**:
The reconciliation pass over the stored corpus (ADR-0016): every row that disagrees with
itself — stale `model_version`, still provisional, or never annotated — is re-analysed
against the **archive tier only**, saved, and republished, one activity at a time. Driven
by a query over the store, not by a provider listing: nothing new is discovered, which is
what separates it from a **sync**. This is how a coefficient re-tune reaches history.
_Avoid_: backfill, reprocess, migration, resync.

**Snapshot**:
One verified `.tar.gz` of the two irreplaceable parts of the corpus — the curated
`pacelab.db` and the pinned weather cache (ADR-0018). Written immediately before a
**recompute** rewrites its first row at a new `model_version`, and by hand after curating —
a pass that finds stale rows but rewrites none of them writes no snapshot. Named for the
version of the corpus it carries, which is what keeps it through later ones. Verified at
write time (integrity check + row counts), or it is a failure, not a warning. The two files it
carries are the **backup set**; the FIT cache is not in it, because intervals.icu holds the
authoritative copy.
_Avoid_: dump, export, archive (that's the `.tar.gz` file, not the act).

**Provisional Analysis**:
An analysis computed from forecast-tier weather because the run is more recent than the
reanalysis archive's publication lag. A preview, marked with a tilde in its annotation,
never disk-cached, and automatically **finalized** — recomputed against the pinned archive
and republished — by a later sync, or by the **recompute** pass once it has fallen out of
watch's window.
_Avoid_: draft, estimate, preliminary result.

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
The scalar fed into the heat penalty curve. Distinct from the penalty itself: the index
measures the environment, the curve maps it to a slowing. v0.2 uses **WBGT** (below); v1
used the **Heat Index** (air temperature + humidity, no wind/sun), now the fallback when
solar data is unavailable.
_Avoid_: feels-like, apparent temperature.

**WBGT** (Wet-Bulb Globe Temperature):
The v0.2 heat-stress index, computed from air temperature, humidity, **wind**, and **solar
radiation** by a closed-form approximation (ADR-0010). Because its wet-bulb term falls as
wind rises, wind cooling is *intrinsic* to it — the "wind→heat coupling" is not a separate
knob but a property of this index. Solar load raises it.
_Avoid_: heat index (that's the v1 fallback), feels-like.

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
**0% grade, 10 °C, 50% RH, no wind, no sun, home altitude**. Chosen so NP reads as
"equivalent ideal cool-weather pace." Frozen — see ADR-0002 (no-sun added in v0.2 for WBGT).
_Avoid_: ideal conditions, baseline (unqualified).

**Coefficient**:
One of the seven numbers that shape a **pace penalty** curve — `k_grade`, `wbgt_ref_c`,
`wbgt_a`, `wbgt_b`, `heat_a`, `heat_b`, `drag_area_per_mass` — each a property of how the
model was fitted rather than of what it normalizes to, and therefore settable per
**Installation**. Distinct from a *term* of the **Reference Conditions**, which is a
definition, frozen, and settable by nobody: `wbgt_ref_c` reads like one but is the heat
curve's zero-point — the number one particular WBGT approximation returns at the frozen
baseline — so it falls on the coefficient side, while `reference_temp_c` *is* the written
definition and stays in code (ADR-0021 argues that line). The reference altitude is on
neither side: settable, but a fact about where an athlete runs that fills a slot in the
frozen definition, which is why **Model Version** covers the coefficients and not it.
_Avoid_: parameter, constant, setting (each blurs the fitted/frozen line).

### Configuration

**Installation**:
One running copy of PaceLab against one corpus — the unit a **Personal Configuration** is
scoped to, and what "an installation that re-fits its heat curve" names. Distinct from
**Account**, which scopes *storage*: one installation may in principle hold several
accounts, and its **coefficients** belong to the installation rather than to any athlete in
it.
_Avoid_: instance, deployment, host, account (that's the storage unit).

**Personal Configuration**:
The optional `pacelab.toml` through which an **Installation** supplies its own
**coefficients** and reference altitude (ADR-0021). Absent — the ordinary case, and a
fresh clone needs no file at all — the engine computes with its shipped values. Located
beside the results database rather than in the process's working directory, so it belongs
to the corpus and follows it into the container.
_Avoid_: settings, preferences, config (bare), profile.
