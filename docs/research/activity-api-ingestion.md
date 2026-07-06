# Activity API ingestion: intervals.icu for original FIT + streams

PaceLab is single-user: it needs to list one athlete's runs over a date range and, per run,
pull the **original uploaded FIT** (falling back to parsed streams). **intervals.icu** is the
right source because — unlike Strava — it exposes an endpoint that returns the *original*
uploaded file, and it authenticates with a plain API key over HTTP Basic (no OAuth dance for a
personal tool). This note pins the exact endpoints, headers, and caveats.

Base URL: `https://intervals.icu`. All paths below are under `/api/v1`.

Primary sources: the OpenAPI/Swagger UI at <https://intervals.icu/api/v1/docs> (landing page
<https://intervals.icu/api-docs.html>), the developer's "API access to Intervals.icu" guide
thread <https://forum.intervals.icu/t/api-access-to-intervals-icu/609>, and the
"API Integration Cookbook" <https://forum.intervals.icu/t/intervals-icu-api-integration-cookbook/80090>.

## 1. Authentication — API key over HTTP Basic

API-key auth is **HTTP Basic**, with the literal string `API_KEY` as the username and the
personal key as the password. Developer "david" states verbatim:

> "The username is `API_KEY` and the password your API key."
> "To use it you need to generate an API key in `/settings` (look for 'Developer Settings' near the bottom)."

Example (verbatim from the guide thread):

```
curl -u API_KEY:1l0nlqjq3j1obdhg08rz5rfhx \
  https://intervals.icu/api/v1/athlete/2049151/activities.csv
```

On the wire this is the standard header `Authorization: Basic base64("API_KEY:<key>")`; with
`curl -u` it is generated for you. The alternative scheme is OAuth2 bearer
(`Authorization: Bearer <token>`), used by third-party apps acting on another athlete's behalf —
not needed for a personal single-user tool.

**Athlete id in paths.** Athlete-scoped endpoints take a numeric athlete id (e.g.
`2049151`). For the athlete owning the API key you may pass `0` as a self-alias — david:

> "you can use `0` for the athlete id for endpoints that accept an athlete id in the path.
> This will use the athlete for the API key or bearer token used to make the call."

Note the `i{number}` prefix (e.g. `i55751783`) is the **activity** id form used on
activity-scoped paths, *not* the athlete id (which is a bare number). Get the key from
Settings → Developer Settings (bottom of the settings page); keep it secret and regenerate if
leaked.

Source: <https://forum.intervals.icu/t/api-access-to-intervals-icu/609>,
<https://forum.intervals.icu/t/intervals-icu-api-integration-cookbook/80090>.

## 2. List activities over a date range

```
GET /api/v1/athlete/{id}/activities?oldest=YYYY-MM-DD&newest=YYYY-MM-DD
```

Swagger summary: *"List activities for a date range in desc date order."* Query params:
`oldest`, `newest` (dates), plus `limit`, `route_id`, and `fields` (to trim the payload).
Append `.csv` to the path for CSV instead of JSON (`.../activities.csv`).

Verbatim cookbook example (bearer form shown; Basic works identically):

```
curl 'https://intervals.icu/api/v1/athlete/0/activities?oldest=2024-11-19&newest=2024-11-20' \
  -H 'Authorization: Bearer d842c1fc25f241e5ae440d09756448a9'
```

Each element is an Activity summary object. Relevant fields for PaceLab: `id` (string,
`i`-prefixed, e.g. `"i55751783"`), `start_date_local` / `start_date`, `type` (e.g. `Run`),
`name`, plus `distance`, `moving_time`, `elapsed_time`, and a `stream_types` array listing
which channels exist for that activity (e.g. `heartrate`, `watts`, `cadence`). The `id` is the
value you feed into the activity-scoped endpoints below.

Related read endpoints (from Swagger, if useful): `/activities/search`,
`/activities/search-full`, `/athlete/{athleteId}/activities/{ids}` (batch fetch by id).

Source: <https://intervals.icu/api/v1/docs>,
<https://forum.intervals.icu/t/intervals-icu-api-integration-cookbook/80090>.

## 3. Download the original uploaded file

```
GET /api/v1/activity/{id}/file
```

Swagger summary (verbatim): *"Download original activity file, Strava activities not
supported."* This returns the **raw original upload** — the exact FIT/GPX/TCX bytes the
device/app sent — **not** a re-encoded copy. It is typically served **gzip-compressed**;
cookbook example writes it straight to `activity.fit.gz`:

```
curl 'https://intervals.icu/api/v1/activity/i55751783/file' \
  -H 'Authorization: Bearer d842c1fc25f241e5ae440d09756448a9' \
  > activity.fit.gz
```

**Caveats (important for PaceLab):**

- **Strava-sourced activities are not supported** by this endpoint — intervals.icu never
  received an original file for those (Strava's API doesn't hand one over; see §6). Runs
  synced from a device/app that uploaded a real FIT are fine.
- The returned file is whatever was originally uploaded (fit / gpx / tcx / or a gz of same),
  so PaceLab must sniff the format rather than assume FIT. The `.gz` wrapper means decompress
  first.

Do **not** confuse this with the re-encoded endpoints, which regenerate a file from
intervals.icu's stored streams and **include any in-app HR/power corrections** (so they are
*not* the pristine original):

- `GET /api/v1/activity/{id}/fit-file` — *"Download Intervals.icu generated activity fit file"*
  (description: *"Not supported for Strava activities"*).
- `GET /api/v1/activity/{id}/gpx-file` — *"Download Intervals.icu generated activity gpx file"*
  (*"Not supported for Strava activities and activities without GPS data"*).

For PaceLab's "pull the original FIT" requirement, use `/file`; treat `/fit-file` only as a
degraded fallback (regenerated, may embed corrections).

Source: <https://intervals.icu/api/v1/docs>,
<https://forum.intervals.icu/t/intervals-icu-api-integration-cookbook/80090>,
<https://forum.intervals.icu/t/import-and-download-workout-and-activity-fit-files/19295>.

## 4. Streams — parsed per-point data (fallback)

```
GET /api/v1/activity/{id}/streams{ext}?types=...
```

Swagger summary: *"List streams for the activity."* `{ext}` is a required extension of at
least one char; use `.json` for JSON, `.csv` for CSV (per the streams forum thread:
*"You can use anything instead of '.json', but at least one character. Only if you use '.csv'
it will download a csv file"*). Example: `/api/v1/activity/i55751783/streams.json?types=watts`.

Query params: `types` (array — the channels you want; comma-separated) and `includeDefaults`
(boolean, add the default streams on top of `types`).

Response: a JSON **array of `ActivityStream` objects**, each roughly `{ type, data: [...] }`
where `data` is a per-sample array aligned to the `time` stream (missing samples appear as
`null`). Typical channels: `time`, `latlng` (or `lat`/`lng`), `distance`, `altitude`,
`heartrate`, `velocity_smooth` / `pace`, `watts`, `cadence`, `temp`. The activity summary's
`stream_types` field tells you which exist before you request them.

**Raw vs. processed:** streams are intervals.icu's *parsed and stored* representation, not the
untouched FIT record messages. Power in particular is served **smoothed/fixed by default** —
the Swagger notes `watts` is returned as `fixed_watts`, and you must pass `raw_watts`
explicitly to get the unsmoothed channel. So streams are convenient but lossy relative to the
original FIT (device-specific fields, developer fields, and exact per-record timing may be
absent or resampled). Prefer §3 `/file` when fidelity matters; use streams when the original is
unavailable (e.g. Strava-origin activities) or when the parsed channels are sufficient.

Source: <https://intervals.icu/api/v1/docs>,
<https://forum.intervals.icu/t/access-activities-streams-via-api/101065>.

## 5. Rate limits & terms

Documented by david for API-key callers (verbatim):

> "API key calls are limited to 5000 requests per day and 2500 requests per rolling 15 minute
> window."

Every response carries the budget in headers:

```
X-RateLimit-Limit:     <15m limit>,<daily limit>
X-RateLimit-Remaining: <15m remaining>,<daily remaining>
```

Exceeding a limit returns **HTTP 429** with a `Retry-After` header — honour it with a backoff.
The API key does not expire but can be **cleared/regenerated** by the user, which immediately
invalidates the old key (david: *"If you suspect that your key may have been compromised
immediately clear or re-generate it."*). No published per-endpoint quota beyond the global
5000/day + 2500/15min. Fair-use: the API is free and open but single-account personal use is
the expected pattern; heavy third-party/multi-athlete use is what OAuth + higher scrutiny is
for.

For PaceLab (one athlete, incremental daily pulls), 5000/day is far above need — the practical
limit is the 2500/15min burst if backfilling a long history, so paginate by date window and
watch the headers.

Source: <https://forum.intervals.icu/t/api-access-to-intervals-icu/609>.

## 6. Why not Strava (brief comparison)

Strava's API is the obvious alternative but is a worse fit here on two counts. First, it
**does not offer original-file download at all** — there is no `/activities/{id}/file`
equivalent; the closest is the Streams API `GET /api/v3/activities/{id}/streams` (channels
`time`, `latlng`, `distance`, `altitude`, `heartrate`, `velocity_smooth`, `watts`, `cadence`,
`temp`, `grade_smooth`), which returns Strava's *processed/smoothed* time series, never the raw
uploaded FIT. Second, Strava mandates **OAuth2** (per-app client id/secret, user authorization
redirect, refreshable access tokens) even for a personal tool, and enforces stricter rate
limits and API-agreement terms (e.g. restrictions on storing/deriving data). intervals.icu, by
contrast, gives a personal API key over HTTP Basic *and* hands back the genuine original file —
so PaceLab gets both simpler auth and higher-fidelity input by ingesting from intervals.icu.

Source (Strava): <https://developers.strava.com/docs/reference/#api-Streams>.
