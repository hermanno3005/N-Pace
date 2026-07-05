"""Backward (NP) and forward (AP) transforms — exact inverses over the applied cost.

Backward removes the applied environmental cost from an observed pace to get Normalized
Pace; forward projects a reference pace into conditions to get Adjusted Pace. Both use the
same ``applied_factor``, so ``adjust(normalize(p)) == p`` by construction (V-2).
"""

from pacelab.engine.combine import CombinedCost


def normalize(observed_pace: float, cost: CombinedCost) -> float:
    """Normalized Pace: observed pace with the applied environmental cost removed."""
    return observed_pace / cost.applied_factor


def adjust(reference_pace: float, cost: CombinedCost) -> float:
    """Adjusted Pace: a reference pace projected into the segment's conditions."""
    return reference_pace * cost.applied_factor
