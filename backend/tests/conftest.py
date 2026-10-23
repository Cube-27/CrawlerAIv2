"""Hypothesis profiles: CI runs every property test with a fixed `max_examples=200`; local runs keep
the Hypothesis default; the verify-* skills run theirs with the `verify` profile. GitHub Actions sets `CI`. Every test
runs without the process's `CRAWLERAI_*` variables. Counters of HTML parser constructions. For API adapters
and recipes, a stand-in API."""

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

from crawlerai.acquire import impersonate
from crawlerai.acquire.api import JsonFetcher, JsonRequest, fetch_json
from crawlerai.acquire.browser_session import Identity
from crawlerai.acquire.ssrf import IPAddress, SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from tests.stand_in import IMPERSONATE, STAND_IN_BROWSER, handler_transport

settings.register_profile("ci", max_examples=200)
# The verify-* skills' one command (`.claude/skills/verify-*/SKILL.md`) asks for more examples, with no per-example
# deadline (the first example builds the CLDR tables), through `--hypothesis-profile=verify`.
settings.register_profile("verify", max_examples=2000, deadline=None)
settings.load_profile("ci" if os.environ.get("CI") else "default")

# The test databases' variables, which name where DB tests may write (`tests/db/conftest.py`).
_TEST_DATABASE_PREFIX = "CRAWLERAI_TEST_"


@pytest.fixture(autouse=True)
def _hermetic_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every `CRAWLERAI_*` variable of the process is removed while a test runs: `make check` exports the developer's
    `.env` (keys, model ids), and settings a test builds read the environment. A test sets what it needs. No Chrome
    starts to read the browser rung's headers (`acquire.impersonate`): the rungs send a stand-in Chrome's user agent
    over the default target."""
    for name in list(os.environ):
        upper = name.upper()
        if upper.startswith("CRAWLERAI_") and not upper.startswith(_TEST_DATABASE_PREFIX):
            monkeypatch.delenv(name)
    monkeypatch.setattr(impersonate, "_read_identity", _no_browser)


async def _no_browser() -> Identity:
    return Identity(STAND_IN_BROWSER, {})


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
    """The selectolax and lxml parser constructions while the test runs."""
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
        fetch_json,
        engine_version="test",
        impersonate=IMPERSONATE,
        connector=SafeConnector(resolve),
        transport=handler_transport(handler),
    )


@pytest.fixture
def stand_in_api() -> Callable[[Mapping[str, bytes]], JsonFetcher]:
    return _stand_in_api


@pytest.fixture
def scripted_api(
    stand_in_api: Callable[[Mapping[str, bytes]], JsonFetcher],
) -> Callable[[Callable[[JsonRequest], bytes], list[JsonRequest]], JsonFetcher]:
    """A stand-in API whose answer to each request is `answer(request)`, which sees the body and headers too (a paged
    list's pages differ by them); every request it gets is added to `sent`."""

    def make(answer: Callable[[JsonRequest], bytes], sent: list[JsonRequest]) -> JsonFetcher:
        async def send(request: JsonRequest, policy: FetchPolicy) -> FetchResult:
            sent.append(request)
            return await stand_in_api({request.url: answer(request)})(request, policy)

        return send

    return make
