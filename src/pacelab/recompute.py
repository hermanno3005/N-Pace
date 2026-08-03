"""The reconciliation pass (ADR-0016): the corpus repairs itself from the store.

`sync` is provider-driven because its job is discovery. This is the opposite job — nothing
new is being found, the store already knows which of its rows are wrong about themselves —
so the pass enumerates from SQLite: stale model version, forecast-tier preview, or stored
but never annotated.

Per activity it interleaves analyse → save → publish. `store.save()` clears
`published_version`, so at every crash point a row is either old and annotated old or new
and annotated new; the pass needs no resume state and no interruption handling.

Weather is **archive tier only**. A provisional still inside ERA5's lag raises
`WeatherUnavailable` and is skipped for this pass — `sync` picks it up through the forecast
tier in the same tick. The pass can only ever improve a `~` preview into a final result.
"""

from pacelab.app import PARSEABLE_SUFFIXES, analyze_file
from pacelab.config import Config
from pacelab.publish.publisher import try_publish
from pacelab.store import ResultStore
from pacelab.weather.service import WeatherUnavailable


def recompute(provider, service, store: ResultStore, config: Config, account_id: str,
              force: bool = False, before_rewrite=None) -> list[tuple[str, str]]:
    """Re-analyse and republish every drifted row for one account.

    Outcomes per activity, in `sync()`'s vocabulary:

    - ``"ok"`` — re-analysed against the archive, stored, annotation republished
    - ``"finalized"`` — a forecast-tier preview recomputed against the archive and
      republished without its ``~`` mark
    - ``"publish-failed"`` — stored, but the annotation write failed; the row stays
      enumerated, so the next pass retries it (publishing retries forever)
    - ``"no-weather"`` — still inside the archive's publication lag; skipped untouched
    - ``"no-file"`` — provider has no downloadable original
    - ``"no-track"`` — original has no usable GPS track (FR-1.4)
    - ``"unsupported"`` — original cached but in a format we can't parse

    ``force`` walks every stored row regardless of drift — what a pipeline change wants,
    and how to exercise a bump without editing ``config.py``.

    ``before_rewrite`` runs once, immediately before the first row is *written*, and only
    when that write replaces a row stamped at an older version — the corpus snapshot
    (ADR-0018). It is deliberately not guarded: if it raises, the pass aborts with the
    corpus untouched, which is the whole point of taking it.
    """
    activity_ids = (store.activity_ids(account_id) if force
                    else store.needs_recompute(config.model_version, account_id))
    snapshot = _Once(before_rewrite)
    outcomes: list[tuple[str, str]] = []
    for activity_id in activity_ids:
        was_provisional = store.is_provisional(activity_id, account_id=account_id)
        stored_current = store.is_current(activity_id, config.model_version, account_id)
        if not force and not was_provisional and stored_current:
            # Stored current, only the annotation is missing. Analysis converges
            # absolutely — it runs once per activity per bump (ADR-0016) — so a row that
            # publishing keeps failing on is retried forever without being re-analysed.
            published = try_publish(provider, store, activity_id, config.model_version,
                                    account_id)
            outcomes.append((activity_id, "ok" if published else "publish-failed"))
            continue
        path = provider.download(activity_id)  # cache hit: originals are immutable
        if path is None:
            outcomes.append((activity_id, "no-file"))
            continue
        if path.suffix.lower() not in PARSEABLE_SUFFIXES:
            outcomes.append((activity_id, "unsupported"))
            continue
        try:
            result = analyze_file(path, config, service)
        except WeatherUnavailable:
            outcomes.append((activity_id, "no-weather"))
            continue
        if result.distance_m == 0:
            outcomes.append((activity_id, "no-track"))
            continue
        if force or not stored_current:
            snapshot()  # ADR-0018, and never after the row it guards
        store.save(activity_id, result, config.model_version, account_id=account_id)
        published = try_publish(provider, store, activity_id, config.model_version, account_id)
        if not published:
            outcomes.append((activity_id, "publish-failed"))
        else:
            outcomes.append((activity_id, "finalized" if was_provisional else "ok"))
    return outcomes


class _Once:
    """The ADR-0018 snapshot hook, fired at most once and only when a rewrite is imminent.

    The gate is per-row and *lazy* rather than a question asked up front about the corpus,
    because the up-front question cannot be answered honestly: whether a stale row will be
    rewritten depends on whether the archive has published its day yet, which is only known
    once the analysis has been attempted. Asking "are there stale rows?" instead armed the
    guard for days after a bump (#37) — the last few activities stay inside ERA5's
    publication lag, are enumerated every tick and skipped ``no-weather``, and stay stale.
    Snapshotting for them wrote 96 archives a day and evicted the pre-bump snapshot the
    whole mechanism exists to produce.

    Firing here is still *before* the first write, which is the property that matters — a
    snapshot taken after the row it guards protects nothing.

    Two kinds of enumerated row deliberately do not reach this at all, because they recur on
    ordinary weeks and neither is destructive. A publish-only retry (stored current,
    annotation still owed) rewrites no row and is enumerated on *every* pass until
    intervals.icu accepts the write. A provisional finalization at the current version
    replaces one preview whose loss costs a re-analysis, not data.
    """

    def __init__(self, hook):
        self._hook = hook

    def __call__(self) -> None:
        if self._hook is not None:
            hook, self._hook = self._hook, None
            hook()
