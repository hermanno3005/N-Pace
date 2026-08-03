"""The shipped config carries the calibration decision, not the ported defaults.

`wbgt_a` is the one coefficient calibration licensed a change to (docs/research/
calibration-findings-2026-07.md). These tests pin that decision so it cannot be reverted
to the population default silently, and pin the `model_version` bump that goes with it —
without a bump the recompute pass never rewrites the corpus (ADR-0016).
"""

from pacelab.config import Config
from pacelab.models.heat import DEFAULT_WBGT_A


def test_wbgt_a_sits_in_the_confound_controlled_bracket():
    # 0.00009 (equal HR, rerun) — 0.00014 (21-day pairing, carried over): the two cuts that
    # control the season confound rather than model it. Anything inside is supportable.
    assert 0.00009 <= Config().wbgt_a <= 0.00014


def test_wbgt_a_is_calibrated_away_from_the_ported_default():
    # The ported El Helou default stays put in the model layer as the population value
    # (ADR-0010); the athlete's own value lives here (ADR-0006).
    assert Config().wbgt_a != DEFAULT_WBGT_A


def test_model_version_moved_past_the_pre_calibration_stamp():
    # 0.2.1 is the last version fitted with the ported coefficient. Results stamped with it
    # are heat-penalised ~7x too hard for this athlete, so they must read as stale — and
    # the store only ever compares versions for equality, so any distinct string does that.
    assert Config().model_version != "0.2.1"
    # Ordering, spelled as numbers: "0.10.0" > "0.2.1" is False as strings.
    assert _parts(Config().model_version) > _parts("0.2.1")


def _parts(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in version.split("."))
