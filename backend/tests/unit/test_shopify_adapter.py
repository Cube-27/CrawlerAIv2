"""The Shopify adapter (SPEC-15 §4.2 to §4.5): detect storefront collection URLs, ask the Storefront API for their
collection, and tell the platform's answer from any other. Product pages take the page path (D-1118).

Shopify is a multi-tenant platform, not a site (C6, C9). Shops and answers are synthetic (`example.test` hosts,
invented handles and products, C3).
"""

import asyncio
import json
from collections.abc import Callable
from ipaddress import IPv4Address, IPv6Address, ip_address

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
        f"https://{SHOP}/fr/collections/widgets",  # a locale-prefixed page
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
        transport = httpx.MockTransport(handler)
        return await fetch_json(request, policy, engine_version="test", connector=connector, transport=transport)

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

    assert (result.block_class, result.attempts[-1].error) == ("error", "network_error: ConnectError")


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
