# Publish annotations by editing the Strava description (and intervals.icu note)

Each analysed run gets a public **annotation** — NP, observed pace, and the grade/heat/wind
decomposition — written to two **publish targets**: the Strava activity **description** and
the intervals.icu activity note. Research in `docs/research/strava-writeback.md`.

**Why the description, not a comment.** Strava's API cannot create comments — the swagger
has only `GET /activities/{id}/comments`, no POST. Description editing
(`PUT /api/v3/activities/{id}`, scope `activity:write`) is the only annotation mechanism,
and it is what the prior art (Klimat; MeteoPace-class apps) does. PUT replaces the whole
description, so publishing is **read-modify-write**: fetch the current description, splice
PaceLab's marker-delimited block (first line `🏃 PaceLab` is the marker), write back. The
athlete's own text is never touched; re-publishing replaces our block, never stacks.

**Crossing the OAuth line knowingly.** ADR-0008 chose intervals.icu to avoid Strava OAuth;
ADR-0009 called OAuth "the ceiling". Write-back has no API-key path, so this feature pays
the OAuth cost — but **write-only and single-user**: a personal API app (Strava
"single-player mode": only the owner's account can authenticate), one-time localhost
consent (`pacelab strava-auth`, scopes `activity:read_all,activity:write`), rotating
refresh token in a gitignored chmod-600 token file, client id/secret in `.env`. Ingestion
stays on intervals.icu. PaceLab consumes no Strava data beyond matching metadata — relevant
because Strava's API policy (June 2026, §5.3) prohibits Strava data in AI applications.

**Matching** (intervals.icu reports `strava_id: null` for native COROS syncs, probed live):
find the Strava activity via `GET /athlete/activities?after&before` around the run's UTC
start; accept on `external_id` containing the COROS activity id (opportunistic exact fast
path — undocumented convention), else require start within ±60 s, `sport_type` Run, and
distance within ~2%. **Zero or multiple survivors → skip and warn**; never annotate the
wrong activity. The matched `strava_id` is persisted, so matching happens once per activity.

**Trigger & scope.** Ambient: `pacelab sync` publishes right after analysing, *iff* Strava
tokens exist (running `strava-auth` is the consent switch). `pacelab publish --from DATE`
backfills or re-publishes (e.g. after a model-version bump recomputes history). **Every**
analysed run is annotated (athlete's choice — MeteoPace-style, no "affected" threshold).
Publish state is persisted per (activity, model_version), so sync re-publishes exactly when
it recomputes.

**Format** (compact 2-liner; wind honesty per ADR-0005 kept in-line):

    🏃 PaceLab · NP 4:37/km (ran 5:04/km)
    ⛰️ grade +3 · 🌡️ heat +23 · 💨 wind −2 s/km (wind not in NP)

**Failure containment.** Publishing is best-effort: a Strava outage, rate limit
(write bucket: 200 req/15 min — ample), or failed match must never fail the sync; outcomes
are reported per activity like sync's own (`published` / `no-match` / `publish-failed`).
