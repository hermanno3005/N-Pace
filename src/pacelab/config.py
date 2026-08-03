"""Tunable configuration (NFR-4): all model parameters live here, not in code paths.

Reference conditions are frozen (ADR-0002); coefficients are tunable, and Phase-3 calibration
(ADR-0006) personalises them — ``wbgt_a`` is the first one it has moved off its ported
population default. ``model_version`` stamps every result so a re-tune can
recompute history consistently and idempotent re-runs know when to recompute (FR-10.2).
"""

from dataclasses import dataclass

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
