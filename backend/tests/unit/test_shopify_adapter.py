"""The Shopify adapter (SPEC-15 §4.2 to §4.5): detect storefront collection URLs, locale-prefixed ones too, ask the
Storefront API for their collection, page through its cursor, and tell the platform's answer from any other. Product
pages take the page path (D-1118).

Shopify is a multi-tenant platform, not a site (C6, C9). Shops and answers are synthetic (`example.test` hosts,
invented handles and products, C3).
"""

import asyncio
import json
from collections.abc import Callable
from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import Any

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher, JsonRequest, fetch_json
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import NOT_PLATFORM, NOT_SERVED, AdapterMatch
from crawlerai.adapters.registry import Registry
from crawlerai.adapters.shopify import API_VERSION, Shopify
from tests.stand_in import CONNECT_FAILED, IMPERSONATE, handler_transport

ADAPTER = Shopify()
SHOP = "shop.example.test"
PAGE = f"https://{SHOP}/collections/widgets"
ENDPOINT = f"https://{SHOP}/api/{API_VERSION}/graphql.json"
# A shop that presents its prices in one currency only.
ONE_CURRENCY: JsonValue = {"paymentSettings": {"enabledPresentmentCurrencies": ["EUR"]}}

handles = st.from_regex(r"[a-z0-9][a-z0-9_-]{0,40}", fullmatch=True)


@given(handle=handles, scheme=st.sampled_from(["http", "https"]))
def test_a_collection_url_without_a_query_is_a_listing_of_its_handle(handle: str, scheme: str) -> None:
    assert ADAPTER.detect(f"{scheme}://{SHOP}/collections/{handle}") == AdapterMatch(SHOP, "listing", handle)
    assert ADAPTER.detect(f"{scheme}://{SHOP.upper()}/collections/{handle}/") == AdapterMatch(SHOP, "listing", handle)
    assert ADAPTER.detect(f"https://{SHOP}/collections/{handle}?page=2") is None


@given(handle=handles, query=st.sampled_from(["", "?variant=7"]))
def test_a_product_page_is_left_to_the_page_path(handle: str, query: str) -> None:
    # D-1118: the page states fields the API's answer lacks.
    assert ADAPTER.detect(f"https://{SHOP}/products/{handle}{query}") is None
    assert ADAPTER.detect(f"https://{SHOP}/collections/all/products/{handle}") is None


@pytest.mark.parametrize(
    "url",
    [
        f"https://{SHOP}/",
        f"https://{SHOP}/collections",
        f"https://{SHOP}/collections/a/b",
        f"https://{SHOP}/collections/..",
        f"https://{SHOP}/collections/widgets.atom",  # another representation of the collection, not its page
        f"https://{SHOP}/collections/%C3%A9t%C3%A9",  # a percent-encoded handle is left to the generic path
        f"https://{SHOP}/english/collections/widgets",  # not a locale subfolder
        f"https://{SHOP}/fr/products/widget",
        f"https://{SHOP}/fr/collections",
        f"https://{SHOP}/collections/widgets?sort_by=price",
        f"https://{SHOP}/pages/about",
        f"ftp://{SHOP}/collections/widgets",
    ],
)
def test_other_urls_are_not_detected(url: str) -> None:
    assert ADAPTER.detect(url) is None


def test_it_serves_storefront_api_endpoints_of_any_version_on_the_pages_host() -> None:
    # SPEC-15 §4.7: the endpoint is on the page's own host.
    page = AdapterMatch(tenant=SHOP, page_kind="listing", item="widgets")
    assert ADAPTER.serves(page, ENDPOINT) is True
    assert ADAPTER.serves(page, f"https://{SHOP.upper()}/api/2025-01/graphql.json") is True
    assert ADAPTER.serves(page, f"https://{SHOP}/collections/widgets") is False
    assert ADAPTER.serves(page, f"https://{SHOP}/api/unstable/graphql.json") is False
    assert ADAPTER.serves(page, f"https://other.example.test/api/{API_VERSION}/graphql.json") is False


Handler = Callable[[httpx.Request], httpx.Response]


def _send(handler: Handler) -> JsonFetcher:
    async def resolve(_host: str) -> list[IPv4Address | IPv6Address]:
        return [ip_address("93.184.215.14")]

    async def send(request: JsonRequest, policy: FetchPolicy) -> FetchResult:
        connector = SafeConnector(resolve)
        transport = handler_transport(handler)
        return await fetch_json(
            request, policy, engine_version="test", impersonate=IMPERSONATE, connector=connector, transport=transport
        )

    return send


def _platform(answer: JsonValue, status: int = 200) -> Handler:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=answer, headers={"X-Shopify-API-Version": API_VERSION})

    return handler


def _fetch(url: str, handler: Handler) -> FetchResult:
    return asyncio.run(ADAPTER.fetch(url, FetchPolicy(), _send(handler)))


def test_a_page_is_asked_of_the_storefront_api_with_its_handle_as_a_variable() -> None:
    page = PAGE
    sent: list[httpx.Request] = []
    answer: JsonValue = {"data": {"shop": ONE_CURRENCY, "collection": {"products": {"nodes": []}}}}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return _platform(answer)(request)

    result = _fetch(page, handler)

    (request,) = sent
    body = json.loads(request.content)
    assert (request.method, request.headers["Host"], request.url.path) == (
        "POST",
        SHOP,
        f"/api/{API_VERSION}/graphql.json",
    )
    assert request.headers["Content-Type"] == "application/json"
    assert body["variables"] == {"handle": page.rsplit("/", 1)[1]}
    assert "collection(handle: $handle)" in body["query"]
    manifest = result.bundle.manifest
    assert (manifest.method, manifest.block_class, manifest.url, manifest.final_url) == ("api", "ok", page, ENDPOINT)
    assert json.loads(result.bundle.body) == answer


def _error(result: FetchResult) -> tuple[str, str | None, bytes]:
    return result.block_class, result.attempts[-1].error, result.bundle.body


@pytest.mark.parametrize("status", [200, 404, 405])
def test_an_answer_without_the_platform_signal_is_not_the_platform(status: int) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"data": {"collection": {"products": {"nodes": []}}}})

    result = _fetch(PAGE, handler)

    assert _error(result) == ("error", NOT_PLATFORM, b"")
    assert result.bundle.manifest.status_code == status


@pytest.mark.parametrize(
    "answer",
    [
        {"data": {"collection": None}},
        {"data": None, "errors": [{"message": "Throttled"}]},
        {"data": {"collection": {"products": {"nodes": []}}}, "errors": [{"message": "partial"}]},
        [],
    ],
)
def test_a_platform_answer_without_the_collection_does_not_serve_the_page(answer: JsonValue) -> None:
    result = _fetch(PAGE, _platform(answer))

    assert _error(result) == ("error", NOT_SERVED, b"")


def test_a_platform_status_failure_is_kept_as_it_is() -> None:
    result = _fetch(PAGE, _platform({}, status=429))

    assert (result.block_class, result.attempts[-1].error, result.bundle.manifest.status_code) == ("blocked", None, 429)


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_a_slow_down_or_server_error_without_the_signal_says_nothing_about_the_platform(status: int) -> None:
    # An edge in front of the shop answers these for the whole host, without the API's version header.
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers={"Retry-After": "2"})

    result = _fetch(PAGE, handler)

    assert (result.attempts[-1].error, result.bundle.manifest.status_code) == (None, status)
    assert result.block_class != "ok"


def test_a_host_answering_a_slow_down_is_not_declined() -> None:
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.url.path)
        return httpx.Response(429)

    registry = Registry([ADAPTER], active={"shopify"})
    send = _send(handler)
    for _ in range(2):
        asyncio.run(registry.serve(PAGE, FetchPolicy(), send))

    assert sent == [f"/api/{API_VERSION}/graphql.json"] * 2


def test_a_fetch_with_no_response_says_nothing_about_the_platform() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    result = _fetch(PAGE, handler)

    assert (result.block_class, result.attempts[-1].error) == ("error", CONNECT_FAILED)


def test_the_endpoint_keeps_the_pages_port_and_drops_its_user_information() -> None:
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.headers["Host"] + request.url.path)
        return _platform({"data": {"shop": ONE_CURRENCY, "collection": {"products": {"nodes": []}}}})(request)

    _fetch(f"https://user:secret@{SHOP}:8443/collections/widgets", handler)

    assert sent == [f"{SHOP}:8443/api/{API_VERSION}/graphql.json"]


def test_a_url_it_does_not_detect_is_refused() -> None:
    fetch = ADAPTER.fetch(f"https://{SHOP}/pages/about", FetchPolicy(), _send(_platform({})))
    with pytest.raises(ValueError, match="not a storefront URL"):
        asyncio.run(fetch)


@pytest.mark.parametrize(("locale", "language"), [("fr", "FR"), ("en-ca", "EN"), ("pt-BR", "PT")])
def test_a_locale_prefixed_collection_is_asked_in_its_language(locale: str, language: str) -> None:
    # D-1386: the subfolder's language subtag (RFC 5646 §2.2.1) is the query's `@inContext(language:)`.
    page = f"https://{SHOP}/{locale}/collections/widgets"
    sent: list[dict[str, Any]] = []
    answer: JsonValue = {
        "data": {
            "shop": ONE_CURRENCY,
            "localization": {"language": {"isoCode": language}},
            "collection": {"products": {"nodes": []}},
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return _platform(answer)(request)

    result = _fetch(page, handler)

    assert ADAPTER.detect(page) == AdapterMatch(SHOP, "listing", "widgets")
    [body] = sent
    assert body["variables"] == {"handle": "widgets", "language": language}
    assert "@inContext(language: $language)" in body["query"]
    assert (result.block_class, result.attempts[-1].error) == ("ok", None)


def test_a_locale_prefixed_collection_the_shop_answers_in_another_language_is_not_served() -> None:
    # A shop that does not publish the language answers in its default one, which the page does not show.
    answer: JsonValue = {
        "data": {
            "shop": ONE_CURRENCY,
            "localization": {"language": {"isoCode": "EN"}},
            "collection": {"products": {"nodes": []}},
        }
    }

    result = _fetch(f"https://{SHOP}/fr/collections/widgets", _platform(answer))

    assert _error(result) == ("error", NOT_SERVED, b"")


def _products_page(names: list[str], cursor: str | None) -> JsonValue:
    nodes: list[JsonValue] = [{"id": f"gid://synthetic/Product/{name}", "title": name} for name in names]
    info: JsonValue = {"hasNextPage": cursor is not None, "endCursor": cursor}
    return {"data": {"shop": ONE_CURRENCY, "collection": {"products": {"pageInfo": info, "nodes": nodes}}}}


def _paged(pages: dict[str | None, JsonValue], sent: list[str | None]) -> Handler:
    """Answers each request with the page its `after` variable names (None: the first)."""

    def handler(request: httpx.Request) -> httpx.Response:
        after = json.loads(request.content)["variables"].get("after")
        sent.append(after)
        return _platform(pages[after])(request)

    return handler


def test_a_collection_of_several_pages_is_read_through_its_cursor_into_one_answer() -> None:
    # D-1385: the connection's `endCursor` asks the next page while `hasNextPage` holds.
    pages = {None: _products_page(["a", "b"], "c1"), "c1": _products_page(["c"], "c2"), "c2": _products_page([], None)}
    sent: list[str | None] = []

    result = _fetch(PAGE, _paged(pages, sent))

    answer = json.loads(result.bundle.body)
    assert sent == [None, "c1", "c2"]
    assert [node["title"] for node in answer["data"]["collection"]["products"]["nodes"]] == ["a", "b", "c"]
    assert answer["data"]["shop"] == ONE_CURRENCY
    assert [attempt.method for attempt in result.attempts] == ["api", "api", "api"]
    assert (result.block_class, result.bundle.manifest.url) == ("ok", PAGE)


def test_the_cursor_is_not_followed_past_the_rows_the_request_asks_for() -> None:
    pages = {None: _products_page(["a", "b"], "c1"), "c1": _products_page(["c"], None)}
    sent: list[str | None] = []

    result = asyncio.run(ADAPTER.fetch(PAGE, FetchPolicy(max_rows=2), _send(_paged(pages, sent))))

    assert sent == [None]
    assert len(json.loads(result.bundle.body)["data"]["collection"]["products"]["nodes"]) == 2
