import json

import pytest

from pacelab.account import Account
from pacelab.providers.http import HttpResponse
from pacelab.providers.intervals import IntervalsProvider, RateLimited


class StubHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, headers):
        self.calls.append(("GET", url, None))
        return self.responses.pop(0)

    def put(self, url, headers, body):
        self.calls.append(("PUT", url, body))
        return self.responses.pop(0)


def _provider(responses, tmp_path):
    return IntervalsProvider(Account("secret", "0"), StubHttp(responses), cache_dir=tmp_path)


def test_fetch_description_reads_the_activity_field(tmp_path):
    provider = _provider([HttpResponse(200, json.dumps({"id": "i100", "description": "hi"}).encode())], tmp_path)
    assert provider.fetch_description("i100") == "hi"


def test_fetch_description_handles_null(tmp_path):
    provider = _provider([HttpResponse(200, json.dumps({"id": "i100", "description": None}).encode())], tmp_path)
    assert provider.fetch_description("i100") is None


def test_update_description_puts_json_to_the_activity(tmp_path):
    provider = _provider([HttpResponse(200, b"{}")], tmp_path)
    provider.update_description("i100", "new text")
    method, url, body = provider._http.calls[0]
    assert method == "PUT"
    assert url.endswith("/activity/i100")
    assert json.loads(body) == {"description": "new text"}


def test_update_description_surfaces_errors(tmp_path):
    provider = _provider([HttpResponse(500, b"boom")], tmp_path)
    with pytest.raises(RuntimeError):
        provider.update_description("i100", "x")


def test_description_calls_respect_rate_limits(tmp_path):
    provider = _provider([HttpResponse(429, b"", headers={"Retry-After": "60"})], tmp_path)
    with pytest.raises(RateLimited):
        provider.fetch_description("i100")
