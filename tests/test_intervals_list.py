import json

from pacelab.account import Account
from pacelab.providers.http import HttpResponse
from pacelab.providers.intervals import IntervalsProvider

LISTING = json.dumps([
    {"id": "i100", "start_date_local": "2024-07-01T08:00:00", "type": "Run", "name": "Morning"},
    {"id": "i101", "start_date_local": "2024-07-02T18:00:00", "type": "Run", "name": "Evening"},
]).encode()


class StubHttp:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, headers):
        self.calls.append((url, headers))
        return self.response


def test_list_activities_parses_refs_and_builds_the_request(tmp_path):
    http = StubHttp(HttpResponse(200, LISTING))
    provider = IntervalsProvider(Account("secret", "0"), http, cache_dir=tmp_path)

    refs = provider.list_activities("2024-07-01", "2024-07-31")

    assert [r.id for r in refs] == ["i100", "i101"]
    assert refs[0].type == "Run"
    url, headers = http.calls[0]
    assert "athlete/0/activities" in url
    assert "oldest=2024-07-01" in url and "newest=2024-07-31" in url
    assert headers["Authorization"].startswith("Basic ")
