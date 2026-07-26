from pacelab.analyze import ActivityResult
from pacelab.publish.annotation import MARKER, render_annotation, splice_annotation


def result(np=277.0, obs=304.0, grade=3.4, heat=23.0, wind=-2.4):
    return ActivityResult(observed_pace=obs, np_pace=np, cost_grade=grade, cost_heat=heat,
                          cost_wind=wind, distance_m=10000.0, segments=[])


# ── render ──────────────────────────────────────────────────────────────────

def test_renders_the_compact_two_liner():
    text = render_annotation(result())
    assert text == (
        "🏃 PaceLab · NP 4:37/km (ran 5:04/km)\n"
        "⛰️ grade +3 · 🌡️ heat +23 · 💨 wind -2 s/km (wind not in NP)"
    )


def test_marker_is_the_first_line_prefix():
    assert render_annotation(result()).startswith(MARKER)


def test_provisional_annotation_marks_np_as_approximate():
    # Forecast-tier weather → the NP is a preview that ERA5 will finalise; the tilde
    # says so without cluttering the block (NFR-2 honesty).
    text = render_annotation(result(), provisional=True)
    assert "NP ~4:37/km" in text


def test_final_annotation_has_no_tilde():
    assert "~" not in render_annotation(result())


def test_zero_components_render_as_plus_zero():
    text = render_annotation(result(grade=0.2, heat=0.0, wind=0.0))
    assert "⛰️ grade +0 · 🌡️ heat +0 · 💨 wind +0" in text


# ── splice ──────────────────────────────────────────────────────────────────

def test_splice_into_empty_description_is_just_the_block():
    block = render_annotation(result())
    assert splice_annotation(None, block) == block
    assert splice_annotation("", block) == block


def test_splice_appends_after_the_athletes_own_text():
    block = render_annotation(result())
    out = splice_annotation("Great tempo run with K.", block)
    assert out.startswith("Great tempo run with K.")
    assert out.endswith(block)
    assert "\n\n" in out  # blank line between their text and ours


def test_splice_replaces_a_previous_block_instead_of_stacking():
    old = render_annotation(result(np=290.0))
    new = render_annotation(result(np=277.0))
    description = "My notes.\n\n" + old
    out = splice_annotation(description, new)
    assert out == "My notes.\n\n" + new
    assert out.count(MARKER) == 1


def test_strip_removes_our_block_and_keeps_the_athletes_text():
    from pacelab.publish.annotation import strip_annotation

    block = render_annotation(result())
    assert strip_annotation(f"My race notes.\n\n{block}") == "My race notes."
    assert strip_annotation(block) == ""
    assert strip_annotation("Just my words.") == "Just my words."
    assert strip_annotation(None) == ""


def test_splice_is_idempotent():
    block = render_annotation(result())
    once = splice_annotation("Notes.", block)
    assert splice_annotation(once, block) == once
