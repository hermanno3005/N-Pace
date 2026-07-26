"""The Annotation — PaceLab's marker-delimited block in an activity description (ADR-0011).

``render_annotation`` produces the compact two-liner; ``splice_annotation`` merges it into
an existing description, replacing a previous PaceLab block (never stacking) and never
touching the athlete's own text. The marker line makes the splice idempotent.
"""

from pacelab.analyze import ActivityResult

MARKER = "🏃 PaceLab"


def _pace(sec_per_km: float) -> str:
    m, s = divmod(round(sec_per_km), 60)
    return f"{m}:{s:02d}/km"


def _signed(cost_s_per_km: float) -> str:
    return f"{round(cost_s_per_km):+d}"


def render_annotation(result: ActivityResult, provisional: bool = False) -> str:
    # The tilde marks a forecast-tier preview that ERA5 will finalise (ADR-0012).
    approx = "~" if provisional else ""
    return (
        f"{MARKER} · NP {approx}{_pace(result.np_pace)} (ran {_pace(result.observed_pace)})\n"
        f"⛰️ grade {_signed(result.cost_grade)} · 🌡️ heat {_signed(result.cost_heat)} · "
        f"💨 wind {_signed(result.cost_wind)} s/km (wind not in NP)"
    )


def strip_annotation(description: str | None) -> str:
    """The description with PaceLab's block removed — the athlete's own text only.

    The PaceLab block is the marker line plus the line after it.
    """
    lines = (description or "").splitlines()
    kept: list[str] = []
    i = 0
    while i < len(lines):
        if lines[i].startswith(MARKER):
            i += 2  # drop the marker line and the component line under it
            continue
        kept.append(lines[i])
        i += 1
    return "\n".join(kept).strip()


def splice_annotation(description: str | None, block: str) -> str:
    """Merge the annotation into a description: replace our old block, or append.

    Everything that isn't PaceLab's block belongs to the athlete and passes through
    untouched.
    """
    own = strip_annotation(description)
    return f"{own}\n\n{block}" if own else block
