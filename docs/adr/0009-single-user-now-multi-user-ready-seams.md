# Stay single-user, but keep the ingestion/storage seams multi-user-ready

PaceLab remains single-user (SRS scope), but the seams introduced for API ingestion are
shaped so that adding users later is *data*, not a rewrite. No server, OAuth, or hosted
database is built now — that would contradict the SRS and balloon scope.

Two ~free forward-compat choices:

- The **Provider is credential-injected per Account**, never a global singleton. Multiple
  users = multiple Providers constructed from multiple Accounts; the fetch code doesn't change.
- **Storage and the FIT cache are keyed by athlete/account id** (defaulting to the single
  v1 account). Adding an account adds rows/files under a new key; no migration.

This is cheap because the **core engine (models, normalize, analyze) is already stateless
and user-agnostic** — it needs nothing. And the ADR-0008 Provider↔processing split *is* the
scaling seam: the per-user, credentialed, rate-limited fetch layer is already isolated from
the stateless processing.

## The ceiling (deliberately not addressed now)

The intervals.icu **API-key** model scales to *technical* users (each supplies their own
key) indefinitely, but not to non-technical users — a consumer product would need **OAuth**
(Strava/Garmin), a server, and hosted storage/DB. That is a different project that would
revisit the source/auth choice (ADR-0008); the account-keyed seams here are what make that
transition additive rather than a teardown.

## Why record this

A future reader will see an `account_id` on every row and a `Provider` that takes an
`Account` while the app only ever has one user, and wonder why. This is the reason: a
deliberate, low-cost hedge against a possible multi-user future, with the hard auth ceiling
named so the boundary is intentional.
