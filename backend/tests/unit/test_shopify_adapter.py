"""The Shopify adapter: detect storefront collection URLs, locale-prefixed ones too, ask the
Storefront API for their collection, page through its cursor, serve only the products the page lists, and tell the
platform's answer from any other. Product
pages take the page path.

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

from snowcrawl.acquire.api import JsonFetcher, JsonRequest, fetch_json
from snowcrawl.acquire.ssrf import SafeConnector
from snowcrawl.acquire.types import FetchPolicy, FetchResult
from snowcrawl.adapters.base import NOT_SERVED, AdapterMatch, PageRefs
from snowcrawl.adapters.shopify import API_VERSION, Shopify
from tests.stand_in import IMPERSONATE, handler_transport

ADAPTER = Shopify()
SHOP = "shop.example.test"
PAGE = f"https://{SHOP}/collections/widgets"
ENDPOINT = f"https://{SHOP}/api/{API_VERSION}/graphql.json"
# A shop that presents its prices in one currency only.
ONE_CURRENCY: JsonValue = {"paymentSettings": {"enabledPresentmentCurrencies": ["EUR"]}}

handles = st.from_regex(r"[a-z0-9][a-z0-9_-]{0,40}", fullmatch=True)


@given(handle=handles, scheme=st.sampled_from(["http", "https"]))
def test_a_collection_url_is_a_listing_of_its_handle(handle: str, scheme: str) -> None:
    assert ADAPTER.detect(f"{scheme}://{SHOP}/collections/{handle}") == AdapterMatch(SHOP, "listing", handle)
    assert ADAPTER.detect(f"{scheme}://{SHOP.upper()}/collections/{handle}/") == AdapterMatch(SHOP, "listing", handle)
    assert ADAPTER.detect(f"https://{SHOP}/collections/{handle}?page=2") == AdapterMatch(SHOP, "listing", handle)


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


def _fetch(url: str, handler: Handler, links: tuple[str, ...] = (f"https://{SHOP}/products/a",)) -> FetchResult:
    return asyncio.run(ADAPTER.fetch_listed(url, PageRefs(own=(url,), links=links), FetchPolicy(), _send(handler)))


def _product(handle: str) -> JsonValue:
    price: JsonValue = {"amount": "5.00", "currencyCode": "EUR"}
    return {
        "handle": handle,
        "title": handle.upper(),
        "priceRange": {"minVariantPrice": price, "maxVariantPrice": price},
    }


def test_a_page_of_a_paged_collection_is_served_with_its_own_products_only() -> None:
    # The theme shows two products a page; the API pages its four by cursor. The page links its two (and a product
    # of the shop's menu that is not in the collection): the answer holds those two, in the page's order.
    pages: dict[str | None, JsonValue] = {
        None: {"pageInfo": {"hasNextPage": True, "endCursor": "c2"}, "nodes": [_product("a"), _product("b")]},
        "c2": {"pageInfo": {"hasNextPage": False, "endCursor": "c4"}, "nodes": [_product("c"), _product("d")]},
    }
    sent: list[JsonValue] = []

    def handler(request: httpx.Request) -> httpx.Response:
        after = json.loads(request.content)["variables"].get("after")
        sent.append(after)
        answer: JsonValue = {"data": {"shop": ONE_CURRENCY, "collection": {"products": pages[after]}}}
        return _platform(answer)(request)

    links = tuple(
        f"https://{SHOP}{path}" for path in ("/products/menu", "/products/d", "/collections/widgets/products/c")
    )
    result = _fetch(f"{PAGE}?page=2", handler, links)

    assert (result.block_class, sent) == ("ok", [None, "c2"])
    nodes = json.loads(result.bundle.body)["data"]["collection"]["products"]["nodes"]
    assert [node["handle"] for node in nodes] == ["d", "c"]


def test_a_page_is_asked_of_the_storefront_api_with_its_handle_as_a_variable() -> None:
    page = PAGE
    sent: list[httpx.Request] = []
    answer: JsonValue = {"data": {"shop": ONE_CURRENCY, "collection": {"products": {"nodes": [_product("a")]}}}}

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


@pytest.mark.parametrize("currencies", [["EUR", "SEK"], []])
def test_a_shop_whose_page_may_show_another_currency_is_left_to_the_page_path(currencies: list[JsonValue]) -> None:
    # The answer prices in the shop's primary market and the page in its visitor's: the page path reads the prices the
    # page shows, where the answer could give none (C7).
    shop: JsonValue = {"paymentSettings": {"enabledPresentmentCurrencies": currencies}}
    answer: JsonValue = {"data": {"shop": shop, "collection": {"products": {"nodes": [_product("a")]}}}}

    result = _fetch(PAGE, _platform(answer))

    assert (result.block_class, result.attempts[-1].error) == ("error", NOT_SERVED)
