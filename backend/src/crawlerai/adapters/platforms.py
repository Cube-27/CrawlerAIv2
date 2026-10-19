"""Commerce platform fingerprints (acquisition spec, "Platform fingerprints"): site data, which names platforms and so
lives in the adapter package (C3).

A platform is told from what every one of its sites serves: the paths of its own static assets and scripts, the
global its storefront script defines, the response headers its servers send. These are platform-level signals, never a
table of sites (C4). A page shows a platform's signal in its markup or its response headers; the first platform whose
signal it shows is its platform, the storefront platforms before the Next.js framework, which may front any of them.

Where a platform documents a public, tokenless product JSON endpoint on the shop's own host, `product_json` names the
request for a product page; a platform whose product API needs a credential (SFCC's OCAPI client id, BigCommerce's
storefront token, Magento's REST token) or that has none (Next.js) is recorded only.
"""

import re
from dataclasses import dataclass
from typing import Final
from urllib.parse import quote, urljoin, urlsplit

from crawlerai.storage.capture_bundle import HeaderList

__all__ = ["SIGNATURES", "PlatformSignature", "ProductJson", "platform_of", "product_json"]


@dataclass(frozen=True)
class PlatformSignature:
    platform: str
    markers: tuple[str, ...] = ()  # in the page's markup: the platform's asset paths and script globals
    header_names: frozenset[str] = frozenset()  # lowercase response header names only the platform's servers send


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
    ),
    # Salesforce Commerce Cloud (Demandware): its controller path and static asset path (SFCC B2C developer docs,
    # "URL syntax": `/on/demandware.store/Sites-{site}-Site/`, `/on/demandware.static/`).
    PlatformSignature("sfcc", markers=("/on/demandware.store/", "/on/demandware.static/")),
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
    PlatformSignature("woocommerce", markers=("/plugins/woocommerce/", "woocommerce-no-js")),
    # Next.js (commerce or any): the framework's data script and static path (Next.js docs, "Pages Router": the
    # `__NEXT_DATA__` script; the `/_next/static/` build output).
    PlatformSignature("nextjs", markers=('id="__NEXT_DATA__"', "/_next/static/")),
)

# The most markup scanned for a marker: a platform's script and asset references sit in the document's head and the
# start of its body; a longer scan reads a product description's text.
_SCAN_CHARS: Final = 500_000


def platform_of(markup: str, headers: HeaderList) -> str | None:
    """The platform whose signal the page shows (module docstring), or None."""
    names = {name.lower() for name, _ in headers}
    head = markup[:_SCAN_CHARS]
    for signature in SIGNATURES:
        if names & signature.header_names or any(marker in head for marker in signature.markers):
            return signature.platform
    return None


@dataclass(frozen=True)
class ProductJson:
    """A platform's public JSON of the product a page shows: the endpoint, and the product's key the page URL names
    (a handle or slug), which the answer must state (`acquire.replay.identifies`)."""

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
    the API root the page links to, on its own host."""
    parts = urlsplit(url)
    route = _SHOPIFY_PRODUCT.fullmatch(parts.path)
    if platform == "shopify" and route is not None and _ONLINE_STORE in markup[:_SCAN_CHARS]:
        handle = route["handle"]
        return ProductJson(f"{parts.scheme}://{parts.netloc}{route['prefix']}/products/{handle}.js", handle)
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
    if urlsplit(root).netloc != netloc or "?" in root:
        return None
    return ProductJson(f"{root.rstrip('/')}/wc/store/v1/products?slug={quote(slug)}", slug)
