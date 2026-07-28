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
              force: bool = False) -> list[tuple[str, str]]:
    """Re-analyse and republish every drifted row for one account.

    Outcomes per activity, in `sync()`'s vocabulary:

    - ``"ok"`` — re-analysed against the archive, stored, annotation republished
    - ``"publish-failed"`` — stored, but the annotation write failed; the row stays
      enumerated, so the next pass retries it (publishing retries forever)
    - ``"no-weather"`` — still inside the archive's publication lag; skipped untouched
    - ``"no-file"`` — provider has no downloadable original
    - ``"no-track"`` — original has no usable GPS track (FR-1.4)
    - ``"unsupported"`` — original cached but in a format we can't parse

    ``force`` walks every stored row regardless of drift — what a pipeline change wants,
    and how to exercise a bump without editing ``config.py``.
    """
    activity_ids = (store.activity_ids(account_id) if force
                    else store.needs_recompute(config.model_version, account_id))
    outcomes: list[tuple[str, str]] = []
    for activity_id in activity_ids:
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
        store.save(activity_id, result, config.model_version, account_id=account_id)
        published = try_publish(provider, store, activity_id, config.model_version, account_id)
        outcomes.append((activity_id, "ok" if published else "publish-failed"))
    return outcomes
