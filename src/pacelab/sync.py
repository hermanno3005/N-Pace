"""Sync orchestration (ADR-0008): list → download new → analyze → store, idempotently.

An activity already current in the store is skipped without downloading (rate-limit
friendly); an activity with no downloadable original is recorded as `no-file` and skipped.
"""

from pacelab.app import analyze_file
from pacelab.config import Config
from pacelab.store import ResultStore


def sync(provider, service, store: ResultStore, config: Config, oldest: str, newest: str,
         account_id: str, reprocess: bool = False) -> list[tuple[str, str]]:
    """Return per-activity outcomes: ("<id>", "skip" | "ok" | "no-file")."""
    outcomes: list[tuple[str, str]] = []
    for ref in provider.list_activities(oldest, newest):
        if not reprocess and store.is_current(ref.id, config.model_version, account_id):
            outcomes.append((ref.id, "skip"))
            continue
        path = provider.download(ref.id)
        if path is None:
            outcomes.append((ref.id, "no-file"))
            continue
        result = analyze_file(path, config, service)
        if result.distance_m == 0:
            # No usable GPS track — a treadmill run, strength session, etc. (FR-1.4).
            outcomes.append((ref.id, "no-track"))
            continue
        store.save(ref.id, result, config.model_version, account_id=account_id)
        outcomes.append((ref.id, "ok"))
    return outcomes
