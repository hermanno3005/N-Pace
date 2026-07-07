# Strava write-back: annotating your own activities via API v3

PaceLab wants to stamp its weather/grade pace-penalty summary onto the athlete's own Strava
activities, Klimat-style. The punchline: **the API cannot create comments** — the only write
surface is `PUT /api/v3/activities/{id}` (`updateActivityById`), which sets the whole
`description` field, so the tool must GET-then-PUT (read-modify-write) and preserve the user's
existing text. Scopes: `activity:read_all` + `activity:write`. For a single-user CLI the OAuth
dance is a one-time browser consent against `localhost` (explicitly white-listed), then
refresh-token rotation forever after.

Primary sources: API reference <https://developers.strava.com/docs/reference/> and machine-readable
swagger <https://developers.strava.com/swagger/swagger.json> (+ model file
<https://developers.strava.com/swagger/activity.json>), authentication
<https://developers.strava.com/docs/authentication/>, getting started
<https://developers.strava.com/docs/getting-started/>, rate limits
<https://developers.strava.com/docs/rate-limits/>, webhooks
<https://developers.strava.com/docs/webhooks/>, API Agreement <https://www.strava.com/legal/api>
and API Policy <https://www.strava.com/legal/api_policy>; Klimat FAQ <https://klimat.app/faq>;
MeteoPace <https://www.meteopace.com/> + <https://www.meteopace.com/support>.

## 1. Comments are read-only

Confirmed from `swagger.json`: the only path containing `comments` is
`GET /activities/{id}/comments` (`getCommentsByActivityId`). **No POST/PUT/DELETE for comments
exists anywhere in the spec.** The reference describes it as read-only:

> "Returns the comments on the given activity. Requires activity:read for Everyone and
> Followers activities. Requires activity:read_all for Only Me activities."
> — <https://developers.strava.com/docs/reference/>

So a MeteoPace/Klimat-style annotation **cannot** be a bot comment; the only mechanism the
public API offers is editing the activity itself (§2). This matches what Klimat documents (§3).

## 2. Description update endpoint (`updateActivityById`)

```
PUT https://www.strava.com/api/v3/activities/{id}
```

Swagger: host `www.strava.com`, basePath `/api/v3`. Operation description (verbatim):

> "Updates the given activity that is owned by the authenticated athlete. Requires
> activity:write. Also requires activity:read_all in order to update Only Me activities"
> — <https://developers.strava.com/docs/reference/> / swagger.json

The `UpdatableActivity` request body (from <https://developers.strava.com/swagger/activity.json>)
accepts exactly these fields:

| field | type | doc (verbatim) |
|---|---|---|
| `name` | string | "The name of the activity" |
| `description` | string | "The description of the activity" |
| `sport_type` | SportType | — |
| `type` | ActivityType | "Deprecated. Prefer to use sport_type. In a request where both type and sport_type are present, this field will be ignored" |
| `gear_id` | string | "Identifier for the gear associated with the activity. 'none' clears gear from activity" |
| `trainer` | boolean | "Whether this activity was recorded on a training machine" |
| `commute` | boolean | "Whether this activity is a commute" |
| `hide_from_home` | boolean | "Whether this activity is muted" |

**Replace, not append.** `description` is a plain string field; the docs define no append/merge
semantics, so sending it sets the entire field (the docs are silent on partial-update behavior —
this is the model's only reading, not an explicitly documented sentence). Therefore PaceLab must
**GET the activity first, splice its own block into the existing description, and PUT the merged
text back** — otherwise it wipes whatever the user (or Klimat) wrote. Reading requires:

> "Returns the given activity that is owned by the authenticated athlete. Requires activity:read
> for Everyone and Followers activities. Requires activity:read_all for Only Me activities."
> — `getActivityById`, <https://developers.strava.com/docs/reference/>

Request `activity:read_all` up front so private ("Only Me") runs work for both GET and PUT.

Re-run safety: delimit PaceLab's block with a recognizable marker (or a fixed first token like
`🌡️`) so a second run replaces its own block instead of appending duplicates — same problem
Klimat has to solve; their FAQ doesn't describe their dedup mechanism.

## 3. What MeteoPace/Klimat do & annotation format

**Klimat** documents the mechanism explicitly — description editing, preserving user text
(<https://klimat.app/faq>, verbatim):

> "After you upload or update an activity in your training log, Klimat looks up the data for
> the time and location of the activity. It then adds the conditions you want to the activity's
> description. If you already have a description, Klimat will add the weather to it."

> "Updates normally happen within a few minutes of your activity uploading to your training
> log" — i.e. event-driven; a few-minute latency after upload strongly implies Strava webhooks
> (§7), though the FAQ never says "webhook".

> "Klimat won't populate weather for activities that are missing GPS information."

Format: template-driven — "Klimat offers full control of weather customization with the use of
Custom Weather Templates … a list of 30+ data metrics that can be added to your custom weather
template" (FAQ). Klimat's own pages publish no verbatim sample line (the examples are images);
third-party reviews' screenshots show a single emoji-prefixed weather line (temperature, wind,
humidity) appended below the user's text — inferred from screenshots, not stated on klimat.app.

**MeteoPace**: not verifiable from its site. <https://www.meteopace.com/> says only "Connect
Strava for activity insights"; the support page lists the FAQ "How does Strava integration
work?" but the answer loads client-side and isn't in the served HTML; the App Store listing
mentions only "Routes can now be imported from Strava". **Whether MeteoPace writes anything back
to Strava descriptions is not documented in any primary source I could fetch** — treat Klimat as
the confirmed prior art for the description-append mechanism.

## 4. OAuth for a single-user CLI

Create the app at <https://www.strava.com/settings/api> → `client_id` + `client_secret`. The
getting-started tutorial (<https://developers.strava.com/docs/getting-started/>): "When building
your app, change 'Authorization Callback Domain' to localhost or any domain." And new apps are
single-user by design, which is exactly PaceLab's shape:

> "All new applications start in single-player mode. This is the default state where only your
> own Strava account can authenticate with the app."

**Authorize** (browser, one time): `GET https://www.strava.com/oauth/authorize` with
`client_id`, `redirect_uri`, `response_type=code`, `approval_prompt=force|auto`, `scope`.
Scope separator (auth doc, verbatim): "Requested scopes, as a comma- or URL-safe space-delimited
string, e.g. 'activity:read_all,activity:write'". Relevant scopes (verbatim):

- `activity:read`: "read the user's activity data for activities that are visible to Everyone"
- `activity:read_all`: "the same access as activity:read, plus privacy zone data and access" [to Only Me activities]
- `activity:write`: "access to create manual activities and uploads, and access to edit"

`redirect_uri` "Must be within the callback domain specified by the application. localhost and
127.0.0.1 are white-listed." (<https://developers.strava.com/docs/authentication/>). The
tutorial itself uses `redirect_uri=http://localhost/exchange_token`.

**Token exchange**: `POST https://www.strava.com/oauth/token` with `client_id`, `client_secret`,
`code`, `grant_type=authorization_code` → returns refresh token, access token, expiry.
**Refresh**: same URL with `grant_type=refresh_token`. Expiry and rotation (verbatim):

> "Access tokens expire six hours after they are created"

> "Once a new refresh token code has been returned, the older code will no longer work." …
> "always use the most recent refresh token for subsequent requests"

So persist whatever `refresh_token` each token response returns, every time.

**Simplest sane CLI pattern**: one-time `pacelab strava auth` opens the authorize URL with
`scope=activity:read_all,activity:write` and a `http://localhost:<port>/...` redirect (tiny
local HTTP listener, or just have the user paste the `code=` from the redirected URL); exchange
for tokens; store `{access_token, expires_at, refresh_token}` in the config dir; on every
subsequent run, if `expires_at` is past, POST a refresh and overwrite all three fields.

## 5. Matching the activity id

```
GET https://www.strava.com/api/v3/athlete/activities   (getLoggedInAthleteActivities)
```

> "Returns the activities of an athlete for a specific identifier. Requires activity:read. Only
> Me activities will be filtered out unless requested by a token with activity:read_all."

Query params (swagger, verbatim): `before` — "An epoch timestamp to use for filtering activities
that have taken place before a certain time."; `after` — same wording with "after"; `page` —
"Page number. Defaults to 1."; `per_page` — "Number of items per page. Defaults to 30."

`SummaryActivity` fields of interest (activity.json, verbatim descriptions): `id` "The unique
identifier of the activity"; `external_id` "The identifier provided at upload time"; `upload_id`
"The identifier of the upload that resulted in this activity"; `name`, `distance` ("in meters"),
`moving_time`/`elapsed_time` ("in seconds"), `sport_type` (`type` is "Deprecated. Prefer to use
sport_type"), `start_date` "The time at which the activity was started.", `start_date_local`
"… in the local timezone."

`external_id` caveat: the doc says only "provided at upload time" — for device syncs it is
whatever the uploader chose (often the original file name, e.g. Garmin `.fit` names), but that
is convention, **not documented guarantee**, and manual/mobile-recorded activities may have a
different or absent value. **Recommended matching**: narrow with `after`/`before` around the FIT
start time, then (1) exact `external_id` match against the FIT filename when present, else
(2) `start_date` within a small tolerance (±60 s) + `distance` within ~1% + `sport_type=Run`.

## 6. Rate limits

From <https://developers.strava.com/docs/rate-limits/> (verbatim):

> "The default overall rate limit allows 200 requests every 15 minutes, with up to 2,000
> requests per day."

> "The default 'non-upload' rate limit allows 100 requests every 15 minutes, with up to 1,000
> requests per day." — defined as "all endpoints with the exception of: POST activities
> (activities#create), POST uploads (uploads#create), activities#upload_media"

Note the naming mismatch: the prose calls the second bucket "non-upload" but the response
headers call it "read": `X-RateLimit-Limit`, `X-RateLimit-Usage`, `X-ReadRateLimit-Limit`,
`X-ReadRateLimit-Usage`, each holding `"<15-min>,<daily>"` comma pairs, e.g. (doc example)
`X-Ratelimit-Limit: 600,30000` / `X-Ratelimit-Usage: 314,27536`. 15-minute windows reset on the
quarter hour (:00/:15/:30/:45); daily resets at midnight UTC.

> "Requests exceeding the limit will return 429 Too Many Requests along with a JSON error
> message."

Both PaceLab's GETs and the description PUT count against the 100/15-min "non-upload/read"
bucket (PUT `/activities/{id}` is not in the exception list). One annotate = 3 calls (list +
get + put); ~30 runs annotated per 15-min window — ample for one athlete.

## 7. API Agreement / ToS notes

Agreement (<https://www.strava.com/legal/api>, "Effective Date: June 1, 2026") + incorporated
API Policy (<https://www.strava.com/legal/api_policy>):

- **Write-back is contemplated, not restricted in detail.** Agreement §7.1: "Your Developer
  Applications may include the option to upload activities or information to the Strava
  Platform". Neither document has clauses specifically about editing descriptions, injected
  content, or spam — the constraints are all on data *use/display*.
- **Owner-only display**: "Strava Data provided by a specific user can only be displayed or
  disclosed in your Developer Application to that user." Trivially satisfied by a single-user CLI.
- **Tiers / subscription**: new apps are single-player (§4 quote above); Policy §3.3 defines a
  Standard tier of "Developer Applications limited to 10 registered Strava users", and
  "Standard Tier Applications are subject to subscription requirements … including a requirement
  that the developer or specified end users maintain an active Strava subscription." I.e. API
  access at the Standard tier now expects the developer to hold a Strava subscription — check
  the current terms at app-registration time.
- **AI restriction** (Policy §5.3): "You may not use the Strava API Materials or Strava Data …
  in connection with the development, training, evaluation, or operation of any AI Application."
  Not relevant to writing a weather line, but a hard stop on feeding Strava-sourced data to models.
- **Branding**: no blanket "Powered by Strava" sentence in the Agreement/Policy text; §8.1 only
  licenses Strava Marks "as described in the Brand Guidelines". A personal CLI that displays
  Strava data should follow the Brand Guidelines if/where it attributes; nothing requires
  branding *inside* the description text you write.
- **Webhooks vs polling**: webhooks (<https://developers.strava.com/docs/webhooks/>) allow one
  subscription per application, fire on activity create/update, and require a **publicly
  accessible callback URL** that echoes a GET challenge within seconds — wrong shape for a local
  CLI. **Recommendation: poll** `GET /athlete/activities?after=<last-run>` when PaceLab runs;
  at one athlete's volume this is nowhere near the rate limits.
