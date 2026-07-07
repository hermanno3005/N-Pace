"""Sync orchestration (ADR-0008): list → download new → analyze → store, idempotently.

An activity already current in the store is skipped without downloading (rate-limit
friendly). A rate limit (429) raises `RateLimited` and aborts the sync rather than
hammering the remaining activities.
"""

from pacelab.app import analyze_file
from pacelab.config import Config
from pacelab.publish.publisher import try_publish
from pacelab.store import ResultStore
from pacelab.weather.service import WeatherUnavailable

_PARSEABLE = {".fit", ".gpx"}


def sync(provider, service, store: ResultStore, config: Config, oldest: str, newest: str,
         account_id: str, reprocess: bool = False) -> list[tuple[str, str]]:
    """Return per-activity outcomes, one of:

    - ``"ok"`` — downloaded, analyzed, stored, annotation published (ADR-0011)
    - ``"publish-failed"`` — analyzed and stored, but the annotation write failed
      (best-effort: retried by the next sync/publish run)
    - ``"skip"`` — already current in the store; not even downloaded
    - ``"no-file"`` — provider has no downloadable original (e.g. Strava-synced)
    - ``"no-track"`` — original has no usable GPS track (treadmill, strength; FR-1.4)
    - ``"no-weather"`` — too recent for the ERA5 archive; nothing stored, retried next sync
    - ``"unsupported"`` — original cached but in a format we can't parse (e.g. TCX)
    """
    outcomes: list[tuple[str, str]] = []
    for ref in provider.list_activities(oldest, newest):
        if not reprocess and store.is_current(ref.id, config.model_version, account_id):
            outcomes.append((ref.id, "skip"))
            continue
        path = provider.download(ref.id)
        if path is None:
            outcomes.append((ref.id, "no-file"))
            continue
        if path.suffix.lower() not in _PARSEABLE:
            # Cached (it's the user's data) but not parseable — never feed e.g. a TCX
            # to the GPX adapter.
            outcomes.append((ref.id, "unsupported"))
            continue
        try:
            result = analyze_file(path, config, service)
        except WeatherUnavailable:
            # ERA5 hasn't published the day yet; the FIT stays cached, nothing is
            # stored, and the next sync picks the activity up again.
            outcomes.append((ref.id, "no-weather"))
            continue
        if result.distance_m == 0:
            # No usable GPS track — a treadmill run, strength session, etc. (FR-1.4).
            outcomes.append((ref.id, "no-track"))
            continue
        store.save(ref.id, result, config.model_version, account_id=account_id)
        published = try_publish(provider, store, ref.id, config.model_version, account_id)
        outcomes.append((ref.id, "ok" if published else "publish-failed"))
    return outcomes
