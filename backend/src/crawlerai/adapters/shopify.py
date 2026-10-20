"""Shopify storefront collections through the Storefront API (adapters spec).

Endpoint, verified against the platform's Storefront API documentation (shopify.dev/docs/api/storefront, 2026-10-16):
every shop answers `POST /api/{version}/graphql.json` on its own domain, and tokenless access serves products and
collections, with a query complexity limit of 1,000. Every API response carries `X-Shopify-API-Version`, the version
that served it (shopify.dev/docs/api/usage/versioning); a retired version falls forward to the oldest supported one.

Shops live on their own domains, so a page URL alone does not say a page is a shop's: the platform's online store
route for a collection (`/collections/{handle}`, also under a locale subfolder, `/{locale}/collections/{handle}`) is the
candidate, and the answer's version header is the platform's signal. An answer without it is `NOT_PLATFORM`; one with
it that holds no collection for the handle, or GraphQL `errors`, is `NOT_SERVED`. Either way the page falls back to the
generic rungs (adapters spec).

A collection page shows one page of the collection, of a size its theme chooses (the Liquid `paginate` tag's `by`),
which no documented API states; the Storefront API pages by cursor only (no page number or offset). So the adapter is
page-scoped (`adapters.base.PageScoped`): it serves a fetched page, and its answer holds the collection's products the
page links to (`/products/{handle}` on the page's host, also under a collection or a locale subfolder), matched by
`handle`, in the page's order; a page linking to none is `NOT_SERVED`, and the page path reads it. Any query (`?page=`,
a sort, a filter) is the page's own: its links say which products it shows. The products come in pages of at most 250
(the Storefront API's `first` limit), joined by the connection's cursor (`pageInfo { hasNextPage endCursor }`, Relay
cursor connections, the API's pagination documentation) until every product the page links to is read, up to the
adapter row cap (`adapters.paging`, D-1385). The next page of the collection is the crawl's to follow, not this one's.

A locale subfolder names the language the page shows (the platform's international domains documentation:
`/{language}` or `/{language}-{country}`): the query asks the collection in that language with
`@inContext(language:)` and is served only when the answer's `localization` says it holds that language (a shop
without the language answers in its default one). The subfolder's country is not used: prices are read only
from a shop with one presentment currency (D-1114, D-1386). A shop with several is not served: the answer's amounts
are its primary market's, while its page may show another market's amounts, so the page path publishes the price the
page shows, with the currency the page states or, failing that, unknown (normalization spec, money). A stored answer
of such a shop is still read without its prices: its amounts are not the page's, whatever their currency.

Product pages are not served (D-1118): the page states fields the API's answer lacks (its default variant's sku,
condition, rating, review count), so a product page takes the page path, which reads them with the variants the page
states.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from typing import Final
from urllib.parse import urlsplit

from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.outcome import as_error
from crawlerai.acquire.robots import at_origin
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.answer import recorded
from crawlerai.adapters.base import ALL, NOT_PLATFORM, NOT_SERVED, AdapterMatch, Members, PageRefs, Shape
from crawlerai.adapters.paging import fetch_pages
from crawlerai.core import json_text
from crawlerai.core.retry import is_transient

API_VERSION: Final = "2026-10"
# The Storefront API's endpoint path of any version: versions are named `YYYY-MM` (API versioning documentation).
_ENDPOINT_PATH: Final = re.compile(r"/api/\d{4}-\d{2}/graphql\.json", re.ASCII)
# Versioning documentation: "API responses include the X-Shopify-API-Version header".
SIGNAL: Final = "x-shopify-api-version"
# A handle is a collection's URL name: lowercase letters, digits, hyphens and underscores in practice
# (Liquid `handle` filter); a handle with other characters is percent-encoded in the URL and left to the generic path.
_HANDLE: Final = re.compile(r"[\w-]+", re.ASCII)
# A locale subfolder: a BCP 47 language subtag (RFC 5646 §2.2.1, ISO 639-1 or 639-2), optionally a region subtag
# (§2.2.4, ISO 3166-1 alpha-2), as the platform writes them in a path segment.
_LOCALE: Final = re.compile(r"([a-z]{2,3})(?:-[a-z]{2})?", re.ASCII | re.IGNORECASE)
# The Online Store's product route (shopify.dev Liquid `product.url`: `/products/{handle}`, also under a collection,
# `/collections/{handle}/products/{handle}`, and a locale subfolder), as a page links its products.
_PRODUCT_PATH: Final = re.compile(
    r"(?:/[a-z]{2,3}(?:-[a-z]{2})?)?(?:/collections/[\w-]+)?/products/([\w-]+)/?", re.ASCII | re.IGNORECASE
)
# The most products one Storefront API connection page holds (`first`, the API's pagination documentation).
PAGE_SIZE: Final = 250
# The query asks for the currencies the shop presents prices in (`PaymentSettings.enabledPresentmentCurrencies`, "A
# list of enabled currencies (ISO 4217 format) that the shop accepts"): a tokenless answer prices in the shop's primary
# market, while a page shows the market of its visitor (`_one_currency`). `{context}` is empty, or the `@inContext`
# directive of a locale-prefixed page with its `localization` check.
_COLLECTION_QUERY: Final = """query Collection($handle: String!, $after: String{variables}){context} {{
  shop {{ paymentSettings {{ enabledPresentmentCurrencies }} }}{localization}
  collection(handle: $handle) {{
    products(first: {page_size}, after: $after) {{
      pageInfo {{ hasNextPage endCursor }}
      nodes {{
        id handle title onlineStoreUrl
        featuredImage {{ url }}
        priceRange {{ minVariantPrice {{ amount currencyCode }} maxVariantPrice {{ amount currencyCode }} }}
      }}
    }}
  }}
}}"""


def _bound(at: Members) -> Shape:
    """An Offer whose price is the `MoneyV2` at `at`."""
    return Shape(type="Offer", at=at, properties={"price": ("amount",), "priceCurrency": ("currencyCode",)})


# A collection lists its products (schema.org ItemList). A listed product's two Offers are its price range's bounds:
# equal bounds are the one price of every variant; different ones disagree, and the answer states no one price of the
# product, so its price is a `conflict` `offers_disagree` (resolution spec, "Candidate score": no low bound is derived).
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
        # A query (a page, an order or a filter of the collection) is the page's own: the page's links say which
        # products it shows (`fetch_listed`).
        handle = _collection(parts.path)
        if handle is None:
            return None
        return AdapterMatch(tenant=parts.hostname, page_kind="listing", item=handle)

    def serves(self, match: AdapterMatch, endpoint: str) -> bool:
        # adapters spec: the API path on the page's own host (the tenant), where `fetch` asks it.
        parts = urlsplit(endpoint)
        return parts.hostname == match.tenant and _ENDPOINT_PATH.fullmatch(parts.path) is not None

    async def fetch(self, url: str, policy: FetchPolicy, send: JsonFetcher) -> FetchResult:
        raise TypeError("a collection is served with the page it shows (fetch_listed)")

    async def fetch_listed(self, url: str, page: PageRefs, policy: FetchPolicy, send: JsonFetcher) -> FetchResult:
        match = self.detect(url)
        if match is None or match.item is None:
            raise ValueError("not a storefront URL this adapter detects")
        listed = _listed(page, match.tenant)
        language = _language(urlsplit(url).path)
        handle = match.item

        def request(after: str | None) -> JsonRequest:
            # The handle, cursor and language go in as GraphQL variables, never into the query's text.
            variables: dict[str, str] = {"handle": handle}
            if after is not None:
                variables["after"] = after
            if language is not None:
                variables["language"] = language
            return JsonRequest(
                url=at_origin(url, f"/api/{API_VERSION}/graphql.json"),
                page_url=url,
                method="POST",
                headers=(("Content-Type", "application/json"),),
                body=json.dumps({"query": _query(language is not None), "variables": variables}),
            )

        def next_page(answers: Sequence[JsonValue]) -> JsonRequest | None:
            read = {_handle(node) for answer in answers for node in _nodes(answer)}
            cursor = _next_cursor(answers[-1])
            return None if cursor is None or read.issuperset(listed) else request(cursor)

        # The page bounds the rows, not the request's row target (`max_rows` counts the collection's products read,
        # not the page's): the walk goes on until every product the page links to is read, up to the hard cap.
        whole = policy.model_copy(update={"max_rows": None})
        result = await fetch_pages(request(None), whole, send, next_page=next_page, merge=_merge, rows=_rows)
        return _verdict(_shown(result, listed), language)

    def shapes(self, _match: AdapterMatch, answer: JsonValue, /) -> tuple[Shape, ...]:
        return (_LISTING if _one_currency(answer) else _UNPRICED_LISTING,)


def _collection(path: str) -> str | None:
    """The handle of a collection page's path, also under a locale subfolder; None for another path."""
    segments = path.removesuffix("/").split("/")
    if _language(path) is not None:
        del segments[1]
    match segments:
        case ["", "collections", handle] if _HANDLE.fullmatch(handle):
            return handle
    return None


def _language(path: str) -> str | None:
    """The Storefront API `LanguageCode` of a collection path's locale subfolder (its language subtag, upper-cased);
    None without one."""
    segments = path.removesuffix("/").split("/")
    locale = _LOCALE.fullmatch(segments[1]) if len(segments) == 4 and segments[2] == "collections" else None
    return None if locale is None else locale.group(1).upper()


def _query(localized: bool) -> str:
    if not localized:
        return _COLLECTION_QUERY.format(variables="", context="", localization="", page_size=PAGE_SIZE)
    return _COLLECTION_QUERY.format(
        variables=", $language: LanguageCode!",
        context=" @inContext(language: $language)",
        localization="\n  localization { language { isoCode } }",
        page_size=PAGE_SIZE,
    )


def _products(answer: JsonValue) -> JsonValue:
    return _member(_member(_member(answer, "data"), "collection"), "products")


def _nodes(answer: JsonValue) -> list[JsonValue]:
    nodes = _member(_products(answer), "nodes")
    return nodes if isinstance(nodes, list) else []


def _listed(page: PageRefs, host: str) -> dict[str, int]:
    """The handles of the products the page links to on its own `host`, each with its first position on the page."""
    listed: dict[str, int] = {}
    for link in page.links:
        parts = urlsplit(link)
        if parts.hostname == host and (route := _PRODUCT_PATH.fullmatch(parts.path)) is not None:
            listed.setdefault(route.group(1).lower(), len(listed))
    return listed


def _shown(result: FetchResult, listed: dict[str, int]) -> FetchResult:
    """`result` with only the products of `listed`, in the page's order; an answer that is not `ok` as it is."""
    if result.block_class != "ok":
        return result
    answer = json_text.parse(result.bundle.body)  # `fetch_json` checked that an `ok` body is JSON
    shown = sorted((n for n in _nodes(answer) if _handle(n) in listed), key=lambda node: listed[_handle(node)])
    products = _products(answer)
    return recorded(
        result, _with_products(answer, {**(products if isinstance(products, dict) else {}), "nodes": shown})
    )


def _handle(node: JsonValue) -> str:
    handle = _member(node, "handle")
    return handle.lower() if isinstance(handle, str) else ""


def _rows(answer: JsonValue) -> int:
    return len(_nodes(answer))


def _next_cursor(answer: JsonValue) -> str | None:
    """The cursor after the answer's last product, while its connection says another page follows."""
    info = _member(_products(answer), "pageInfo")
    cursor = _member(info, "endCursor")
    return cursor if _member(info, "hasNextPage") is True and isinstance(cursor, str) else None


def _merge(answers: Sequence[JsonValue]) -> JsonValue:
    """The first answer with every page's products in order, and the last page's `pageInfo`."""
    products = {
        "pageInfo": _member(_products(answers[-1]), "pageInfo"),
        "nodes": [n for a in answers for n in _nodes(a)],
    }
    return _with_products(answers[0], products)


def _with_products(answer: JsonValue, products: JsonValue) -> JsonValue:
    """`answer` with its collection's `products` replaced by `products`."""
    if not isinstance(answer, dict):
        return answer
    data = _member(answer, "data")
    collection = _member(data, "collection")
    merged_collection = {**(collection if isinstance(collection, dict) else {}), "products": products}
    return {**answer, "data": {**(data if isinstance(data, dict) else {}), "collection": merged_collection}}


def _one_currency(answer: JsonValue) -> bool:
    """Whether the shop presents its prices in one currency only, so that the answer's prices are in the currency any
    page of the shop shows. A tokenless answer prices in the shop's primary market (`@inContext` names no other), while
    the page shows its visitor's market; with several currencies they may differ, and nothing in the answer says which
    one a page showed (C7: decline rather than guess)."""
    shop = _member(_member(answer, "data"), "shop")
    currencies = _member(_member(shop, "paymentSettings"), "enabledPresentmentCurrencies")
    return isinstance(currencies, list) and len(currencies) == 1


def _priced(answer: JsonValue) -> bool:
    """Whether every listed product has a price above zero (`priceRange.minVariantPrice.amount`, a `Decimal` string):
    a shop that hides its prices from the API (amounts of zero) may still show them on its page, and the answer must
    not take the page path's prices away (adapters spec: an adapter answer never serves a page with less)."""
    for node in _nodes(answer):
        amount = _member(_member(_member(node, "priceRange"), "minVariantPrice"), "amount")
        try:
            if not isinstance(amount, str) or Decimal(amount) <= 0:
                return False
        except InvalidOperation:
            return False
    return True


def _member(value: JsonValue, name: str) -> JsonValue:
    return value.get(name) if isinstance(value, dict) else None


def _verdict(result: FetchResult, language: str | None) -> FetchResult:
    """`result`, or why it does not serve the page. No response, a slow-down or a server error is kept as it is: it
    says nothing of the platform, and the page falls back. An answer without the platform's signal is `NOT_PLATFORM`;
    the platform's answer holding errors, no collection or none of the page's products, for a page in `language` not
    in that language, of a shop whose page may show another currency than the answer's (`_one_currency`), or with a
    product it states no price for (`_priced`), is `NOT_SERVED`."""
    manifest = result.bundle.manifest
    if manifest.status_code == 0 or is_transient(manifest.status_code):
        return result
    if not any(name.lower() == SIGNAL for name, _ in manifest.headers.response):
        return as_error(result, NOT_PLATFORM)
    if result.block_class != "ok":
        return result
    # `fetch_json` checked that an `ok` body is JSON (RFC 8259); GraphQL answers with an object.
    answer = json_text.parse(result.bundle.body)
    served = (
        isinstance(answer, dict)
        and not answer.get("errors")
        and isinstance(_member(answer.get("data"), "collection"), dict)
        and _rows(answer) > 0
        and (language is None or _answered_in(answer) == language)
        and _one_currency(answer)
        and _priced(answer)
    )
    return result if served else as_error(result, NOT_SERVED)


def _answered_in(answer: JsonValue) -> JsonValue:
    """The language the answer is in (`Localization.language.isoCode`)."""
    return _member(_member(_member(_member(answer, "data"), "localization"), "language"), "isoCode")
