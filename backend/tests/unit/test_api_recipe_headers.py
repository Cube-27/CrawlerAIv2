"""Header minimization by replay (SPEC-09 §4.6): a recipe starts with `Accept: application/json` only and keeps a
captured header only when adding it makes the replay reproduce every sample page's values; credentials, tokens and
headers that vary per page are never sent, and a recipe that needs one is not learnable.

A local server on 127.0.0.1 answers for synthetic `.test` hosts; the replay goes through `fetch_json`.
"""

import asyncio
import json
import threading
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import IPv4Address
from typing import ClassVar
from urllib.parse import urlsplit

import httpx
import pytest
from pydantic import JsonValue

from crawlerai.acquire.api import JsonRequest, fetch_json
from crawlerai.acquire.ssrf import SafeConnector, Target
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.config_ir.api_recipe.binding import CapturedRequest, Sample
from crawlerai.config_ir.api_recipe.headers import NotLearnable, Proven, minimize
from crawlerai.config_ir.api_recipe.model import RequestSpec
from crawlerai.config_ir.api_recipe.replay import ReplayPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

SCHEMA = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="synthetic",
    version=1,
    page_kind="detail",
    fields={
        "title": FieldSpec(type=FieldType.TEXT, description="d", required=True),
        "price": FieldSpec(type=FieldType.MONEY, description="d", required=True),
    },
)
MAP = {"title": "$['data']['name']", "price": "$['data']['price']+$['data']['currency']"}
PRODUCTS = {"desk-lamp": ("Desk Lamp", 19.5), "oak-chair": ("Oak Chair", 120)}
SITE = "https://shop.example.test"
HEX_KEY = "0123456789abcdef" * 2


def _page_url(slug: str) -> str:
    return f"{SITE}/p/{slug}"


def _required(path: str, headers: Mapping[str, str]) -> bool:
    """What each endpoint of the server needs from a request, by its first path segment."""
    mode, slug = path.split("/")[1], path.split("/")[-1]
    needs = {
        "plain": True,
        "xrw": headers.get("x-requested-with") == "XMLHttpRequest",
        "referer": headers.get("referer") == _page_url(slug),
        "two": "x-requested-with" in headers and "x-client" in headers,
        "cookie": "cookie" in headers,
        "auth": "authorization" in headers,
        "key": "x-api-key" in headers,
        "trace": "x-trace" in headers,
    }
    return needs.get(mode, True)


class Handler(BaseHTTPRequestHandler):
    received: ClassVar[list[dict[str, str]]] = []

    def do_GET(self) -> None:
        headers = {name.lower(): value for name, value in self.headers.items()}
        Handler.received.append(headers)
        path = urlsplit(self.path).path
        if not _required(path, headers):
            self._send(403, {"error": "forbidden"})
            return
        name, price = PRODUCTS[path.split("/")[-1]]
        # `wrong`: the endpoint answers, but not with the page's values.
        amount = price + 1 if path.startswith("/wrong/") else price
        self._send(200, {"data": {"name": name, "price": amount, "currency": "EUR"}})

    def _send(self, status: int, document: JsonValue) -> None:
        body = json.dumps(document).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


class PinToLoopback(SafeConnector):
    """Pins every URL to 127.0.0.1, which the real guard would refuse: the test server is local."""

    async def check(self, url: str) -> Target:
        parts = httpx.URL(url)
        return Target(url=url, host=parts.host, port=parts.port or 80, ip=IPv4Address("127.0.0.1"))


@pytest.fixture(scope="module")
def port() -> Iterator[int]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def received() -> list[dict[str, str]]:
    Handler.received = []
    return Handler.received


def _browser_headers(page_url: str) -> list[tuple[str, str]]:
    return [
        ("User-Agent", "SyntheticBrowser/1.0 (X11)"),
        ("Accept", "*/*"),
        ("Referer", page_url),
        ("X-Requested-With", "XMLHttpRequest"),
        ("Accept-Language", "en"),
    ]


Extra = Callable[[str], list[tuple[str, str]]]


def _no_extra(_slug: str) -> list[tuple[str, str]]:
    return []


def _pages(endpoint: str, extra: Extra = _no_extra) -> list[ReplayPage]:
    pages = []
    for slug, (name, price) in PRODUCTS.items():
        page_url = _page_url(slug)
        headers = (*_browser_headers(page_url), *extra(slug))
        request = CapturedRequest("GET", f"{endpoint}/products/{slug}", headers=headers)
        ctx = Context(captured_at=datetime(2026, 10, 14, tzinfo=UTC), base_url=page_url, page_url=page_url)
        values: dict[str, JsonValue] = {"title": name, "price": {"amount": str(price), "currency": "EUR"}}
        pages.append(ReplayPage(Sample(page_url, request), values, ctx))
    return pages


def _spec(endpoint: str) -> RequestSpec:
    return RequestSpec(method="GET", url=f"{endpoint}/products/{{p1}}", params_from_url={"p1": "path:1"})


async def _replay(request: JsonRequest) -> FetchResult:
    return await fetch_json(request, FetchPolicy(timeout_s=5), engine_version="test", connector=PinToLoopback())


def _minimize(port: int, mode: str, extra: Extra = _no_extra) -> Proven | NotLearnable:
    endpoint = f"http://api.example.test:{port}/{mode}"
    return asyncio.run(minimize(_spec(endpoint), MAP, _pages(endpoint, extra), SCHEMA, _replay))


def test_an_endpoint_that_needs_no_header_keeps_only_accept(port: int, received: list[dict[str, str]]) -> None:
    result = _minimize(port, "plain")

    endpoint = f"http://api.example.test:{port}/plain"
    assert result == Proven(
        spec=RequestSpec(
            method="GET",
            url=f"{endpoint}/products/{{p1}}",
            params_from_url={"p1": "path:1"},
            headers={"Accept": "application/json"},
        ),
        headers_tried=0,
    )
    assert [(r["accept"], "x-requested-with" in r) for r in received] == [("application/json", False)] * 2


def test_the_recipe_keeps_exactly_the_header_the_endpoint_needs(port: int) -> None:
    result = _minimize(port, "xrw")

    assert isinstance(result, Proven)
    # User-Agent, Accept and Referer were tried and dropped before X-Requested-With made the replay pass.
    assert (result.spec.headers, result.headers_tried) == (
        {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
        4,
    )


def test_a_referer_that_is_the_page_url_is_kept_as_its_template(port: int, received: list[dict[str, str]]) -> None:
    result = _minimize(port, "referer")

    assert isinstance(result, Proven)
    assert (result.spec.headers, result.headers_tried) == ({"Accept": "application/json", "Referer": "{page_url}"}, 3)
    assert [r.get("referer") for r in received[-2:]] == [_page_url(slug) for slug in PRODUCTS]


def test_an_endpoint_that_needs_two_added_headers_is_not_learnable(port: int) -> None:
    def client(_slug: str) -> list[tuple[str, str]]:
        return [("X-Client", "web")]

    assert _minimize(port, "two", client) == NotLearnable(
        reason="no single captured header makes the replay reproduce the sample values", headers_tried=6
    )


def test_an_endpoint_that_needs_a_cookie_is_not_learnable(port: int, received: list[dict[str, str]]) -> None:
    result = _minimize(port, "cookie")

    assert isinstance(result, NotLearnable)
    assert all("cookie" not in r for r in received)


def test_credentials_and_tokens_are_never_sent_and_named_when_needed(port: int, received: list[dict[str, str]]) -> None:
    def secrets(_slug: str) -> list[tuple[str, str]]:
        return [("Authorization", "Basic dTpw"), ("X-Api-Key", HEX_KEY)]

    result = _minimize(port, "auth", secrets)

    assert result == NotLearnable(
        reason="the replay needs a header a recipe never keeps (a credential, a token or a per-page value): "
        "Authorization, X-Api-Key",
        headers_tried=5,
    )
    assert all("authorization" not in r and "x-api-key" not in r for r in received)


def test_a_header_that_varies_between_pages_is_never_sent(port: int, received: list[dict[str, str]]) -> None:
    def trace(slug: str) -> list[tuple[str, str]]:
        return [("X-Trace", slug)]

    result = _minimize(port, "trace", trace)

    assert isinstance(result, NotLearnable)
    assert result.reason.endswith(": X-Trace")
    assert all("x-trace" not in r for r in received)


@pytest.mark.parametrize(
    "value",
    [
        HEX_KEY,  # hex (RFC 4648 §8)
        "dGhpcyBpcyBhIHNlY3JldCB0b2tlbg==",  # base64 (§4)
        "eyJhbGciOiJIUzI1NiJ9-_x",  # base64url (§5)
        "Token 123e4567-e89b-12d3-a456-426614174000",  # one list item of the value is a token
    ],
)
def test_a_value_that_looks_like_a_token_is_withheld(port: int, value: str) -> None:
    def key(_slug: str) -> list[tuple[str, str]]:
        return [("X-Api-Key", value)]

    result = _minimize(port, "key", key)

    assert isinstance(result, NotLearnable)
    assert result.reason.endswith(": X-Api-Key")


def test_a_form_media_type_is_not_a_token(port: int) -> None:
    def form(_slug: str) -> list[tuple[str, str]]:
        return [("X-Api-Key", "application/x-www-form-urlencoded")]

    result = _minimize(port, "key", form)

    assert isinstance(result, Proven)
    assert result.spec.headers == {"Accept": "application/json", "X-Api-Key": "application/x-www-form-urlencoded"}


def test_values_that_differ_from_the_capture_are_not_learnable(port: int) -> None:
    result = _minimize(port, "wrong")

    assert result == NotLearnable(
        reason="no single captured header makes the replay reproduce the sample values", headers_tried=5
    )
