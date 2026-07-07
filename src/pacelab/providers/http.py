"""A tiny injectable HTTP seam so providers are testable without a network.

The real implementation wraps urllib with an explicit CA bundle (macOS-safe, as the weather
client does); tests pass a stub that returns canned responses.
"""

import ssl
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

import certifi


@dataclass(frozen=True)
class HttpResponse:
    status: int
    content: bytes
    headers: dict[str, str] = field(default_factory=dict)


class Http(Protocol):
    def get(self, url: str, headers: dict[str, str]) -> HttpResponse:
        ...


# intervals.icu sits behind Cloudflare, which 403s (error 1010) the default urllib
# User-Agent as a bot. A real UA is required.
_USER_AGENT = "PaceLab/0.1 (+https://github.com/hermanno3005/N-Pace)"


class UrllibHttp:
    def __init__(self, timeout: float = 30.0):
        self._timeout = timeout
        self._ssl = ssl.create_default_context(cafile=certifi.where())

    def get(self, url: str, headers: dict[str, str]) -> HttpResponse:
        headers = {"User-Agent": _USER_AGENT, **headers}
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout, context=self._ssl) as resp:
                return HttpResponse(status=resp.status, content=resp.read(),
                                    headers=dict(resp.headers))
        except urllib.error.HTTPError as e:
            return HttpResponse(status=e.code, content=e.read(),
                                headers=dict(e.headers or {}))
