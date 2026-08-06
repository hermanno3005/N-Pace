"""Tunable configuration (NFR-4): all model parameters live here, not in code paths.

Reference conditions are frozen (ADR-0002); coefficients are tunable, and Phase-3 calibration
(ADR-0006) personalises them — ``wbgt_a`` is the first one it has moved off its ported
population default. ``model_version`` stamps every result so a re-tune can
recompute history consistently and idempotent re-runs know when to recompute (FR-10.2).

The values below are what PaceLab *ships*, fitted to one athlete's corpus in one location
(``docs/research/calibration-findings-2026-07.md``). An installation supplies its own through
an optional ``pacelab.toml`` beside its results database (ADR-0019) — see ``load_config``.
"""

import tomllib
from dataclasses import dataclass, fields, replace
from pathlib import Path

from pacelab.models.grade import DEFAULT_GRADE_SENSITIVITY
from pacelab.models.heat import (
    DEFAULT_HEAT_A,
    DEFAULT_HEAT_B,
    DEFAULT_WBGT_B,
    REFERENCE_TEMP_C,
    WBGT_REF_C,
)
from pacelab.models.wind import DEFAULT_DRAG_AREA_PER_MASS


@dataclass(frozen=True)
class Config:
    # Frozen reference (ADR-0002)
    reference_temp_c: float = REFERENCE_TEMP_C
    home_elevation_m: float = 535.0
    # Preprocessing
    step_m: float = 100.0
    # Model coefficients (tunable; grade grounded per ADR-0007 — calibration could not
    # identify k_grade on this terrain, so the population default stands)
    k_grade: float = DEFAULT_GRADE_SENSITIVITY
    # WBGT heat curve (v0.2 primary, ADR-0010)
    wbgt_ref_c: float = WBGT_REF_C
    # Calibrated for this athlete (ADR-0006); models/heat.py keeps the ported 0.0007 as the
    # population default. Bracket, provenance and diagnostics:
    # docs/research/calibration-findings-2026-07.md.
    wbgt_a: float = 0.0001
    wbgt_b: float = DEFAULT_WBGT_B
    # Heat Index curve (fallback when solar data is unavailable)
    heat_a: float = DEFAULT_HEAT_A
    heat_b: float = DEFAULT_HEAT_B
    drag_area_per_mass: float = DEFAULT_DRAG_AREA_PER_MASS
    # Whether wind enters the applied NP (ADR-0005: off by default)
    apply_wind: bool = False
    # Stamps results for reproducibility / idempotent re-runs (FR-10.2).
    # 0.2.0: heat index → WBGT (ADR-0010). 0.2.1: remainder-segment merge + solar
    # actually persisted in the weather cache (both change stored numbers).
    # 0.3.0: first calibrated coefficient — wbgt_a 0.0007 → 0.0001 (ADR-0006/ADR-0014).
    # Minor, not patch: everything before this ran on ported population defaults.
    model_version: str = "0.3.0"


CONFIG_FILENAME = "pacelab.toml"

#: The reference altitude plus the seven model coefficients (ADR-0019). Everything else on
#: ``Config`` is deliberately not settable — see ``_UNSETTABLE_KEYS``.
SETTABLE_KEYS = (
    "home_elevation_m",
    "k_grade",
    "wbgt_ref_c",
    "wbgt_a",
    "wbgt_b",
    "heat_a",
    "heat_b",
    "drag_area_per_mass",
)

#: Fields a reader could plausibly expect to set, each held back for a stated reason
#: (ADR-0019). They get their own message: "unknown key" would be a lie, and the reason is
#: the part worth reading.
_UNSETTABLE_KEYS = {
    "apply_wind": "wind in NP is a per-invocation reporting choice (ADR-0005); "
                  "use the --apply-wind flag",
    "step_m": "the segment length is a pipeline constant, not a personal tunable",
    "reference_temp_c": "the Reference Conditions are frozen (ADR-0002)",
    "model_version": "the model version stamps what the engine computed; it is never "
                     "declared by an installation",
}


class ConfigError(ValueError):
    """A ``pacelab.toml`` that cannot be loaded exactly as written.

    Raised rather than warned, and never partially applied. A misspelled key that falls
    back to a shipped default is precisely the failure this file exists to prevent: the
    installation would go on computing a Normalized Pace with the author's coefficients
    while believing it had supplied its own.
    """


def config_path(db_path: Path | str) -> Path:
    """Where the configuration lives for a given results database.

    Beside the database, not in the process working directory — which is what makes the
    lookup survive the container, whose working directory *is* the bind-mounted corpus
    directory, so ``compose.yaml`` needs no change (ADR-0019).
    """
    return Path(db_path).resolve().parent / CONFIG_FILENAME


def load_config(db_path: Path | str, *, apply_wind: bool = False) -> Config:
    """The configuration for one run: shipped defaults, overlaid with ``pacelab.toml``.

    With no file present every value is the shipped default and nothing behaves
    differently — the common case, and it stays zero-configuration.
    """
    path = config_path(db_path)
    if not path.exists():
        return Config(apply_wind=apply_wind)

    try:
        # encoding pinned, not left to the locale: TOML is defined as UTF-8, and the
        # shipped example carries °C and em-dashes.
        table = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise ConfigError(f"{path}: {e}") from e

    return replace(Config(apply_wind=apply_wind), **_overrides(table, path))


def _overrides(table: dict, path: Path) -> dict[str, float]:
    known = {f.name for f in fields(Config)}
    overrides: dict[str, float] = {}
    for key, value in table.items():
        if key in _UNSETTABLE_KEYS:
            raise ConfigError(f"{path}: '{key}' cannot be set here — {_UNSETTABLE_KEYS[key]}")
        if key not in SETTABLE_KEYS:
            hint = "not settable" if key in known else "unknown key"
            raise ConfigError(f"{path}: {hint} '{key}'. Settable keys: "
                              f"{', '.join(SETTABLE_KEYS)}")
        # bool before int, deliberately: Python's bool *is* an int, so an unguarded
        # numeric check would accept `k_grade = true` and normalize at 1.0.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"{path}: '{key}' must be a number, got {value!r}")
        overrides[key] = float(value)
    return overrides
