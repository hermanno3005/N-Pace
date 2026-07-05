"""A tiny injectable HTTP seam so providers are testable without a network.

The real implementation wraps urllib with an explicit CA bundle (macOS-safe, as the weather
client does); tests pass a stub that returns canned responses.
"""

import ssl
import urllib.request
from dataclasses import dataclass
from typing import Protocol

import certifi


@dataclass(frozen=True)
class HttpResponse:
    status: int
    content: bytes


class Http(Protocol):
    def get(self, url: str, headers: dict[str, str]) -> HttpResponse:
        ...


class UrllibHttp:
    def __init__(self, timeout: float = 30.0):
        self._timeout = timeout
        self._ssl = ssl.create_default_context(cafile=certifi.where())

    def get(self, url: str, headers: dict[str, str]) -> HttpResponse:
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout, context=self._ssl) as resp:
                return HttpResponse(status=resp.status, content=resp.read())
        except urllib.error.HTTPError as e:
            return HttpResponse(status=e.code, content=e.read())
