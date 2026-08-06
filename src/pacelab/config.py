"""Tunable configuration (NFR-4): all model parameters live here, not in code paths.

Reference conditions are frozen (ADR-0002); coefficients are tunable, and Phase-3 calibration
(ADR-0006) personalises them — ``wbgt_a`` is the first one it has moved off its ported
population default. ``model_version`` stamps every result so a re-tune can recompute history
consistently and idempotent re-runs know when to recompute (FR-10.2) — and it is *derived*
from the coefficients in force, so a re-tune cannot fail to reach the stamp.

The values below are what PaceLab *ships*, fitted to one athlete's corpus in one location
(``docs/research/calibration-findings-2026-07.md``). An installation supplies its own through
an optional ``pacelab.toml`` beside its results database (ADR-0019) — see ``load_config``.
"""

import hashlib
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

    @property
    def model_version(self) -> str:
        """What produced these numbers: ``0.3.0``, or ``0.3.0+<digest>`` off the defaults.

        A field would be a lie once coefficients are data (ADR-0019). Editing
        ``pacelab.toml`` changes every number the engine produces, so it has to change the
        stamp too — otherwise the corpus keeps calling itself current, ``Recompute``
        enumerates nothing, and history disagrees with itself invisibly.

        The digest is over the values, not over the file: two installations tuned to the
        same numbers stamp the same version, and a file restating the defaults costs
        nothing — which is what keeps this change from drifting an existing corpus on the
        day it ships. Truncated to 8 hex characters: it distinguishes coefficient sets a
        person typed, not adversarial ones, and it stays legible in ``pacelab calibrate``'s
        version breakdown.
        """
        coefficients = _canonical_coefficients(self)
        if coefficients == _SHIPPED_COEFFICIENTS:
            return DECLARED_VERSION
        return f"{DECLARED_VERSION}+{_digest(coefficients)}"


#: The declared version — bumped by hand for a change no configuration file can express:
#: a pipeline change, or a re-tune of the *shipped* coefficients (which moves the baseline
#: the digest is measured against, so it stamps a bare version rather than a suffixed one).
#: 0.2.0: heat index → WBGT (ADR-0010). 0.2.1: remainder-segment merge + solar actually
#: persisted in the weather cache. 0.3.0: first calibrated coefficient — wbgt_a 0.0007 →
#: 0.0001 (ADR-0006/ADR-0014); minor, not patch, because everything before it ran on
#: ported population defaults.
DECLARED_VERSION = "0.3.0"

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

#: Settable but deliberately outside the version stamp: ``home_elevation_m`` is declared
#: here and read nowhere in the engine — an inert slot documenting the altitude term of the
#: Reference Conditions. A value that cannot change a stored number must not invalidate one.
#: If a future model consumes it, it moves into the digest in that same commit (ADR-0019).
_UNVERSIONED_KEYS = ("home_elevation_m",)

#: The seven coefficients whose values reach every number the engine stores, and therefore
#: the version it stamps them with. Derived by subtraction so that a *new* tunable enters
#: the digest by default — the safe direction to be wrong in.
VERSIONED_KEYS = tuple(k for k in SETTABLE_KEYS if k not in _UNVERSIONED_KEYS)

#: Fields a reader could plausibly expect to set, each held back for a stated reason
#: (ADR-0019). They get their own message: "unknown key" would be a lie, and the reason is
#: the part worth reading.
_UNSETTABLE_KEYS = {
    "apply_wind": "wind in NP is a per-invocation reporting choice (ADR-0005); "
                  "use the --apply-wind flag",
    "step_m": "the segment length is a pipeline constant, not a personal tunable",
    "reference_temp_c": "the Reference Conditions are frozen (ADR-0002)",
    "model_version": "the model version stamps what the engine computed; it is derived "
                     "from the coefficients below, never declared by an installation",
}


def _canonical_coefficients(config: "Config") -> str:
    """The versioned coefficients as one string, in a fixed order, at float precision.

    ``float()`` before ``repr()`` so that TOML's ``8`` and ``8.0`` — the same model to the
    engine — cannot present themselves as two versions.
    """
    return "\n".join(f"{key}={float(getattr(config, key))!r}" for key in VERSIONED_KEYS)


def _digest(coefficients: str) -> str:
    return hashlib.sha256(coefficients.encode("utf-8")).hexdigest()[:8]


#: What "unchanged" means, computed once. Compared as the canonical string rather than
#: through the digest, so the bare-version case never depends on the hash at all.
#:
#: Note what this does *not* cover: re-tuning a shipped default in ``models/`` still
#: stamps the bare version, because the defaults moved with it. That case is a code change
#: and is handled the way it always was — by bumping ``DECLARED_VERSION`` in the same
#: commit — and ``test_model_version.py`` pins the shipped values so it cannot pass unnoticed.
_SHIPPED_COEFFICIENTS = _canonical_coefficients(Config())


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
