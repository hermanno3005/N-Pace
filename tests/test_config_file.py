"""Personal configuration loaded from the corpus directory (ADR-0021).

The whole point of the file is that an installation's Normalized Pace is computed with its
own coefficients rather than the author's, so every test here is either "the value reached
the engine" or "a value that would silently not reach the engine is an error instead".
"""

import pytest

from pacelab.config import (
    CONFIG_FILENAME, SETTABLE_KEYS, Config, ConfigError, load_config,
)


def _write(tmp_path, body: str):
    """A results database path with `body` as the configuration beside it."""
    (tmp_path / CONFIG_FILENAME).write_text(body)
    return tmp_path / "pacelab.db"


def test_no_file_is_todays_shipped_defaults(tmp_path):
    # The common case, and the one that must stay zero-configuration: cloning and running
    # `pacelab analyze` behaves exactly as it did before this feature existed.
    assert load_config(tmp_path / "pacelab.db") == Config()


def test_an_empty_file_is_also_the_shipped_defaults(tmp_path):
    assert load_config(_write(tmp_path, "")) == Config()


def test_every_supported_key_reaches_the_config(tmp_path):
    db = _write(tmp_path, """
        home_elevation_m = 1609.0
        k_grade = 0.35
        wbgt_ref_c = 8.0
        wbgt_a = 0.0009
        wbgt_b = 1.8
        heat_a = 0.002
        heat_b = 1.4
        drag_area_per_mass = 0.006
    """)

    config = load_config(db)

    assert config.home_elevation_m == 1609.0
    assert config.k_grade == 0.35
    assert config.wbgt_ref_c == 8.0
    assert config.wbgt_a == 0.0009
    assert config.wbgt_b == 1.8
    assert config.heat_a == 0.002
    assert config.heat_b == 1.4
    assert config.drag_area_per_mass == 0.006


def test_a_partial_file_leaves_the_rest_at_their_defaults(tmp_path):
    config = load_config(_write(tmp_path, "k_grade = 0.35\n"))

    assert config.k_grade == 0.35
    assert config.wbgt_a == Config().wbgt_a


def test_integers_are_accepted_as_floats(tmp_path):
    # TOML distinguishes 8 from 8.0; a reader writing a round number should not have to
    # know that, and the engine does float arithmetic either way.
    config = load_config(_write(tmp_path, "wbgt_ref_c = 8\n"))

    assert config.wbgt_ref_c == 8.0
    assert isinstance(config.wbgt_ref_c, float)


def test_the_file_is_found_beside_the_database_not_in_the_cwd(tmp_path, monkeypatch):
    # The lookup rule that makes the container work: the Watch container's working
    # directory *is* the corpus directory, so a file that arrives through the existing
    # bind mount is found — and one sitting in whatever directory the process happens to
    # have started in is not.
    corpus = tmp_path / "data"
    corpus.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / CONFIG_FILENAME).write_text("k_grade = 0.99\n")
    (corpus / CONFIG_FILENAME).write_text("k_grade = 0.35\n")
    monkeypatch.chdir(elsewhere)

    assert load_config(corpus / "pacelab.db").k_grade == 0.35


def test_a_bare_database_name_resolves_against_the_cwd(tmp_path, monkeypatch):
    # `--db pacelab.db` (the default) has no directory part; the corpus directory is then
    # the working directory, which is exactly the container's case.
    monkeypatch.chdir(tmp_path)
    (tmp_path / CONFIG_FILENAME).write_text("k_grade = 0.35\n")

    assert load_config("pacelab.db").k_grade == 0.35


def test_apply_wind_is_a_flag_not_a_file_key(tmp_path):
    assert load_config(tmp_path / "pacelab.db", apply_wind=True).apply_wind is True
    assert load_config(tmp_path / "pacelab.db").apply_wind is False


@pytest.mark.parametrize("key", ["apply_wind", "step_m", "reference_temp_c", "model_version"])
def test_the_deliberately_unsettable_keys_are_rejected(tmp_path, key):
    # Each is a real field on Config, so accepting it would "work" — and quietly move a
    # thing that ADR-0021 keeps out of an installation's hands.
    db = _write(tmp_path, f"{key} = 1\n")

    with pytest.raises(ConfigError) as e:
        load_config(db)

    assert key in str(e.value)


def test_a_misspelled_key_is_an_error_naming_it_and_the_file(tmp_path):
    # The failure this feature exists to prevent: `k_grad = 0.35` silently normalizing at
    # the shipped 0.40 and calling the result personal.
    db = _write(tmp_path, "k_grad = 0.35\n")

    with pytest.raises(ConfigError) as e:
        load_config(db)

    assert "k_grad" in str(e.value)
    assert CONFIG_FILENAME in str(e.value)


@pytest.mark.parametrize("value", ['"0.35"', "true", "[0.35]", "{ a = 1 }"])
def test_a_non_numeric_value_is_an_error_naming_the_key(tmp_path, value):
    # `true` is here because Python's bool is an int: an unguarded numeric check accepts
    # it and normalizes at k_grade = 1.0.
    db = _write(tmp_path, f"k_grade = {value}\n")

    with pytest.raises(ConfigError) as e:
        load_config(db)

    assert "k_grade" in str(e.value)


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "+inf"])
def test_a_non_finite_value_is_an_error_naming_the_key(tmp_path, value):
    # TOML spells these as float literals, so a plain numeric check admits them. A NaN
    # coefficient makes every Normalized Pace it touches NaN and still hashes into
    # model_version, so the corpus gets stamped as if the poison were a legitimate re-tune.
    db = _write(tmp_path, f"k_grade = {value}\n")

    with pytest.raises(ConfigError) as e:
        load_config(db)

    assert "k_grade" in str(e.value)


def test_malformed_toml_is_an_error_naming_the_file(tmp_path):
    db = _write(tmp_path, "k_grade =\n")

    with pytest.raises(ConfigError) as e:
        load_config(db)

    assert CONFIG_FILENAME in str(e.value)


def test_a_configured_coefficient_changes_the_normalized_pace(tmp_path):
    # The criterion that matters: a value in the file is not merely parsed, it reaches the
    # engine and moves the number. A hot flat run under a doubled heat scale must have more
    # heat cost removed than the same run under the shipped one.
    from pacelab.analyze import analyze
    from pacelab.core import Segment
    from pacelab.weather.conditions import Conditions

    segments = [(Segment(distance=100.0, grade=0.0, bearing=90.0, elapsed=34.0,
                         lat=48.0, lon=11.0, start_time=0.0),
                 Conditions(30.0, 60.0, 0.0, 0.0, 0.0, 1013.25,
                            solar_radiation_wm2=600.0))] * 10

    shipped = analyze(segments, load_config(tmp_path / "pacelab.db"))
    hotter = analyze(segments, load_config(_write(tmp_path, "wbgt_a = 0.0014\n")))

    assert hotter.cost_heat > shipped.cost_heat
    assert hotter.np_pace < shipped.np_pace


def test_a_bad_configuration_file_fails_the_command_instead_of_running(tmp_path, capsys,
                                                                      monkeypatch):
    # End to end: the operator gets one line naming their typo and a non-zero exit, not a
    # traceback and not an analysis quietly computed with the author's coefficients.
    monkeypatch.setenv("INTERVALS_API_KEY", "test-key")
    monkeypatch.setenv("INTERVALS_ATHLETE_ID", "i399426")
    monkeypatch.setattr("pacelab.cli.recompute", lambda *a, **k: [])
    db = _write(tmp_path, "k_grad = 0.35\n")

    from pacelab.cli import main

    assert main(["recompute", "--db", str(db), "--cache-dir", str(tmp_path),
                 "--snapshots-dir", str(tmp_path / "snapshots")]) == 1

    err = capsys.readouterr().err
    assert "k_grad" in err and CONFIG_FILENAME in err
    assert "Traceback" not in err


def test_the_shipped_example_file_loads_to_the_shipped_defaults(tmp_path):
    # The example is documentation that can go stale, so it is checked rather than
    # trusted: every value it lists must still be the value the engine ships.
    from pathlib import Path

    example = Path(__file__).resolve().parents[1] / "pacelab.example.toml"
    body = example.read_text()

    assert load_config(_write(tmp_path, body)) == Config()
    # Uncommenting it must not then fail on a key the loader rejects…
    uncommented = "\n".join(line.lstrip("# ") if line.startswith("#") and "=" in line else line
                            for line in body.splitlines())
    assert load_config(_write(tmp_path, uncommented)) == Config()
    # …and it must list every settable key, so adding one to the loader without
    # documenting it here fails rather than shipping an undiscoverable knob.
    listed = {line.split("=")[0].strip() for line in uncommented.splitlines() if "=" in line}
    assert listed == set(SETTABLE_KEYS)
