"""The version stamp is derived from the coefficients that produced the numbers (ADR-0019).

Once coefficients are data, "the model changed" and "the version changed" stop being one
act unless the values themselves reach the stamp. Every test here is either "a change that
moves a stored number moves the version" or "a change that cannot move a stored number
leaves the corpus alone".
"""

import re

import pytest
from test_recompute import (
    ACCOUNT, ArchiveService, StubProvider, _stub_result, _watch_writes, _write_gpx,
)

from pacelab.account import Account
from pacelab.cli import main
from pacelab.config import (
    CONFIG_FILENAME, DECLARED_VERSION, SETTABLE_KEYS, VERSIONED_KEYS, Config, load_config,
)
from pacelab.recompute import recompute
from pacelab.report import format_summary
from pacelab.store import ResultStore

#: The seven tunable coefficients, each with a value that is not its shipped default.
RETUNED = {
    "k_grade": 0.35,
    "wbgt_ref_c": 8.0,
    "wbgt_a": 0.0014,
    "wbgt_b": 1.8,
    "heat_a": 0.002,
    "heat_b": 1.4,
    "drag_area_per_mass": 0.006,
}


def _write(tmp_path, body: str):
    (tmp_path / CONFIG_FILENAME).write_text(body)
    return tmp_path / "pacelab.db"


def test_the_shipped_defaults_are_the_bare_declared_version(tmp_path):
    # Load-bearing, not tidy: the author's corpus is stamped `0.3.0`, and a scheme that
    # suffixed the default version would mark all 55 rows drifted the day this shipped.
    assert Config().model_version == DECLARED_VERSION
    assert load_config(tmp_path / "pacelab.db").model_version == DECLARED_VERSION


def test_a_file_restating_every_default_is_also_the_bare_version(tmp_path):
    # Every settable key, not just the versioned ones: a reader who copies
    # `pacelab.example.toml` and uncomments the lot must not thereby drift their corpus.
    body = "\n".join(f"{key} = {getattr(Config(), key)!r}" for key in SETTABLE_KEYS)

    assert load_config(_write(tmp_path, body)).model_version == DECLARED_VERSION


def test_re_tuning_a_shipped_default_must_bump_the_declared_version():
    # The one drift the digest cannot catch by itself: change a default in `models/` and
    # the "shipped" baseline moves with it, so the corpus keeps stamping the bare version
    # under a changed model. That case is a code change, and this is its tripwire — if you
    # are here because a value below no longer matches, bump DECLARED_VERSION in the same
    # commit, then update these.
    assert (Config().k_grade, Config().wbgt_ref_c, Config().wbgt_a, Config().wbgt_b) == \
        (0.40, 7.2, 0.0001, 2.0)
    assert (Config().heat_a, Config().heat_b, Config().drag_area_per_mass) == \
        (0.0018, 1.5, 0.0057)
    assert DECLARED_VERSION == "0.3.0"


@pytest.mark.parametrize("key,value", sorted(RETUNED.items()))
def test_changing_any_coefficient_changes_the_stamp(tmp_path, key, value):
    version = load_config(_write(tmp_path, f"{key} = {value}\n")).model_version

    assert version != DECLARED_VERSION
    assert version.startswith(f"{DECLARED_VERSION}+")


def test_the_seven_coefficients_are_exactly_what_the_digest_covers():
    # A new tunable must enter the digest, and this is where forgetting shows up.
    assert set(VERSIONED_KEYS) == set(RETUNED)


def test_changing_the_reference_altitude_does_not_change_the_stamp(tmp_path):
    # `home_elevation_m` is declared and read nowhere in the engine — an inert slot
    # documenting the altitude term. A value that cannot change a stored number must not
    # invalidate one, so editing it must not recompute the corpus.
    db = _write(tmp_path, "home_elevation_m = 1609.0\n")

    assert load_config(db).home_elevation_m == 1609.0
    assert load_config(db).model_version == DECLARED_VERSION


def test_the_altitude_does_not_change_a_re_tuned_stamp_either(tmp_path):
    # Not just "excluded when nothing else moved": excluded, full stop.
    retuned = load_config(_write(tmp_path, "k_grade = 0.35\n")).model_version
    with_altitude = load_config(
        _write(tmp_path, "k_grade = 0.35\nhome_elevation_m = 1609.0\n")
    ).model_version

    assert with_altitude == retuned


def test_the_same_coefficients_always_produce_the_same_suffix(tmp_path):
    body = "wbgt_a = 0.0014\nk_grade = 0.35\n"
    reordered = "k_grade = 0.35\nwbgt_a = 0.0014\n"

    assert load_config(_write(tmp_path, body)).model_version == \
        load_config(_write(tmp_path, reordered)).model_version


def test_differing_coefficients_produce_differing_suffixes(tmp_path):
    versions = {load_config(_write(tmp_path, f"{key} = {value}\n")).model_version
                for key, value in RETUNED.items()}

    assert len(versions) == len(RETUNED)


def test_the_suffix_is_short_and_the_same_across_processes(tmp_path):
    # Pinned rather than merely self-consistent: the stamp lands in a database that
    # outlives the process, so a change to how it is derived must fail here rather than
    # silently mark an entire stored corpus drifted. Every coefficient is stated, so the
    # pin covers the derivation alone — a shipped default moving is the tripwire above.
    body = "\n".join(f"{key} = {value!r}" for key, value in sorted(RETUNED.items()))
    version = load_config(_write(tmp_path, body)).model_version

    assert re.fullmatch(r"0\.3\.0\+[0-9a-f]{8}", version)
    assert version == "0.3.0+cdab924d"


def test_an_integer_and_its_float_stamp_alike(tmp_path):
    # TOML distinguishes 8 from 8.0; the engine does not, so neither may the stamp — the
    # same model must not present itself as two.
    assert load_config(_write(tmp_path, "wbgt_ref_c = 8\n")).model_version == \
        load_config(_write(tmp_path, "wbgt_ref_c = 8.0\n")).model_version


def test_the_wind_flag_is_not_part_of_the_stamp(tmp_path):
    # A per-invocation reporting choice (ADR-0005), not a re-tune.
    assert load_config(tmp_path / "pacelab.db", apply_wind=True).model_version == DECLARED_VERSION


# --- the point of all of the above: the re-tune reaches history -------------------------

def test_a_re_tune_drifts_the_stored_corpus_and_recompute_reconciles_it(tmp_path):
    # The whole feature in one case. The corpus is settled at the shipped coefficients;
    # someone edits one; every row is drifted and the pass re-analyses and republishes it.
    provider, store, config = _retuned_corpus(tmp_path)

    assert store.needs_recompute(config.model_version, ACCOUNT) == ["i100"]

    outcomes = recompute(provider, ArchiveService(), store, config, ACCOUNT)

    assert outcomes == [("i100", "ok")]
    assert provider.downloaded == ["i100"]  # re-analysed, not merely re-stamped
    assert store.is_current("i100", config.model_version, account_id=ACCOUNT)
    assert not store.needs_publish("i100", config.model_version, account_id=ACCOUNT)
    assert store.needs_recompute(config.model_version, ACCOUNT) == []  # settled again


def test_a_re_tune_snapshots_before_the_first_row_is_rewritten(tmp_path):
    # ADR-0018's guard covers the coefficient case for free — a re-tune is a version bump
    # like any other, so a bad one is recoverable by the path that already exists.
    provider, store, config = _retuned_corpus(tmp_path)
    # Ordered against the first *write*, which is what #37 established the guard covers:
    # the pass downloads and analyses before it knows whether the row can be rewritten.
    events = _watch_writes(store)

    recompute(provider, ArchiveService(), store, config, ACCOUNT,
              before_rewrite=lambda: events.append("snapshot"))

    assert events[0] == "snapshot"
    assert "save" in events  # the pass really did rewrite, so the ordering means something


def test_editing_the_reference_altitude_recomputes_nothing(tmp_path):
    # The corpus is expensive to invalidate: 55 rows re-analysed and 55 public descriptions
    # rewritten to produce bit-identical numbers.
    provider, store, config = _retuned_corpus(tmp_path, "home_elevation_m = 1609.0\n")

    assert recompute(provider, ArchiveService(), store, config, ACCOUNT) == []
    assert provider.downloaded == []


def test_a_toml_beside_the_database_stamps_the_rows_it_produced(tmp_path, monkeypatch,
                                                               capsys):
    # End to end at the CLI seam: the file is found beside the database, the coefficients
    # reach the stamp, and a corpus stamped at the bare version is reported as drifted.
    monkeypatch.setenv("INTERVALS_API_KEY", "test-key")
    monkeypatch.setenv("INTERVALS_ATHLETE_ID", "i399426")
    account_id = Account.from_env().storage_id
    gpx = tmp_path / "run.gpx"
    _write_gpx(gpx)
    provider = StubProvider(gpx)
    monkeypatch.setattr("pacelab.cli.IntervalsProvider", lambda *a, **kw: provider)
    monkeypatch.setattr("pacelab.cli._weather", lambda cache_dir: ArchiveService())
    db = tmp_path / "pacelab.db"
    store = ResultStore(db)
    store.save("i100", _stub_result(), DECLARED_VERSION, account_id=account_id)
    store.mark_published("i100", DECLARED_VERSION, account_id=account_id)
    (tmp_path / CONFIG_FILENAME).write_text("wbgt_a = 0.0014\n")

    assert main(["recompute", "--db", str(db), "--cache-dir", str(tmp_path / ".cache"),
                 "--snapshots-dir", str(tmp_path / "snapshots")]) == 0

    stamped = load_config(db).model_version
    assert stamped.startswith(f"{DECLARED_VERSION}+")
    assert store.is_current("i100", stamped, account_id=account_id)
    assert (tmp_path / "snapshots" / "latest.tar.gz").exists()
    # …and the pass says which model it rewrote the corpus at, so a suffixed stamp in the
    # database can be traced back to the run that put it there.
    assert stamped in capsys.readouterr().out


def test_an_analysed_activity_reports_the_model_that_produced_it(tmp_path):
    # A suffix is the only visible sign that these numbers came from a personal
    # `pacelab.toml` rather than the shipped coefficients.
    version = load_config(_write(tmp_path, "wbgt_a = 0.0014\n")).model_version

    summary = format_summary("i100", _stub_result(), version)

    assert version in summary


def _retuned_corpus(tmp_path, body: str = "wbgt_a = 0.0014\n"):
    """One stored activity, settled at the shipped coefficients, then `body` is written."""
    gpx = tmp_path / "run.gpx"
    _write_gpx(gpx)
    provider = StubProvider(gpx)
    store = ResultStore(tmp_path / "pacelab.db")
    store.save("i100", _stub_result(), DECLARED_VERSION, account_id=ACCOUNT)
    store.mark_published("i100", DECLARED_VERSION, account_id=ACCOUNT)
    return provider, store, load_config(_write(tmp_path, body))
