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

# PaceLab's models are running physics (Minetti grade, running heat curve, running drag
# area) — only run-type activities are analysed. intervals.icu uses Strava-style types.
_RUN_TYPES = {"Run", "TrailRun"}


def sync(provider, service, store: ResultStore, config: Config, oldest: str, newest: str,
         account_id: str, reprocess: bool = False, provisional_service=None) -> list[tuple[str, str]]:
    """Return per-activity outcomes, one of:

    - ``"ok"`` — downloaded, analyzed, stored, annotation published (ADR-0011)
    - ``"provisional"`` — inside the archive's publication lag; analysed against the
      forecast tier and published with the ~ mark (ADR-0012); finalized by a later sync
    - ``"finalized"`` — a previously provisional result recomputed against the archive
      and republished
    - ``"publish-failed"`` — analyzed and stored, but the annotation write failed
      (best-effort: retried by the next sync/publish run)
    - ``"not-a-run"`` — a ride/swim/etc.; running physics don't apply, never downloaded
    - ``"skip"`` — already current in the store; not even downloaded
    - ``"no-file"`` — provider has no downloadable original (e.g. Strava-synced)
    - ``"no-track"`` — original has no usable GPS track (treadmill, strength; FR-1.4)
    - ``"no-weather"`` — no weather on any tier yet; nothing stored, retried next sync
    - ``"unsupported"`` — original cached but in a format we can't parse (e.g. TCX)
    """
    outcomes: list[tuple[str, str]] = []
    for ref in provider.list_activities(oldest, newest):
        if ref.type not in _RUN_TYPES:
            outcomes.append((ref.id, "not-a-run"))
            continue
        was_provisional = store.is_provisional(ref.id, account_id=account_id)
        if (not reprocess and not was_provisional
                and store.is_current(ref.id, config.model_version, account_id)):
            outcomes.append((ref.id, "skip"))
            continue
        path = provider.download(ref.id)  # cache hit for finalization passes
        if path is None:
            outcomes.append((ref.id, "no-file"))
            continue
        if path.suffix.lower() not in _PARSEABLE:
            # Cached (it's the user's data) but not parseable — never feed e.g. a TCX
            # to the GPX adapter.
            outcomes.append((ref.id, "unsupported"))
            continue

        provisional = False
        try:
            result = analyze_file(path, config, service)
        except WeatherUnavailable:
            # Inside the archive's publication lag: fall back to the forecast tier for a
            # provisional preview (ADR-0012), or defer entirely if that's dry too.
            if provisional_service is None:
                outcomes.append((ref.id, "no-weather"))
                continue
            try:
                result = analyze_file(path, config, provisional_service)
            except WeatherUnavailable:
                outcomes.append((ref.id, "no-weather"))
                continue
            provisional = True

        if result.distance_m == 0:
            # No usable GPS track — a treadmill run, strength session, etc. (FR-1.4).
            outcomes.append((ref.id, "no-track"))
            continue
        if provisional and was_provisional:
            # Still inside the lag; the stored preview is already published — leave it.
            outcomes.append((ref.id, "provisional"))
            continue
        store.save(ref.id, result, config.model_version, account_id=account_id,
                   provisional=provisional)
        published = try_publish(provider, store, ref.id, config.model_version, account_id)
        if not published:
            outcomes.append((ref.id, "publish-failed"))
        elif provisional:
            outcomes.append((ref.id, "provisional"))
        else:
            outcomes.append((ref.id, "finalized" if was_provisional else "ok"))
    return outcomes
