# Software Requirements Specification
## Environment-Adjusted Pace Engine (working title: *PaceLab*)

| | |
|---|---|
| **Version** | 0.1 (Draft for tuning) |
| **Status** | Draft — open decisions flagged in §10 |
| **Owner** | Hermann |
| **Scope** | Single-user, personal, non-commercial |
| **Target runtime** | Local CLI / Python package; deployable on HermiPi (Docker) |

---

## 1. Introduction

### 1.1 Purpose
Specify a system that takes a recorded running activity (GPS track + elevation + time + optionally HR) and computes:
1. **Normalized Pace (NP)** — the pace the athlete *would* have run under defined reference conditions at the same physiological effort, i.e. observed pace with the estimated environmental cost removed. This is the primary retrospective metric.
2. A **per-segment cost decomposition** into grade, heat, and wind contributions.
3. (Forward mode, secondary) **Adjusted Pace (AP)** — a reference/goal pace projected *into* given conditions, for race planning.

The physics engine is bidirectional: forward (AP) and backward (NP) are inverses of the same model, so both fall out of one implementation.

### 1.2 Scope
In scope: ingestion of personal activities, weather enrichment from a free reanalysis/forecast API, three environmental impact models (grade, heat, wind), a normalization/adjustment engine, a personal-calibration loop, and local output/storage.

Out of scope (this version): multi-user, commercial weather licensing, wind microclimate downscaling, acclimatization state-tracking, a mobile UI, real-time on-watch guidance.

### 1.3 Definitions & Acronyms
- **Segment** — a consecutive pair (or short window) of track points over which grade/bearing/conditions are treated as locally constant.
- **GAP** — Grade-Adjusted Pace.
- **NP / AP** — Normalized Pace / Adjusted Pace (see §1.1).
- **Reference conditions** — the canonical "ideal" baseline NP normalizes to. Default candidate: flat (0%), 10 °C, 50% RH, no wind, athlete's home altitude. *Tunable — see D-1.*
- **WBGT** — Wet-Bulb Globe Temperature (heat-stress index).
- **ERA5** — ECMWF reanalysis dataset exposed via Open-Meteo's historical API.
- **FIT** — Garmin/COROS activity file format.

### 1.4 References (scientific basis)
- Minetti et al. (2002) — energy cost of running vs. gradient → grade model.
- Ely, Cheuvront, Roberts & Montain (2007); El Helou et al. (2012) — temperature vs. marathon performance → heat model.
- Pugh (1971); Davies (1980) — air-resistance energy cost / headwind–tailwind asymmetry → wind model.
- Smyth & Lawlor (2015) — pacing/blow-up context (motivational, not computational).
- Open-Meteo Historical Weather API (ERA5); COROS / Strava activity data.

---

## 2. Overall Description

### 2.1 Product perspective
Standalone Python tool. No server dependency beyond an outbound HTTPS call to the weather API. Runs as a CLI/batch job locally or on HermiPi; all activity data stays on local disk.

### 2.2 Primary functions
Ingest activity → preprocess track → enrich with weather → compute per-segment grade/heat/wind cost → produce NP, decomposition, and stored results. Optionally calibrate model coefficients to the athlete's own data.

### 2.3 User characteristics
Single technical user (Python-literate, data-comfortable). No GUI required; tabular/JSON output and charts acceptable.

### 2.4 Constraints
- **C-1** Weather data MUST come from a source free for personal use (Open-Meteo assumed).
- **C-2** Implementation language: Python 3.11+.
- **C-3** MUST run offline except for weather API calls; results cached so re-runs need no network.
- **C-4** MUST be Dockerizable for HermiPi (arm64).
- **C-5** Internal units SI (m, s, °C, m/s); display units metric (min/km, km/h, °C).

### 2.5 Assumptions & dependencies
- **A-1** Per-point GPS lat/lon, elevation, and timestamp are obtainable per activity. *Open question: COROS MCP may expose only workout-level summaries; raw track likely needs FIT export (COROS app / Strava). See D-2.*
- **A-2** Altitude via GPS-Position.
- **A-3** Open-Meteo provides hourly temp, RH, wind speed, wind direction, cloud cover, surface pressure at the activity's location/time; exact grid resolution to be confirmed (tens of km, coarse). See D-3.

---

## 3. Functional Requirements

### 3.1 Activity Ingestion — `FR-1`
- **FR-1.1** Parse FIT files into a normalized per-point record: `(t, lat, lon, ele, dist, speed, hr?, cadence?)`.
- **FR-1.2** Parse GPX as a fallback/alternative input.
- **FR-1.3** (Optional) Pull activities/metadata via COROS MCP or Strava where raw track is available.
- **FR-1.4** Reject/flag activities missing GPS or timestamps; degrade gracefully (e.g. treadmill runs → heat-only, no grade/wind).

### 3.2 Track Preprocessing — `FR-2`
- **FR-2.1** Resample/clean the track to a consistent basis (fixed distance step or time step). *Step size tunable — D-4.*
- **FR-2.2** Smooth elevation to suppress GPS/baro spikes before computing grade (e.g. rolling/Savitzky–Golay). MUST cap per-segment grade to a physically valid range (≈ −45%…+45%, Minetti's validity bounds).
- **FR-2.3** Compute per-segment grade, distance, bearing (course heading), and elapsed time.
- **FR-2.4** Detect and flag stoppages/pauses so they don't distort pace metrics.

### 3.3 Weather Enrichment — `FR-3`
- **FR-3.1** For each segment, query weather for its location and timestamp; interpolate the hourly grid in **time and space** to the *moving* runner's position (not a single fixed point per activity).
- **FR-3.2** Retrieve at minimum: air temperature, relative humidity, wind speed, wind direction, cloud cover, surface pressure.
- **FR-3.3** Cache raw API responses locally keyed by (lat, lon, hour) so re-runs are network-free and reproducible.
- **FR-3.4** Support both historical (ERA5) for past activities and forecast for forward/planning mode, behind one interface.

### 3.4 Grade Model — `FR-4`
- **FR-4.1** Compute a per-segment grade cost factor based on the Minetti (2002) energy-cost-vs-gradient polynomial, normalized to flat (`C(grade)/C(0)`).
- **FR-4.2** Cost MUST be asymmetric (climbs cost more than equivalent descents return) and reflect that steep descents stop yielding benefit.
- **FR-4.3** Coefficients exposed as parameters (not hard-coded) for later personalization (athlete hill strength). See `FR-8`.

### 3.5 Heat Model — `FR-5`
- **FR-5.1** Compute a heat-stress index per segment from temperature + humidity, optionally incorporating cloud cover (radiant load) and wind (convective cooling). v1 MAY use apparent temperature; a WBGT approximation is the target.
- **FR-5.2** Map the heat-stress index to a fractional pace penalty that is ~0 near the reference temperature and increases monotonically (non-linearly) with heat. Curve shape from Ely (2007) / El Helou (2012), with parameters exposed for tuning.
- **FR-5.3** Cold penalty MAY be modeled but is low priority; default 0 above freezing.
- **FR-5.4** (Deferred) Acclimatization adjustment — out of scope v1; the heat-cost interface MUST leave a hook for a future per-athlete modifier.

### 3.6 Wind Model — `FR-6`
- **FR-6.1** Project the wind vector onto each segment's bearing to derive the **headwind component** (signed).
- **FR-6.2** Compute a pace cost from the air-resistance relationship (cost ∝ air density × relative-velocity²), with **headwind cost > tailwind benefit** (Pugh/Davies asymmetry).
- **FR-6.3** Derive air density from temperature, pressure, and altitude.
- **FR-6.4** v1 uses raw reanalysis 10 m wind directly (no terrain sheltering). Wind contribution MUST be tagged **low-confidence** in output. Microclimate downscaling is explicitly out of scope (D-5).
- **FR-6.5** Optional `drafting` flag that attenuates wind cost (default off for solo training).

### 3.7 Adjustment & Normalization Engine — `FR-7`
- **FR-7.1** Combine the three per-segment cost factors into a single environmental multiplier. The combination rule (additive in cost vs. multiplicative, and cross-coupling such as wind→heat cooling) MUST be a defined, documented function. See D-6.
- **FR-7.2** **Backward (NP):** map each segment's observed pace to reference conditions by removing its environmental cost; aggregate to an activity-level Normalized Pace.
- **FR-7.3** **Forward (AP):** map a reference/goal pace into target conditions to predict actual pace/splits.
- **FR-7.4** Output a per-activity decomposition: total environmental cost in s/km, split into grade / heat / wind, plus NP and observed pace.
- **FR-7.5** Cost attribution MUST be transparent and reproducible (same inputs → same numbers; no hidden state).

### 3.8 Personal Calibration — `FR-8` (Phase 2)
- **FR-8.1** Using activities with HR, model the athlete's pace-at-given-effort and regress residuals against grade, heat-stress, and headwind to estimate **personal coefficients**, replacing population defaults.
- **FR-8.2** MUST report fit quality (R², residual spread) and never silently overfit on sparse data; fall back to population defaults when data is insufficient.
- **FR-8.3** Calibration is reproducible and versioned (store the coefficient set + the data window it was fit on).

### 3.9 Output, Storage & Reporting — `FR-9`
- **FR-9.1** Persist results per activity (JSON + a tabular store, e.g. SQLite/Parquet) for trend analysis.
- **FR-9.2** Produce a per-activity summary (NP, observed pace, decomposition) and a per-segment table.
- **FR-9.3** Support an NP-over-time view to track fitness independent of conditions.
- **FR-9.4** (Optional) Chart output for single-activity decomposition and the NP trend.

### 3.10 Batch Processing — `FR-10`
- **FR-10.1** Process a directory/history of activities idempotently (skip already-computed unless model version changed).
- **FR-10.2** Tag each result with the model + coefficient version used, so a re-tune can recompute history consistently.

---

## 4. Non-Functional Requirements

- **NFR-1 Accuracy (target, not guarantee):** on stable-condition runs, |NP − observed pace| within a small tolerance; on known-hard conditions, decomposition signs and rough magnitudes must match sport-science expectations. Validation per §6.
- **NFR-2 Transparency:** every adjustment traceable to inputs and named coefficients; no black-box step.
- **NFR-3 Reproducibility:** deterministic given cached weather; results stamped with model/coefficient version.
- **NFR-4 Tunability:** all model parameters live in config, not code.
- **NFR-5 Performance:** a single typical activity processes in < a few seconds (excluding cold weather-API calls); full history batch is acceptable to run overnight.
- **NFR-6 Portability:** runs on x86 dev machine and arm64 HermiPi via Docker.
- **NFR-7 Privacy:** activity data never leaves local storage except anonymized lat/lon/time sent to the weather API.
- **NFR-8 Extensibility:** each impact model is a pluggable component behind a common interface (`cost(segment, weather) → factor`).

---

## 5. External Interfaces

- **IF-1 Weather API (Open-Meteo):** HTTPS; historical (ERA5) + forecast endpoints; rate-limit-aware with local cache.
- **IF-2 Activity sources:** FIT/GPX file input (primary); COROS MCP / Strava (secondary, subject to raw-track availability — D-2).
- **IF-3 Storage:** local filesystem (cache + results DB).
- **IF-4 (Optional) Strava write-back / watch export:** out of scope v1, noted for future.

---

## 6. Validation & Acceptance Criteria

- **V-1 Unit sanity:** grade/heat/wind models reproduce textbook values at reference points (flat & 10 °C & no wind → all factors ≈ 1.0; known Minetti points within tolerance).
- **V-2 Self-consistency:** forward then backward transform returns the original pace (round-trip identity).
- **V-3 Empirical, on Hermann's data:** across stable-condition runs, NP variance should be *lower* than raw-pace variance (normalization removes condition noise). NP should track independently-known fitness changes (e.g. taper, PB build-ups).
- **V-4 Stress cases:** a hot run, a windy run, and a hilly run each produce a decomposition whose dominant term and sign are correct.
- **V-5 Calibration (Phase 2):** personalized coefficients improve V-3 fit vs. population defaults, with reported R²/residuals.

---

## 7. Release Phasing

| Phase | Contents | Effort |
|---|---|---|
| **v0.1 (weekend)** | FR-1 (FIT), FR-2, FR-3 (historical), FR-4, basic FR-5, naive FR-6, FR-7 (NP + decomposition), FR-9 minimal | small |
| **v0.2 (evenings)** | GPS/elevation hardening, WBGT heat, FR-9 full + charts, FR-10 batch over history | medium |
| **v0.3 (data-science)** | FR-8 personal calibration against HR; NP-trend validation | medium |
| **Deferred** | wind downscaling, acclimatization modeling, watch/Strava write-back, GUI | — |

---

## 8. Out of Scope (explicit)
Microclimate/terrain wind downscaling; heat-acclimatization state modeling; multi-user; commercial weather feeds; mobile app; real-time guidance.

---

## 9. Risks
- **R-1** Coarse weather grid misrepresents felt conditions (esp. wind) → mitigate by confidence-tagging and personal calibration.
- **R-2** COROS raw-track access uncertain → may force FIT-export workflow.
- **R-3** Sparse personal data → calibration overfit → guarded by NFR fallback + fit reporting.
- **R-4** Combination rule (FR-7.1) is the highest-leverage modeling choice and the easiest to get subtly wrong.

---

## 10. Decisions to Tune (open register)

| ID | Decision | Default / leaning | Notes |
|---|---|---|---|
| **D-1** | Reference conditions for NP | flat, 10 °C, 50% RH, no wind, home altitude | drives every NP number; pick once and freeze |
| **D-2** | Activity source for raw track | FIT export (COROS/Strava) | confirm whether COROS MCP exposes per-point GPS |
| **D-3** | Weather product/resolution | Open-Meteo ERA5 (historical) | confirm grid res & forecast endpoint for fwd mode |
| **D-4** | Segmentation basis & step | TBD (e.g. 100 m or 10 s) | trade resolution vs. noise |
| **D-5** | Wind handling in v1 | raw 10 m wind, low-confidence | downscaling deferred |
| **D-6** | Cost combination rule | additive-in-cost, with wind→heat cooling coupling | highest-leverage; document explicitly |
| **D-7** | Heat index | apparent temp v1 → WBGT target | cloud cover in or out for v1? |
| **D-8** | Units in output | min/km, km/h, °C | SI internal |
| **D-9** | Calibration trigger | min N activities + condition spread | define thresholds before enabling FR-8 |

---

*End of draft v0.1. Tune §10 first — those decisions propagate through the functional requirements.*
