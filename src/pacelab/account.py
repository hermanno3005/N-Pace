"""An Account — one athlete's credentials on a Provider (ADR-0009).

The unit of scoping for storage and the FIT cache. v1 reads a single account from the
environment; the abstraction is what keeps a multi-user future data rather than a rewrite.
The API key lives only in the environment — never in the repo, config, or the store.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Account:
    api_key: str
    athlete_id: str = "0"  # intervals.icu: 0 means "the key's owner"

    @classmethod
    def from_env(cls) -> "Account":
        key = os.environ.get("INTERVALS_API_KEY")
        if not key:
            raise RuntimeError(
                "INTERVALS_API_KEY is not set — get a key from intervals.icu "
                "Settings → Developer and export it."
            )
        return cls(api_key=key, athlete_id=os.environ.get("INTERVALS_ATHLETE_ID", "0"))
