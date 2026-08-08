"""The README's contract with the code it describes (#44).

The README is the public front door, and three of its claims are the kind that rot
silently: the sample annotation (which must stay what the renderer actually produces), the
verb table (which must stay the set of verbs the CLI actually has), and the absence of
coefficient values (which is what lets a re-tune ship without a README edit). Each is
checked here rather than left to a reader noticing.
"""

import re
from pathlib import Path

from pacelab.analyze import ActivityResult
from pacelab.cli import main  # noqa: F401  — imported so a broken CLI fails here too
from pacelab.config import VERSIONED_KEYS, Config
from pacelab.publish.annotation import MARKER, render_annotation

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text()
CLI_SOURCE = (ROOT / "src" / "pacelab" / "cli.py").read_text()

#: The corpus activity the README's sample annotation comes from: intervals.icu
#: i172861541, 5 August 2026, 9.6 km at 30 °C — deliberately an unremarkable run rather
#: than the corpus's extremes, so the block on the front page is the one a reader will
#: actually get. Stored numbers, copied from `activities` so the assertion runs without
#: the corpus, which is not in the repository. Segments are irrelevant to the annotation.
SAMPLE = ActivityResult(
    observed_pace=326.32018125568,
    np_pace=314.3741048473,
    cost_grade=2.42740480843857,
    cost_heat=9.44741471273196,
    cost_wind=-0.258747636403162,
    distance_m=9591.80639075328,
    segments=[],
    start_time=1785953902.0,
)

#: The run was still provisional when the block was taken, so the README shows the tilde.
SAMPLE_PROVISIONAL = True


def _annotation_in_readme(height: int) -> str:
    """The README's PaceLab block, the marker line and the ``height - 1`` lines under it.

    The height comes from the rendered annotation rather than being restated here, so a
    renderer that grows a third line is compared against a third line.
    """
    lines = README.splitlines()
    i = next(i for i, line in enumerate(lines) if line.startswith(MARKER))
    return "\n".join(lines[i:i + height])


def _table_rows() -> list[str]:
    """The README's Markdown table rows — the verb table and the doc map alike."""
    return [line for line in README.splitlines() if line.startswith("|")]


def test_titled_pacelab():
    assert README.startswith("# PaceLab")


def test_sample_annotation_is_what_the_renderer_produces():
    # Not hand-written, and not allowed to drift: an annotation format change has to reach
    # the README in the same commit, or this fails.
    block = render_annotation(SAMPLE, provisional=SAMPLE_PROVISIONAL)
    assert _annotation_in_readme(len(block.splitlines())) == block


def test_every_cli_verb_is_tabled():
    # Read off the CLI's own source rather than restated, so a tenth verb fails this
    # instead of quietly going undocumented. The count is the ninth verb's tripwire: a
    # *renamed* subparser would otherwise still satisfy the loop below.
    verbs = set(re.findall(r'add_parser\(\s*\n?\s*"(\w+)"', CLI_SOURCE))
    assert len(verbs) == 9, f"expected nine verbs, found {sorted(verbs)}"
    rows = _table_rows()
    for verb in verbs:
        assert any(f"`pacelab {verb}" in row for row in rows), f"{verb} is not tabled"


def test_states_no_coefficient_value():
    # The re-tune invariant: the README says where coefficients live and what changing one
    # does, never what it is. Otherwise every calibration pass edits this file.
    shipped = Config()
    for key in VERSIONED_KEYS:
        value = float(getattr(shipped, key))
        for rendered in {f"{value}", f"{value:.2f}", f"{value:.3f}",
                         f"{value:.4f}", f"{value:.5f}"}:
            assert rendered not in README, f"README states {key} = {rendered}"


def test_doc_map_links_every_entry_point():
    rows = _table_rows()
    for target in ("CONTEXT.md", "docs/adr/", "SRS_AdjustedPace.md", "docs/runbooks/",
                   "CLAUDE.md"):
        assert any(f"`{target}`" in row for row in rows), \
            f"the doc map does not link {target}"
        assert (ROOT / target).exists(), f"the doc map links a missing {target}"
