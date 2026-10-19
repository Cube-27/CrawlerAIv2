"""Commerce platform fingerprints (acquisition spec, "Platform fingerprints"): site data, which names platforms and so
lives in the adapter package (C3).

A platform is told from what every one of its sites serves: the paths of its own static assets and scripts, the
global its storefront script defines, the response headers its servers send. These are platform-level signals, never a
table of sites (C4). A page shows a platform's signal in its markup or its response headers; the first platform whose
signal it shows is its platform, the storefront platforms before the Next.js framework, which may front any of them.

Where a platform documents how a URL selects one variant of a product page (a query parameter on the product's own
URL), `variant_params` names the parameters, so that resolution knows a link to the page's own resource with one of
them for a variant of the page, not a link to a thing described elsewhere (variants spec, "Own variants").

Where a platform documents a public, tokenless product JSON endpoint on the shop's own host, `product_json` names the
request for a product page and `answer_shapes` the schema.org nodes its answer holds, as the platform documents its
members (adapters spec `Shape`, C2), amounts in the minor unit the documentation states; a platform whose product API
needs a credential (SFCC's OCAPI client id, BigCommerce's storefront token, Magento's REST token) or that has none
(Next.js) is recorded only.

A product whose variants are priced differently has no one price its answer states for the page, which shows the
selected variant's: its answer is read without its Offer, so it never stands against the price the page shows (INV-14;
the page keeps its prices, adapters spec "merge, don't override").
"""

import re
from dataclasses import dataclass, replace
from typing import Final
from urllib.parse import quote, urljoin, urlsplit

from pydantic import JsonValue

from crawlerai.adapters.base import ALL, Shape
from crawlerai.storage.capture_bundle import HeaderList

__all__ = [
    "SIGNATURES",
    "PlatformSignature",
    "ProductJson",
    "answer_shapes",
    "platform_of",
    "product_json",
    "signature_of",
]


@dataclass(frozen=True)
class PlatformSignature:
    platform: str
    markers: tuple[str, ...] = ()  # in the page's markup: the platform's asset paths and script globals
    header_names: frozenset[str] = frozenset()  # lowercase response header names only the platform's servers send
    # The query parameters (names, or name prefixes ending in `_`) by which the platform's documented product URLs
    # select one variant of the product.
    variant_params: tuple[str, ...] = ()


# The global the Online Store's theme layout defines (`content_for_header`); a headless storefront has none, nor the
# Online Store's Ajax API.
_ONLINE_STORE: Final = "Shopify.shop"

SIGNATURES: Final[tuple[PlatformSignature, ...]] = (
    # Shopify: the Online Store's `Shopify.shop` global (`content_for_header`) and the platform's asset CDN, which a
    # headless storefront (Hydrogen) also serves from; its edge sends `x-shopid` and `x-shopify-stage`.
    PlatformSignature(
        "shopify",
        markers=(_ONLINE_STORE, "cdn.shopify.com/", "shopify-features"),
        header_names=frozenset({"x-shopid", "x-shopify-stage"}),
        # shopify.dev Liquid `variant.url`: the product URL with `?variant=<id>` selects that variant.
        variant_params=("variant",),
    ),
    # Salesforce Commerce Cloud (Demandware): its controller path and static asset path (SFCC B2C developer docs,
    # "URL syntax": `/on/demandware.store/Sites-{site}-Site/`, `/on/demandware.static/`).
    # SFCC developer docs, "Product variation URLs": `dwvar_<product id>_<attribute>=<value>` selects a variation value.
    PlatformSignature("sfcc", markers=("/on/demandware.store/", "/on/demandware.static/"), variant_params=("dwvar_",)),
    # Magento / Adobe Commerce: its RequireJS module namespace and init script (Adobe Commerce frontend docs,
    # "JavaScript init"); its full-page cache sends `x-magento-tags`.
    PlatformSignature(
        "magento",
        markers=("Magento_Ui/js/core/app", '"Magento_', "mage/requirejs/"),
        header_names=frozenset({"x-magento-tags", "x-magento-cache-debug"}),
    ),
    # BigCommerce: the Stencil theme's asset CDN and bootstrap (BigCommerce dev docs, "Stencil":
    # `cdn11.bigcommerce.com`, `stencilBootstrap`).
    PlatformSignature("bigcommerce", markers=("cdn11.bigcommerce.com/s-", "stencilBootstrap(")),
    # WooCommerce: the plugin's asset path and the class its script swaps on the body (WooCommerce developer docs).
    # Its variation links carry `attribute_<attribute slug>=<term>` for each attribute (WooCommerce developer docs,
    # `WC_Product_Variation::get_permalink`).
    PlatformSignature(
        "woocommerce", markers=("/plugins/woocommerce/", "woocommerce-no-js"), variant_params=("attribute_",)
    ),
    # Next.js (commerce or any): the framework's data script and static path (Next.js docs, "Pages Router": the
    # `__NEXT_DATA__` script; the `/_next/static/` build output).
    PlatformSignature("nextjs", markers=('id="__NEXT_DATA__"', "/_next/static/")),
)

# The most markup scanned for a marker: a platform's script and asset references sit in the document's head and the
# start of its body; a longer scan reads a product description's text.
_SCAN_CHARS: Final = 500_000


def signature_of(markup: str, headers: HeaderList) -> PlatformSignature | None:
    """The signature of the platform whose signal the page shows (module docstring), or None."""
    names = {name.lower() for name, _ in headers}
    head = markup[:_SCAN_CHARS]
    for signature in SIGNATURES:
        if names & signature.header_names or any(marker in head for marker in signature.markers):
            return signature
    return None


def platform_of(markup: str, headers: HeaderList) -> str | None:
    """The platform whose signal the page shows (module docstring), or None."""
    signature = signature_of(markup, headers)
    return None if signature is None else signature.platform


@dataclass(frozen=True)
class ProductJson:
    """A platform's public JSON of the product a page shows: the platform, the endpoint, and the product's key the page
    URL names (a handle or slug), which the answer must state (`acquire.identity.identifies`)."""

    platform: str
    url: str
    key: str


# Shopify's product route (shopify.dev Ajax API, "Product": `GET /{locale}/products/{product-handle}.js`, which "returns
# the JSON of a product"; the route also appears under a collection, `/collections/{handle}/products/{handle}`).
_SHOPIFY_PRODUCT: Final = re.compile(
    r"(?P<prefix>(?:/[a-z]{2,3}(?:-[a-z]{2})?)?)(?:/collections/[\w-]+)?/products/(?P<handle>[\w-]+)/?",
    re.ASCII | re.IGNORECASE,
)
# WordPress REST API discovery (developer.wordpress.org/rest-api/using-the-rest-api/discovery): the API root is the
# `link rel="https://api.w.org/"` of every page.
_API_ROOT: Final = re.compile(r"""<link[^>]+rel=["']https://api\.w\.org/["'][^>]*>""", re.IGNORECASE)
_HREF: Final = re.compile(r"""href=["']([^"']+)["']""", re.IGNORECASE)
# A WordPress slug: lowercase letters, digits and hyphens (`sanitize_title`); a percent-encoded one is left alone.
_SLUG: Final = re.compile(r"[a-z0-9-]+", re.ASCII)


def product_json(platform: str | None, url: str, markup: str) -> ProductJson | None:
    """The documented public product JSON request for the product page at `url` of `platform`, or None: Shopify's Ajax
    API product (`/products/{handle}.js`) of an Online Store page (`_ONLINE_STORE`), or WooCommerce's Store API
    products by slug (developer.woocommerce.com, "Store API, Products": `GET /wp-json/wc/store/v1/products?slug=`), at
    the API root the page links to, on its own origin."""
    parts = urlsplit(url)
    route = _SHOPIFY_PRODUCT.fullmatch(parts.path)
    if platform == "shopify" and route is not None and _ONLINE_STORE in markup[:_SCAN_CHARS]:
        handle = route["handle"]
        return ProductJson("shopify", f"{parts.scheme}://{parts.netloc}{route['prefix']}/products/{handle}.js", handle)
    if platform == "woocommerce":
        return _store_api(parts.scheme, parts.netloc, parts.path, markup)
    return None


def _store_api(scheme: str, netloc: str, path: str, markup: str) -> ProductJson | None:
    slug = path.rstrip("/").rpartition("/")[2]
    link = _API_ROOT.search(markup[:_SCAN_CHARS])
    href = None if link is None else _HREF.search(link.group(0))
    if not _SLUG.fullmatch(slug) or href is None:
        return None
    root = urljoin(f"{scheme}://{netloc}/", href.group(1).replace("&amp;", "&"))
    # Same origin as the page: a root on another scheme (an `http` link on an `https` page) would send the call where
    # its answer can be altered in transit.
    if (urlsplit(root).scheme, urlsplit(root).netloc) != (scheme, netloc) or "?" in root:
        return None
    return ProductJson("woocommerce", f"{root.rstrip('/')}/wc/store/v1/products?slug={quote(slug)}", slug)


# Shopify Ajax API, "Product" (shopify.dev/docs/api/ajax/reference/product): the product's `title`, `url` (its route
# on the shop), `featured_image`, `vendor`, and its prices as integers in cents (the response's `price`, `price_min`,
# `price_max`; "prices are in cents"), with `price_varies` true when its variants are priced differently.
_SHOPIFY_PRODUCT_NODE: Final = Shape(
    type="Product",
    properties={"name": ("title",), "url": ("url",), "image": ("featured_image",), "brand": ("vendor",)},
)
_SHOPIFY_OFFER: Final = Shape(
    type="Offer", anchor=("price",), properties={"price": ("price",)}, minor_units={"price": 2}
)
# WooCommerce Store API, "Products" (github.com/woocommerce/woocommerce, plugins/woocommerce/src/StoreApi/docs,
# products.md): a list of products, each with `name`, `permalink`, `sku`, `images[].src`, and `prices`, whose `price`
# is a string of the amount in the currency's minor unit, `currency_minor_unit` its decimal places and `currency_code`
# its ISO 4217 code; `price_range` is set when the product's variations are priced differently.
_WOO_PRODUCT_NODE: Final = Shape(
    type="Product",
    at=(ALL,),
    properties={"name": ("name",), "url": ("permalink",), "sku": ("sku",), "image": ("images", ALL, "src")},
)
_WOO_OFFER: Final = Shape(
    type="Offer",
    at=("prices",),
    properties={"price": ("price",), "priceCurrency": ("currency_code",)},
    minor_units={"price": ("currency_minor_unit",)},
)


def answer_shapes(platform: str, answer: JsonValue) -> tuple[Shape, ...]:
    """The schema.org nodes the documented product JSON `answer` of `platform` holds (module docstring); none for a
    platform with no documented product JSON, or an answer not of its documented form."""
    if platform == "shopify" and isinstance(answer, dict):
        varies = answer.get("price_varies") is not False
        return (
            _SHOPIFY_PRODUCT_NODE if varies else replace(_SHOPIFY_PRODUCT_NODE, nodes={"offers": (_SHOPIFY_OFFER,)}),
        )
    if platform == "woocommerce" and isinstance(answer, list) and len(answer) == 1 and isinstance(answer[0], dict):
        prices = answer[0].get("prices")
        varies = not isinstance(prices, dict) or prices.get("price_range") is not None
        return (_WOO_PRODUCT_NODE if varies else replace(_WOO_PRODUCT_NODE, nodes={"offers": (_WOO_OFFER,)}),)
    return ()
