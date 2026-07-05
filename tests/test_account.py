import pytest

from pacelab.account import Account


def test_from_env_reads_the_api_key(monkeypatch):
    monkeypatch.setenv("INTERVALS_API_KEY", "secret-key")
    monkeypatch.delenv("INTERVALS_ATHLETE_ID", raising=False)
    account = Account.from_env()
    assert account.api_key == "secret-key"
    assert account.athlete_id == "0"  # 0 = the key's owner (intervals.icu convention)


def test_from_env_reads_an_explicit_athlete_id(monkeypatch):
    monkeypatch.setenv("INTERVALS_API_KEY", "secret-key")
    monkeypatch.setenv("INTERVALS_ATHLETE_ID", "i12345")
    assert Account.from_env().athlete_id == "i12345"


def test_from_env_without_a_key_raises_a_clear_error(monkeypatch):
    monkeypatch.delenv("INTERVALS_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="INTERVALS_API_KEY"):
        Account.from_env()
