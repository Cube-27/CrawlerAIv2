"""Shopify storefronts through the Storefront API (SPEC-15).

Endpoint, verified against the platform's Storefront API documentation (shopify.dev/docs/api/storefront, 2026-10-16):
every shop answers `POST /api/{version}/graphql.json` on its own domain, and tokenless access serves products and
collections, with a query complexity limit of 1,000. Every API response carries `X-Shopify-API-Version`, the version
that served it (shopify.dev/docs/api/usage/versioning); a retired version falls forward to the oldest supported one.

Shops live on their own domains, so a page URL alone does not say a page is a shop's: the platform's online store
routes (`/products/{handle}`, `/collections/{handle}`) are the candidates, and the answer's version header is the
platform's signal. An answer without it is `NOT_PLATFORM`; one with it that holds no product or collection for the
handle, or GraphQL `errors`, is `NOT_SERVED`. Either way the page falls back to the generic rungs (SPEC-15 §4.6).
"""

import json
import re
from collections.abc import Mapping
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
from crawlerai.db.models import PageKind

API_VERSION: Final = "2026-10"
# The Storefront API's endpoint path of any version: versions are named `YYYY-MM` (API versioning documentation).
_ENDPOINT_PATH: Final = re.compile(r"/api/\d{4}-\d{2}/graphql\.json", re.ASCII)
# Versioning documentation: "API responses include the X-Shopify-API-Version header".
SIGNAL: Final = "x-shopify-api-version"
# A handle is a product's or collection's URL name: lowercase letters, digits, hyphens and underscores in practice
# (Liquid `handle` filter); a handle with other characters is percent-encoded in the URL and left to the generic path.
_HANDLE: Final = re.compile(r"[\w-]+", re.ASCII)
# GraphQL Admin API, `ProductVariantsBulkCreateStrategy`: a product without options has one standalone default
# variant titled "Default Title"; the title names no variant.
_DEFAULT_TITLE: Final = "Default Title"
# schema.org ItemAvailability members, by their IRIs.
_IN_STOCK, _BACK_ORDER, _OUT_OF_STOCK = (f"https://schema.org/{m}" for m in ("InStock", "BackOrder", "OutOfStock"))

# Both queries ask for the currencies the shop presents prices in (`PaymentSettings.enabledPresentmentCurrencies`, "A
# list of enabled currencies (ISO 4217 format) that the shop accepts"): a tokenless answer prices in the shop's primary
# market, while a page shows the market of its visitor (`_one_currency`).
_PRODUCT_QUERY: Final = """query Product($handle: String!) {
  shop { paymentSettings { enabledPresentmentCurrencies } }
  product(handle: $handle) {
    id title description vendor onlineStoreUrl
    featuredImage { url }
    variants(first: 250) {
      nodes { id title sku barcode availableForSale currentlyNotInStock price { amount currencyCode } }
    }
  }
}"""
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
# The query of each page kind, and the member of the answer's `data` that holds its product or collection.
_QUERIES: Final[dict[PageKind, tuple[str, str]]] = {
    "detail": (_PRODUCT_QUERY, "product"),
    "listing": (_COLLECTION_QUERY, "collection"),
}


def _availability(variant: Mapping[str, JsonValue]) -> tuple[JsonValue, Members] | None:
    """The schema.org availability the variant's two documented booleans state (`ProductVariant`):
    `availableForSale` "Indicates if the product variant is available for sale"; `currentlyNotInStock` "out of stock
    but still available for purchase (used for backorders)", schema.org BackOrder."""
    match variant.get("availableForSale"), variant.get("currentlyNotInStock"):
        case False, _:
            return _OUT_OF_STOCK, ("availableForSale",)
        case True, True:
            return _BACK_ORDER, ("currentlyNotInStock",)
        case True, False:
            return _IN_STOCK, ("availableForSale",)
    return None


def _variant_name(variant: Mapping[str, JsonValue]) -> tuple[JsonValue, Members] | None:
    title = variant.get("title")
    return None if title == _DEFAULT_TITLE else (title, ("title",))


def _bound(at: Members) -> Shape:
    """An Offer whose price is the `MoneyV2` at `at`."""
    return Shape(type="Offer", at=at, properties={"price": ("amount",), "priceCurrency": ("currencyCode",)})


# A product is a schema.org ProductGroup ("a group of Products that vary only in certain well-described ways"). Its
# `vendor` ("the manufacturer, wholesaler, or other vendor for the product", Help Center, "Product details") is its
# schema.org `brand`, as in the platform's own schema.org output (Liquid `structured_data` filter: its documented
# example states the example shop's vendor as the product's brand). Each
# variant a Product under `hasVariant`, whose Offer is a view of the variant anchored at its `price`. Its image is the
# featured image ("functionally equivalent to images(first: 1)"): every image would be several values of one property,
# which a single image field cannot choose among.
_VARIANT: Final = Shape(
    type="Product",
    at=("variants", "nodes", ALL),
    properties={"sku": ("sku",), "gtin": ("barcode",), "productID": ("id",)},
    stated={"name": _variant_name},
    nodes={
        "offers": (
            Shape(
                type="Offer",
                properties={"price": ("price", "amount"), "priceCurrency": ("price", "currencyCode")},
                stated={"availability": _availability},
                anchor=("price",),
            ),
        )
    },
)
_PRODUCT: Final = Shape(
    type="ProductGroup",
    at=("data", "product"),
    properties={
        "name": ("title",),
        "description": ("description",),
        "url": ("onlineStoreUrl",),
        "productID": ("id",),
        "image": ("featuredImage", "url"),
        "brand": ("vendor",),
    },
    nodes={"hasVariant": (_VARIANT,)},
)
# A collection lists its products (schema.org ItemList). A listed product's two Offers are its price range's bounds:
# equal bounds are the one price of every variant, and different ones agree on no single price (INV-14).
_LISTED: Final = Shape(
    type="Product",
    at=("nodes", ALL),
    properties={"name": ("title",), "url": ("onlineStoreUrl",), "image": ("featuredImage", "url")},
    nodes={"offers": (_bound(("priceRange", "minVariantPrice")), _bound(("priceRange", "maxVariantPrice")))},
)
_SHAPES: Final[dict[PageKind, tuple[Shape, ...]]] = {
    "detail": (_PRODUCT,),
    "listing": (Shape(type="ItemList", at=("data", "collection", "products"), nodes={"itemListElement": (_LISTED,)}),),
}
# A listing of a shop whose page may show another currency than the answer's: its rows without their Offers (C7).
_UNPRICED_LISTING: Final = (replace(_SHAPES["listing"][0], nodes={"itemListElement": (replace(_LISTED, nodes={}),)}),)


class Shopify:
    name: Final = "shopify"

    def detect(self, url: str) -> AdapterMatch | None:
        parts = urlsplit(url)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            return None
        match parts.path.removesuffix("/").split("/"):
            case ["", "products", handle] if _HANDLE.fullmatch(handle):
                return AdapterMatch(tenant=parts.hostname, page_kind="detail", item=handle)
            case ["", "collections", collection, "products", handle] if _handles(collection, handle):
                return AdapterMatch(tenant=parts.hostname, page_kind="detail", item=handle)
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
        query, member = _QUERIES[match.page_kind]
        request = JsonRequest(
            url=at_origin(url, f"/api/{API_VERSION}/graphql.json"),
            page_url=url,
            method="POST",
            headers=(("Content-Type", "application/json"),),
            # The handle goes in as a GraphQL variable, never into the query's text.
            body=json.dumps({"query": query, "variables": {"handle": match.item}}),
        )
        return _verdict(await send(request, policy), match.page_kind, member)

    def shapes(self, page_kind: PageKind, answer: JsonValue, /) -> tuple[Shape, ...]:
        if page_kind == "listing" and not _one_currency(answer):
            return _UNPRICED_LISTING
        return _SHAPES[page_kind]


def _handles(*segments: str) -> bool:
    return all(_HANDLE.fullmatch(segment) for segment in segments)


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


def _verdict(result: FetchResult, page_kind: PageKind, member: str) -> FetchResult:
    """`result`, or why it does not serve the page. No response, a slow-down or a server error is kept as it is: it
    says nothing of the platform, and the page falls back. An answer without the platform's signal is `NOT_PLATFORM`;
    the platform's answer holding errors or no `member` is `NOT_SERVED`, and so is a product of a shop that may show
    the page in another currency than the answer's: a detail page is read for its price, which the page states."""
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
        and isinstance(_member(answer.get("data"), member), dict)
        and (page_kind == "listing" or _one_currency(answer))
    )
    return result if served else as_error(result, NOT_SERVED)
