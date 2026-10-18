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

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher, JsonRequest, fetch_json
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import AdapterMatch
from crawlerai.adapters.shopify import API_VERSION, Shopify
from tests.stand_in import IMPERSONATE, handler_transport

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
