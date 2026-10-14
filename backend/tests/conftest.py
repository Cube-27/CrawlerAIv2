"""Hypothesis profiles: CI runs every property test with a fixed `max_examples=200` (SPEC-04 §6); local runs keep
the Hypothesis default. GitHub Actions sets `CI`. Every test runs without the process's `CRAWLERAI_*` variables. For
INV-26, counters of HTML parser constructions. For API adapters and recipes (SPEC-02 §4.9, SPEC-09), a stand-in API."""

import os
from collections.abc import Callable, Mapping
from functools import partial
from ipaddress import ip_address
from typing import Any

import httpx
import pytest
from hypothesis import settings
from lxml import html as lxml_html
from selectolax import lexbor

from crawlerai.acquire.api import JsonFetcher, fetch_json
from crawlerai.acquire.ssrf import IPAddress, SafeConnector

settings.register_profile("ci", max_examples=200)
settings.load_profile("ci" if os.environ.get("CI") else "default")

# The test databases' variables, which name where DB tests may write (`tests/db/conftest.py`).
_TEST_DATABASE_PREFIX = "CRAWLERAI_TEST_"


@pytest.fixture(autouse=True)
def _hermetic_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every `CRAWLERAI_*` variable of the process is removed while a test runs: `make check` exports the developer's
    `.env` (keys, model ids), and settings a test builds read the environment. A test sets what it needs."""
    for name in list(os.environ):
        upper = name.upper()
        if upper.startswith("CRAWLERAI_") and not upper.startswith(_TEST_DATABASE_PREFIX):
            monkeypatch.delenv(name)


class ParserCounter:
    """Counts the constructions of one parser, with the first argument of each (the document parsed)."""

    def __init__(self) -> None:
        self.inputs: list[object] = []

    @property
    def calls(self) -> int:
        return len(self.inputs)

    def wrap(self, constructor: Callable[..., Any]) -> Callable[..., Any]:
        def counted(*args: Any, **kwargs: Any) -> Any:
            self.inputs.append(args[0] if args else None)
            return constructor(*args, **kwargs)

        return counted


@pytest.fixture
def parses(monkeypatch: pytest.MonkeyPatch) -> Mapping[str, ParserCounter]:
    """INV-26: the selectolax and lxml parser constructions while the test runs."""
    counters = {"selectolax": ParserCounter(), "lxml": ParserCounter()}
    monkeypatch.setattr(lexbor, "LexborHTMLParser", counters["selectolax"].wrap(lexbor.LexborHTMLParser))
    monkeypatch.setattr(lxml_html, "document_fromstring", counters["lxml"].wrap(lxml_html.document_fromstring))
    return counters


def _stand_in_api(routes: Mapping[str, bytes]) -> JsonFetcher:
    """`fetch_json` against a stand-in API serving `routes` (endpoint URL -> body; 404 for any other), resolving
    every host to a public address."""
    by_path = {httpx.URL(endpoint).raw_path.decode(): body for endpoint, body in routes.items()}

    async def resolve(_host: str) -> list[IPAddress]:
        return [ip_address("93.184.215.14")]

    def handler(request: httpx.Request) -> httpx.Response:
        body = by_path.get(request.url.raw_path.decode())
        return httpx.Response(404, json={}) if body is None else httpx.Response(200, content=body)

    return partial(
        fetch_json, engine_version="test", connector=SafeConnector(resolve), transport=httpx.MockTransport(handler)
    )


@pytest.fixture
def stand_in_api() -> Callable[[Mapping[str, bytes]], JsonFetcher]:
    return _stand_in_api
