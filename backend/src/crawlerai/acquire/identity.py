"""Identity-checked data calls (acquisition spec, "Data calls"): a JSON answer fetched for one product, kept only when
it states that product.

A data call is a request for a product's JSON that the fetch makes beside the product's page: the product JSON a
platform documents for a detail page (`adapters.platforms.product_json`), or an API recipe's request (adapters spec,
`config_ir.api_recipe.execute`). Before its answer is used it must state the requested product (the identity check):
a string or number equal to a key the request was made with (a handle, a slug, a product id), or a URL whose path is the
page's path. An answer that does not is dropped and recorded on its attempt as `NOT_THE_PRODUCT`: an endpoint that
ignores its key answers one product for every page.

A documented platform answer that passes joins the page's HTTP capture as one more network body, marked with its
platform (the network body's `data_call`), which the extraction reads as that platform documents it
(`collect.platform_json`).
"""

from collections.abc import Iterable, Iterator
from typing import Final
from urllib.parse import unquote, urljoin, urlsplit

from pydantic import JsonValue

from crawlerai.acquire.outcome import as_error
from crawlerai.acquire.types import FetchResult
from crawlerai.core.ids import uuid7
from crawlerai.storage.capture_bundle import CaptureBundle, NetworkBody, network_file, network_json

__all__ = ["MIN_KEY", "NOT_THE_PRODUCT", "identifies", "joined"]

# The reason of a data call's attempt whose answer does not state the requested product.
NOT_THE_PRODUCT: Final = "not_the_product"
# A key shorter than this names no product (a locale, a two-letter path prefix): it is no evidence of identity.
MIN_KEY: Final = 4
# The most scalars of an answer the identity check reads: a product's JSON holds its key near the top.
_MAX_SCALARS: Final = 20_000


def identifies(answer: JsonValue, page_url: str, keys: Iterable[str]) -> bool:
    """Whether the JSON `answer` states the product of the page at `page_url` requested by `keys` (module docstring);
    a key shorter than `MIN_KEY` is not compared."""
    wanted = {unquote(key).casefold() for key in keys if len(key) >= MIN_KEY}
    path = urlsplit(page_url).path.rstrip("/")
    for value in _scalars(answer):
        text = str(value)
        if text.casefold() in wanted or (len(path) > 1 and _path_of(page_url, text) == path):
            return True
    return False


def _path_of(page_url: str, text: str) -> str | None:
    """The path of `text` as a URL reference resolved against the page (RFC 3986 §5), when it is an absolute URL or an
    absolute path."""
    if not text.startswith(("http://", "https://", "/")):
        return None
    try:
        return urlsplit(urljoin(page_url, text)).path.rstrip("/")
    except ValueError:
        return None


def _scalars(answer: JsonValue) -> Iterator[str | int | float]:
    """The strings and numbers of `answer` (a boolean or null is no key), walked with a stack, up to `_MAX_SCALARS`."""
    stack, seen = [answer], 0
    while stack and seen < _MAX_SCALARS:
        value = stack.pop()
        if isinstance(value, dict):
            stack.extend(reversed(list(value.values())))
        elif isinstance(value, list):
            stack.extend(reversed(value))
        elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
            seen += 1
            yield value


def joined(page: FetchResult, call: FetchResult, key: str, platform: str) -> tuple[FetchResult | None, FetchResult]:
    """The HTTP `page` with the `ok` documented answer `call` of `platform` as one more network body, marked with the
    platform, as a capture of its own (a new id), when the answer states the product (`identifies`), and the call's
    result; else None, and the call as an error, `NOT_THE_PRODUCT`. The page keeps its
    attempts; the caller adds the call's."""
    if call.block_class != "ok":
        return None, call
    try:
        answer = network_json(call.bundle.body)
    except ValueError:
        return None, as_error(call, NOT_THE_PRODUCT)
    if not identifies(answer, page.bundle.manifest.final_url, (key,)):
        return None, as_error(call, NOT_THE_PRODUCT)
    sent = call.bundle.manifest
    content_type = next((value for name, value in sent.headers.response if name.lower() == "content-type"), None)
    manifest = page.bundle.manifest
    entry = NetworkBody(
        url=sent.final_url,
        status=sent.status_code,
        content_type=content_type,
        sha256=sent.html_sha256,
        file=network_file(len(page.bundle.network)),
        method="GET",
        request_headers=sent.headers.request,
        response_headers=sent.headers.response,
        resource_type="fetch",
        action=0,
        data_call=platform,
    )
    bundle = CaptureBundle(
        # Another capture than the HTTP page's: a new id, so no parse of the page alone stands for it (INV-26).
        manifest=manifest.model_copy(
            update={"capture_id": uuid7(), "network_bodies": (*manifest.network_bodies, entry)}
        ),
        body=page.bundle.body,
        network=(*page.bundle.network, call.bundle.body),
        raw_body=page.bundle.raw_body,
    )
    return page.model_copy(update={"bundle": bundle}), call
