"""Fixtures shared by unit tests: for the platform adapter tests (SPEC-02 §4.9) a stand-in API, a JSONPath selector
and the presets' schema.org projections."""

import re
from collections.abc import Callable, Mapping
from functools import partial
from ipaddress import ip_address
from typing import Any

import httpx
import pytest

from crawlerai.acquire.api import JsonFetcher, fetch_json
from crawlerai.acquire.ssrf import IPAddress, SafeConnector
from crawlerai.schemas.registry import load_presets


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


def _select(path: str, document: Any) -> list[Any]:
    """The values a mapped path selects: `$`, then `['name']` member and `[*]` wildcard segments (RFC 9535 §2.5)."""
    nodes = [document]
    for segment in re.findall(r"\['([^']*)'\]|\[\*\]", path.removeprefix("$")):
        if segment:
            nodes = [node[segment] for node in nodes if isinstance(node, dict) and segment in node]
        else:
            nodes = [item for node in nodes for item in node]
    return nodes


@pytest.fixture
def stand_in_api() -> Callable[[Mapping[str, bytes]], JsonFetcher]:
    return _stand_in_api


@pytest.fixture
def select_json() -> Callable[[str, Any], list[Any]]:
    return _select


def _preset_fields(preset: str) -> dict[str, str]:
    """The preset's `field -> schema.org path` projection, what an adapter's `map` takes."""
    (schema,) = (s for s in load_presets() if s.name == preset)
    return {name: spec.schema_org for name, spec in schema.fields.items() if spec.schema_org is not None}


@pytest.fixture
def preset_fields() -> Callable[[str], dict[str, str]]:
    return _preset_fields
