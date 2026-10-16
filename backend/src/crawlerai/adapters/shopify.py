"""Shopify storefront collections through the Storefront API (SPEC-15).

Endpoint, verified against the platform's Storefront API documentation (shopify.dev/docs/api/storefront, 2026-10-16):
every shop answers `POST /api/{version}/graphql.json` on its own domain, and tokenless access serves products and
collections, with a query complexity limit of 1,000. Every API response carries `X-Shopify-API-Version`, the version
that served it (shopify.dev/docs/api/usage/versioning); a retired version falls forward to the oldest supported one.

Shops live on their own domains, so a page URL alone does not say a page is a shop's: the platform's online store
route for a collection (`/collections/{handle}`) is the candidate, and the answer's version header is the platform's
signal. An answer without it is `NOT_PLATFORM`; one with it that holds no collection for the handle, or GraphQL
`errors`, is `NOT_SERVED`. Either way the page falls back to the generic rungs (SPEC-15 §4.6).

Product pages are not served (D-1118): the page states fields the API's answer lacks (its default variant's sku,
condition, rating, review count), so a product page takes the page path, which reads them with the variants the page
states.
"""

import json
import re
from dataclasses import replace
from http import HTTPStatus
from typing import Final
from urllib.parse import urlsplit

from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.outcome import as_error
from crawlerai.acquire.robots import at_origin
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import ALL, NOT_PLATFORM, NOT_SERVED, AdapterMatch, Members, Shape

API_VERSION: Final = "2026-10"
# The Storefront API's endpoint path of any version: versions are named `YYYY-MM` (API versioning documentation).
_ENDPOINT_PATH: Final = re.compile(r"/api/\d{4}-\d{2}/graphql\.json", re.ASCII)
# Versioning documentation: "API responses include the X-Shopify-API-Version header".
SIGNAL: Final = "x-shopify-api-version"
# A handle is a collection's URL name: lowercase letters, digits, hyphens and underscores in practice
# (Liquid `handle` filter); a handle with other characters is percent-encoded in the URL and left to the generic path.
_HANDLE: Final = re.compile(r"[\w-]+", re.ASCII)
# The query asks for the currencies the shop presents prices in (`PaymentSettings.enabledPresentmentCurrencies`, "A
# list of enabled currencies (ISO 4217 format) that the shop accepts"): a tokenless answer prices in the shop's primary
# market, while a page shows the market of its visitor (`_one_currency`).
_COLLECTION_QUERY: Final = """query Collection($handle: String!) {
  shop { paymentSettings { enabledPresentmentCurrencies } }
  collection(handle: $handle) {
    products(first: 250) {
      nodes {
        id title onlineStoreUrl
        featuredImage { url }
        priceRange { minVariantPrice { amount currencyCode } maxVariantPrice { amount currencyCode } }
      }
    }
  }
}"""


def _bound(at: Members) -> Shape:
    """An Offer whose price is the `MoneyV2` at `at`."""
    return Shape(type="Offer", at=at, properties={"price": ("amount",), "priceCurrency": ("currencyCode",)})


# A collection lists its products (schema.org ItemList). A listed product's two Offers are its price range's bounds:
# equal bounds are the one price of every variant, and different ones agree on no single price (INV-14).
_LISTED: Final = Shape(
    type="Product",
    at=("nodes", ALL),
    properties={"name": ("title",), "url": ("onlineStoreUrl",), "image": ("featuredImage", "url")},
    nodes={"offers": (_bound(("priceRange", "minVariantPrice")), _bound(("priceRange", "maxVariantPrice")))},
)
_LISTING: Final = Shape(type="ItemList", at=("data", "collection", "products"), nodes={"itemListElement": (_LISTED,)})
# A listing of a shop whose page may show another currency than the answer's: its rows without their Offers (C7).
_UNPRICED_LISTING: Final = replace(_LISTING, nodes={"itemListElement": (replace(_LISTED, nodes={}),)})


class Shopify:
    name: Final = "shopify"

    def detect(self, url: str) -> AdapterMatch | None:
        parts = urlsplit(url)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            return None
        match parts.path.removesuffix("/").split("/"):
            # A collection URL with a query shows a page, an order or a filter of it, which the first page of the
            # unqueried collection does not reproduce.
            case ["", "collections", handle] if _HANDLE.fullmatch(handle) and not parts.query:
                return AdapterMatch(tenant=parts.hostname, page_kind="listing", item=handle)
        return None

    def serves(self, match: AdapterMatch, endpoint: str) -> bool:
        # SPEC-15 §4.7: the API path on the page's own host (the tenant), where `fetch` asks it.
        parts = urlsplit(endpoint)
        return parts.hostname == match.tenant and _ENDPOINT_PATH.fullmatch(parts.path) is not None

    async def fetch(self, url: str, policy: FetchPolicy, send: JsonFetcher) -> FetchResult:
        match = self.detect(url)
        if match is None:
            raise ValueError("not a storefront URL this adapter detects")
        request = JsonRequest(
            url=at_origin(url, f"/api/{API_VERSION}/graphql.json"),
            page_url=url,
            method="POST",
            headers=(("Content-Type", "application/json"),),
            # The handle goes in as a GraphQL variable, never into the query's text.
            body=json.dumps({"query": _COLLECTION_QUERY, "variables": {"handle": match.item}}),
        )
        return _verdict(await send(request, policy))

    def shapes(self, _match: AdapterMatch, answer: JsonValue, /) -> tuple[Shape, ...]:
        return (_LISTING if _one_currency(answer) else _UNPRICED_LISTING,)


def _transient(status: int) -> bool:
    """A status that says the server cannot answer now rather than what it is (RFC 6585 §4: 429, too many requests;
    RFC 9110 §15.6: a 5xx server error). An edge in front of a shop answers these without the API's header."""
    return status == HTTPStatus.TOO_MANY_REQUESTS or status >= HTTPStatus.INTERNAL_SERVER_ERROR


def _one_currency(answer: JsonValue) -> bool:
    """Whether the shop presents its prices in one currency only, so that the answer's prices are in the currency any
    page of the shop shows. A tokenless answer prices in the shop's primary market (`@inContext` names no other), while
    the page shows its visitor's market; with several currencies they may differ, and nothing in the answer says which
    one a page showed (C7: decline rather than guess)."""
    shop = _member(_member(answer, "data"), "shop")
    currencies = _member(_member(shop, "paymentSettings"), "enabledPresentmentCurrencies")
    return isinstance(currencies, list) and len(currencies) == 1


def _member(value: JsonValue, name: str) -> JsonValue:
    return value.get(name) if isinstance(value, dict) else None


def _verdict(result: FetchResult) -> FetchResult:
    """`result`, or why it does not serve the page. No response, a slow-down or a server error is kept as it is: it
    says nothing of the platform, and the page falls back. An answer without the platform's signal is `NOT_PLATFORM`;
    the platform's answer holding errors or no collection is `NOT_SERVED`."""
    manifest = result.bundle.manifest
    if manifest.status_code == 0 or _transient(manifest.status_code):
        return result
    if not any(name.lower() == SIGNAL for name, _ in manifest.headers.response):
        return as_error(result, NOT_PLATFORM)
    if result.block_class != "ok":
        return result
    # `fetch_json` checked that an `ok` body is JSON (RFC 8259); GraphQL answers with an object.
    answer = json.loads(result.bundle.body)
    served = (
        isinstance(answer, dict)
        and not answer.get("errors")
        and isinstance(_member(answer.get("data"), "collection"), dict)
    )
    return result if served else as_error(result, NOT_SERVED)
