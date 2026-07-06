import gzip

import pytest

from pacelab.account import Account
from pacelab.providers.http import HttpResponse
from pacelab.providers.intervals import IntervalsProvider

FIT_BYTES = b"\x00" * 8 + b".FIT" + b"payload-bytes"  # .FIT signature at offset 8
GPX_BYTES = b'<?xml version="1.0"?>\n<gpx version="1.1"><trk></trk></gpx>'


class StubHttp:
    def __init__(self, response):
        self.response = response

    def get(self, url, headers):
        return self.response


def _provider(response, tmp_path):
    return IntervalsProvider(Account("secret", "0"), StubHttp(response), cache_dir=tmp_path)


def test_download_decompresses_and_caches_the_original_fit(tmp_path):
    provider = _provider(HttpResponse(200, gzip.compress(FIT_BYTES)), tmp_path)
    path = provider.download("i100")
    assert path.suffix == ".fit"
    assert path.read_bytes() == FIT_BYTES  # decompressed to the original
    assert path.parent.name == "0"  # account-keyed cache


def test_download_detects_a_gpx_original(tmp_path):
    provider = _provider(HttpResponse(200, gzip.compress(GPX_BYTES)), tmp_path)
    assert provider.download("i101").suffix == ".gpx"


def test_download_handles_uncompressed_bodies(tmp_path):
    # Not all bodies are gzipped — a raw FIT must still be written.
    provider = _provider(HttpResponse(200, FIT_BYTES), tmp_path)
    assert provider.download("i102").read_bytes() == FIT_BYTES


def test_missing_original_skips_with_a_warning(tmp_path):
    # Strava-synced activities have no original → 404 → skip, don't crash (ADR-0008).
    provider = _provider(HttpResponse(404, b"not found"), tmp_path)
    with pytest.warns(UserWarning, match="i103"):
        assert provider.download("i103") is None
