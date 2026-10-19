"""Data calls over HTTP (acquisition spec, "Data calls"): the product JSON a detail page's own HTTP fetch is joined
with, from the platform's documented endpoint (`adapters.platforms.product_json`) or from the data call a render of the
site's pages made, which the acquisition contract keeps (`DataCall`, method `api_replay`).

A kept call is the render's request with the product's key, a token of the page URL that the call's URL and its answer
both state, replaced by `{key}`; the key's place in a page URL (`KeyAt`) gives the next page's key. A call whose URL
names no token of the page URL would answer the same product for every page, so it is not kept.

Before an answer joins a page it must state the requested product (the identity check, owned-by as in resolution): a
string or number equal to the page's key, or a URL whose path is the page's path. An answer that does not is dropped
and recorded on its attempt as `NOT_THE_PRODUCT`. A joined answer is one more network body of the page's HTTP capture,
which the extraction reads as it reads a render's (`collect.xhr`): it adds evidence, and never replaces the page's.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final, Literal
from urllib.parse import parse_qsl, unquote, urljoin, urlsplit

from pydantic import JsonValue

from crawlerai.acquire.outcome import as_error
from crawlerai.acquire.public_suffix import default_suffixes
from crawlerai.acquire.types import FetchResult
from crawlerai.storage.capture_bundle import CaptureBundle, NetworkBody, network_file, network_json

__all__ = ["NOT_THE_PRODUCT", "DataCall", "KeyAt", "identifies", "joined", "learned_call"]

# The reason of a data call's attempt whose answer does not state the requested product.
NOT_THE_PRODUCT: Final = "not_the_product"
_PLACEHOLDER: Final = "{key}"
# A key shorter than this names no product: a locale, a two-letter path prefix.
_MIN_KEY: Final = 4
# RFC 3986 §2.3: the unreserved characters a path segment's token is made of.
_RUN: Final = re.compile(r"[A-Za-z0-9]+")
_SUCCESS: Final = range(200, 300)
# The most scalars of an answer the identity check reads: a product's JSON holds its key near the top.
_MAX_SCALARS: Final = 20_000

KeyKind = Literal["segment", "run", "query"]


@dataclass(frozen=True)
class KeyAt:
    """Where a page URL states its product's key: a path segment or an alphanumeric run of the path, counted from the
    end (-1 the last), or a query parameter's value by name."""

    kind: KeyKind
    at: str  # the index from the end, or the parameter's name

    def of(self, url: str) -> str | None:
        parts = urlsplit(url)
        if self.kind == "query":
            return next((value for name, value in parse_qsl(parts.query) if name == self.at), None)
        tokens = _segments(parts.path) if self.kind == "segment" else _RUN.findall(parts.path)
        index = int(self.at)
        return tokens[index] if -len(tokens) <= index < 0 else None


@dataclass(frozen=True)
class DataCall:
    """A data call the contract keeps: its URL with the key as `{key}`, and where a page URL states the key."""

    url: str
    key: KeyAt

    def stored(self) -> dict[str, str]:
        return {"url": self.url, "key": f"{self.key.kind}:{self.key.at}"}

    @classmethod
    def load(cls, stored: dict[str, str] | None) -> "DataCall | None":
        if stored is None:
            return None
        kind, _, at = stored["key"].partition(":")
        match kind:
            case "segment" | "run" | "query":
                return cls(stored["url"], KeyAt(kind, at))
        return None

    def for_page(self, url: str) -> tuple[str, str] | None:
        """The call's URL for the page at `url`, with the page's key; None when the page URL states no key there."""
        key = self.key.of(url)
        if key is None or len(key) < _MIN_KEY:
            return None
        return self.url.replace(_PLACEHOLDER, key), key


def learned_call(rendered: FetchResult) -> DataCall | None:
    """The data call of a render to keep (module docstring): the first successful GET of the page's site whose URL and
    JSON answer state a key of the page URL, the page URL's last tokens first."""
    page = rendered.bundle.manifest.url
    suffixes = default_suffixes()
    site = suffixes.site(urlsplit(page).hostname or "")
    for entry, body in zip(rendered.bundle.manifest.network_bodies, rendered.bundle.network, strict=True):
        host = urlsplit(entry.url).hostname or ""
        if entry.status not in _SUCCESS or (entry.method or "GET") != "GET" or suffixes.site(host) != site:
            continue
        try:
            answer = network_json(body)
        except ValueError:
            continue
        for at, key in _keys(page):
            if (template := _template(entry.url, key)) is not None and identifies(answer, page, key):
                return DataCall(template, at)
    return None


def _segments(path: str) -> list[str]:
    return [segment for segment in path.split("/") if segment]


def _keys(url: str) -> Iterator[tuple[KeyAt, str]]:
    """The page URL's candidate keys, the last path segment first, then the path's runs from the end, then the query's
    values."""
    parts = urlsplit(url)
    segments = _segments(parts.path)
    runs = _RUN.findall(parts.path)
    candidates = [
        *((KeyAt("segment", str(i)), segments[i]) for i in range(-1, -len(segments) - 1, -1)),
        *((KeyAt("run", str(i)), runs[i]) for i in range(-1, -len(runs) - 1, -1)),
        *((KeyAt("query", name), value) for name, value in parse_qsl(parts.query)),
    ]
    yield from ((at, key) for at, key in candidates if len(key) >= _MIN_KEY)


def _template(url: str, key: str) -> str | None:
    """`url` with each occurrence of `key` as a whole token of its path or query (no letter or digit beside it, other
    than a percent-encoded octet's) made `{key}`; None when it holds none."""
    parts = urlsplit(url)
    origin_end = len(f"{parts.scheme}://{parts.netloc}")
    # A percent-encoded octet beside the key (RFC 3986 §2.1: a quote or brace of a JSON query value) delimits it too.
    token = re.compile(
        rf"(?:(?<![A-Za-z0-9])|(?<=%[0-9A-Fa-f]{{2}})){re.escape(key)}(?=%[0-9A-Fa-f]{{2}}|[^A-Za-z0-9]|$)"
    )
    rest = url[origin_end:]
    if token.search(rest) is None:
        return None
    return url[:origin_end] + token.sub(lambda _: _PLACEHOLDER, rest)


def identifies(answer: JsonValue, page_url: str, key: str) -> bool:
    """Whether the JSON `answer` states the product of the page at `page_url` whose key is `key` (module docstring)."""
    wanted = unquote(key).casefold()
    path = urlsplit(page_url).path.rstrip("/")
    for value in _scalars(answer):
        text = str(value)
        if text.casefold() == wanted or (len(path) > 1 and _path_of(page_url, text) == path):
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


def joined(page: FetchResult, call: FetchResult, key: str) -> tuple[FetchResult | None, FetchResult]:
    """The HTTP `page` with the `ok` data call `call`'s answer as one more network body, when the answer states the
    product (`identifies`), and the call's result; else None, and the call as an error, `NOT_THE_PRODUCT`. The page
    keeps its attempts; the caller adds the call's."""
    if call.block_class != "ok":
        return None, call
    try:
        answer = network_json(call.bundle.body)
    except ValueError:
        return None, as_error(call, NOT_THE_PRODUCT)
    if not identifies(answer, page.bundle.manifest.final_url, key):
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
    )
    bundle = CaptureBundle(
        manifest=manifest.model_copy(update={"network_bodies": (*manifest.network_bodies, entry)}),
        body=page.bundle.body,
        network=(*page.bundle.network, call.bundle.body),
        raw_body=page.bundle.raw_body,
    )
    return page.model_copy(update={"bundle": bundle}), call
