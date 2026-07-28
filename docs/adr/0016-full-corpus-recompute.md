# The corpus reconciles itself from the store, on every watch tick

`model_version` exists so a re-tune can recompute history consistently (FR-10.2), and the
HermiPi deployment promises this happens unattended: bump the version, and every annotation
on intervals.icu is republished without anyone opening a laptop. Nothing in the code does
that today.

`sync()` walks a rolling 14-day window (ADR-0013), and `store.is_current()` compares
`model_version` exactly. So a bump recomputes the last two weeks and leaves everything older
stamped at the old version — while `np_trend()` and `load()` apply no version filter at all,
so `calibrate` would fit across a mixed-version corpus without saying so. This ADR adds the
missing pass and decides what triggers it.

## The pass is driven by the store, not by the provider

`sync` is provider-driven by construction: it iterates `provider.list_activities(oldest,
newest)` because its job is **discovery** — finding runs it has never seen. Reconciliation is
the opposite job. Nothing new is being discovered; the corpus already knows exactly which of
its rows are wrong about themselves.

So the pass enumerates from SQLite:

```sql
SELECT activity_id FROM activities
 WHERE account_id = ?
   AND (model_version != ?              -- stale: the version was bumped
        OR provisional = 1              -- a preview, to finalize against the archive
        OR published_version IS NOT ?)  -- stored current, never annotated
```

No listing call, no date window, no re-running the not-a-run filter over every ride ever
recorded. Rows whose remote activity has since been deleted are still recomputed locally;
only their republish fails, which is correct — the corpus is ours, the annotation is theirs.

The cost is that the pass can never pick up an activity the store has never seen. That is
deliberate: discovery is `sync`'s job and the initial corpus is seeded, not derived.

Scoped to one `account_id` (`Account.from_env().storage_id`), because rows under the `local`
account come from `pacelab analyze` on local files and have no provider to download from or
publish to.

## Drift is a query, not a stored marker

The alternative — recording the last version the recompute ran at — would be a second source
of truth that can disagree with the rows themselves. The query above is derived from the data
it describes, so it cannot go stale, and it represents a *partially* completed pass correctly
for free.

## Per activity: analyse, save, publish — in that order, interleaved

Not recompute-everything-then-republish-everything. `store.save()` sets `published_version`
back to NULL, so an interleaved pass leaves every row, at every crash point, in one of two
self-consistent states: old version annotated at the old version, or new version annotated at
the new one. At most one activity is in flight, and the next tick catches it.

The batched ordering has no compensating advantage and a real cost: it leaves the entire
store ahead of what is public for the duration of the pass.

This is also why the pass needs **no resume state and no interruption handling**. A container
restart mid-pass is indistinguishable from a pass that hasn't started.

Re-analysis is network-free: originals are immutable and cached (ADR-0008), weather is cached
per cell-day (ADR-0004). Only publishing touches the network, at two calls per activity.
intervals.icu allows 5000 requests/day and 2500 per rolling 15 minutes, so a 55-activity
burst — 110 calls — is not close to a limit, and the existing `RateLimited` abort remains the
only pacing the pass needs.

## Convergence is split by cost

The pass runs constantly, so it must go quiet. Two rows resist: one whose activity was deleted
on intervals.icu (`fetch_description` 404s, and `try_publish` is best-effort and swallows it),
and one still inside ERA5's publication lag.

The resolution is to let the two halves converge differently.

**Analysis converges absolutely.** It runs once per activity per bump, because `store.save()`
cannot fail — the row is stamped current whatever happens next.

**Publishing retries forever.** That is the right behaviour for the overwhelmingly likely
cause (a transient outage, an expired key, intervals.icu down), and the cost of being wrong is
bounded: a permanently dead activity burns ~192 requests/day against a 5000/day budget.

Rejected: a `gone` tombstone column set on a 404. It buys complete silence at the price of a
schema migration and a state that is wrong if the activity returns — or if the 404 was really
an auth failure in disguise.

Rejected: a bounded retry counter. It converges without knowing *why* it failed, and silently
abandons a row after a long enough outage.

## Every tick, not once at boot

`try_publish` never raises. A recompute can therefore finish with every row stamped at the new
version and some `published_version` still NULL — drift by version is gone, but the annotation
is stale, and `sync`'s rolling window only retries publishes inside the last 14 days. A
boot-only trigger would leave that until the container restarts.

So `watch` runs the pass at the top of every tick, before `sync`. When the corpus is settled
this is one indexed `SELECT` returning nothing, every 15 minutes.

Ordering within the tick is load-bearing: recompute runs first with **archive-tier weather
only**, so a provisional still inside the lag raises `WeatherUnavailable` and is skipped —
then `sync` picks it up through the forecast tier in the same tick. The recompute can only
ever *improve* a `~` preview into a final result; it will never overwrite one guess with
another.

## The pass also rescues stranded provisionals

Including `provisional = 1` in the enumeration is not only about version bumps. ADR-0012
assumed a provisional row is finalized by a later sync, which holds only while the row stays
inside `watch`'s window. Three rows in the current corpus have already fallen out of it: they
are provisional *and* stale at `0.2.0`, so today they are never finalized, never recomputed,
and silently mixed into every `calibrate` fit.

The same query and the same loop fix them. Widening `watch`'s window instead was rejected: no
fixed window survives a Pi that was switched off for a month, and it costs a longer listing
call every 15 minutes forever.

## `calibrate` reports a mixed corpus rather than refusing to fit

`calibrate` gains the version breakdown in the header it already prints, stated loudly when
there is more than one version present. It still fits.

Refusing would be wrong in the common case. Calibration reads only `pace_obs`, `grade`,
`avg_hr`, `elapsed`, `stopped` and WBGT-from-raw-weather — never `p_grade`, `pace_np`, or any
other model output. A **coefficient** bump (`wbgt_a`, `k_grade`) therefore leaves every column
calibration touches bit-identical, and a mixed corpus is provably harmless. Only a **pipeline**
bump (segment step, smoothing, solar in the cache, HR persistence) genuinely invalidates the
fit.

Filtering silently to the current version was also rejected: it changes what `n_runs` means
mid-pass, and an underpowered fit that looks entirely normal is the failure mode calibration
can least afford.

`trend` has the same missing filter and keeps it — it displays rather than fits.

## Surface

    pacelab recompute [--force]      # the pass, on demand
    pacelab watch [--no-recompute]   # the pass, every tick, before sync

One function, two entry points, so the manual and automatic paths cannot diverge. `--force`
reprocesses every row regardless of drift — needed to exercise a bump without editing
`config.py`, and what a pipeline change wants. `--no-recompute` is off by default and exists
so a misbehaving pass on the Pi can be disabled without taking the watch loop down with it.

How loudly the pass announces itself is left to the health-surface and logging design; a
55-activity boot pass is something that design has to account for.
