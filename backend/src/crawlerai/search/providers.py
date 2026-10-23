"""The search providers the operator configures: a SearXNG instance's JSON API (`search_searxng_url`), or any
endpoint named by a URL template (`search_url_template`) whose `{query}` and `{limit}` are filled in. The operator's
own endpoint is trusted, so, unlike a page, it may be on a private network; it is asked over plain HTTP(S) with no
cookies and redirects are not followed.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final, Protocol
from urllib.parse import quote, urlencode, urlsplit

import httpx

from crawlerai.core.errors import Refusal
from crawlerai.search.results import Fields, Hit, parse, unique

MAX_BYTES: Final = 2_000_000  # an answer past this is not read
# SearXNG's JSON API gives a page of results at a time (`pageno`, 1-based); a `limit` past one page reads further
# pages, up to this many.
SEARXNG_MAX_PAGES: Final = 5
# SearXNG's documented JSON result members (Search API, `format=json`): a result's `url`, `title` and `content` (its
# snippet). A result also carries `engine`, `template`, `category` and other strings, so it is read by these names,
# not by its shape.
SEARXNG_FIELDS: Final[Fields] = {"url": "url", "title": "title", "snippet": "content"}

QUERY: Final = "{query}"  # the placeholder of a URL template, replaced by the percent-encoded query
LIMIT: Final = "{limit}"

Get = Callable[[str], Awaitable[tuple[bytes, str | None]]]


class SearchFailed(Refusal):
    """The provider did not answer usefully: unreachable, an error status, or an answer too large."""


class SearchProvider(Protocol):
    async def search(self, query: str, limit: int) -> list[Hit]: ...


def http_get(timeout_s: float) -> Get:
    """A `Get` that reads at most `MAX_BYTES` of the URL's body, returning it with its declared charset."""

    async def get(url: str) -> tuple[bytes, str | None]:
        try:
            async with (
                httpx.AsyncClient(timeout=timeout_s, follow_redirects=False) as client,
                client.stream("GET", url, headers={"Accept": "application/json, text/html;q=0.8"}) as response,
            ):
                if response.status_code != httpx.codes.OK:
                    raise SearchFailed(f"the search provider answered {response.status_code}")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        raise SearchFailed("the search provider's answer is too large")
                return bytes(body), response.charset_encoding
        except httpx.HTTPError as e:
            raise SearchFailed(f"the search provider did not answer: {type(e).__name__}") from e

    return get


@dataclass(frozen=True)
class SearxngProvider:
    """A SearXNG instance at `base_url`: `GET {base_url}/search?q=...&format=json&pageno=n`."""

    base_url: str
    get: Get

    async def search(self, query: str, limit: int) -> list[Hit]:
        hits: list[Hit] = []
        for page in range(1, SEARXNG_MAX_PAGES + 1):
            params = urlencode({"q": query, "format": "json", "pageno": page})
            body, charset = await self.get(f"{self.base_url.rstrip('/')}/search?{params}")
            found = unique(hits + parse(body, charset, self.base_url, SEARXNG_FIELDS))
            if len(found) == len(hits):
                break
            hits = found
            if len(hits) >= limit:
                break
        return hits[:limit]


@dataclass(frozen=True)
class TemplateProvider:
    """Any endpoint: `template` with `{query}` (percent-encoded) and `{limit}` replaced, read generically
    (`crawlerai.search.results`)."""

    template: str
    get: Get
    fields: Fields | None = None

    async def search(self, query: str, limit: int) -> list[Hit]:
        url = self.template.replace(QUERY, quote(query, safe="")).replace(LIMIT, str(limit))
        body, charset = await self.get(url)
        return parse(body, charset, url, self.fields)[:limit]


def configured(
    searxng_url: str | None, url_template: str | None, timeout_s: float, fields: Fields | None = None
) -> SearchProvider | None:
    """The provider the settings name, or `None` when they name none. Raises `ValueError` for a malformed setting."""
    get = http_get(timeout_s)
    if searxng_url is not None:
        _absolute(searxng_url)
        return SearxngProvider(searxng_url, get)
    if url_template is not None:
        if QUERY not in url_template:
            raise ValueError("the search URL template has no {query}")
        _absolute(url_template.replace(QUERY, "q").replace(LIMIT, "1"))
        return TemplateProvider(url_template, get, fields)
    return None


def _absolute(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("a search provider URL is an absolute http or https URL")
