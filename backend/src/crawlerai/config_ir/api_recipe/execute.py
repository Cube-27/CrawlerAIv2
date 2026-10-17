"""Recipe execution (SPEC-09 §4.8, ARCHITECTURE §7.1 "Adapter / API" rung, §8.6): serve a site's pages with its
active config's API recipe over `fetch_json`, with no browser.

`RecipeRung` is the recipe bound to its fetchers, the rung `acquire` takes (`acquire.rungs`): it binds the
parameters from the page URL (fetching the HTML page first only when a binder reads the page's JSON documents,
`requires_page_fetch`), sends the recipe's request through the SSRF guard (INV-16) and answers a
`FetchResult(method='api')` whose body is the JSON. A page the recipe cannot serve is an `error` result, and `acquire`
fetches it the configured way (§4.10); when the rung fetched the HTML page to bind and reached it, that page is the
result instead, so it is not fetched twice. A listing's pages come from `pages`, which follows the recipe's pagination
(`pagination.py`: a page number or offset, a cursor, a next URL or an RFC 8288 `next` link, in the query or the JSON
body) until a response's `rows` select nothing or the caller's records target is reached: this is how infinite scroll
is served (§8.6). `recipe_collector` reads what the rung fetched.
"""

import asyncio
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.outcome import Content, fetch_result
from crawlerai.acquire.politeness import Admit
from crawlerai.acquire.rungs import Rung, slow_down, with_attempts
from crawlerai.acquire.types import BlockClass, FetchPolicy, FetchResult
from crawlerai.collect import json_doc
from crawlerai.collect.api import ApiCollector
from crawlerai.collect.config import Executed
from crawlerai.collect.network_match import LearnedCalls
from crawlerai.config_ir.api_recipe.binding import PageData, page_data
from crawlerai.config_ir.api_recipe.model import ApiRecipe
from crawlerai.config_ir.api_recipe.pagination import first_request, next_request
from crawlerai.config_ir.api_recipe.replay import request_for
from crawlerai.content.page import ParsedPage
from crawlerai.db.models import FieldStatus
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import SchemaDef

# A listing served by its recipe sends at most this many page requests (SPEC-09 §4.8): the records target ends it
# sooner, and a pagination that never ends (a cursor that comes back) is cut here.
MAX_PAGES: Final = 50


def recipe_collector(recipe: ApiRecipe, recipe_id: str) -> ApiCollector:
    """The collector of the captures `recipe` fetches; `recipe_id` names it in candidate locators."""
    rows = None if recipe.pagination is None else recipe.pagination.rows
    return ApiCollector(recipe_id, recipe.map, rows)


@dataclass(frozen=True, slots=True)
class RecipeExecutor:
    """The `ConfigExecutor` of the captures a config's recipe fetched: the recipe's collector, with the status of the
    config's fields the recipe maps, which role C is then not asked for (SPEC-08 §4.8)."""

    recipe: ApiRecipe
    collector: ApiCollector
    field_status: Mapping[str, FieldStatus]

    @classmethod
    def of(cls, recipe: ApiRecipe, recipe_id: str, config_status: Mapping[str, FieldStatus]) -> "RecipeExecutor":
        # An absent field (D-1341) is no recipe's either, and role C is not asked for it on a recipe's pages.
        status = {name: s for name, s in config_status.items() if name in recipe.map or s == "absent"}
        return cls(recipe, recipe_collector(recipe, recipe_id), status)

    @property
    def learned_calls(self) -> LearnedCalls | None:
        return None  # it reads the recipe's own `api` captures, which hold no calls

    def execute(self, page: ParsedPage, schema: SchemaDef, ctx: Context) -> Executed:
        return self.collector.collect(page, schema, ctx)


@dataclass(frozen=True, slots=True)
class RecipeRung:
    """`recipe` bound to `fetch_json` (the job's guard and engine version) and to `fetch_page`, the HTTP rung that
    fetches the HTML page when the recipe reads the page's JSON documents."""

    recipe: ApiRecipe
    fetch_json: JsonFetcher
    fetch_page: Rung
    engine_version: str

    async def __call__(self, url: str, policy: FetchPolicy) -> FetchResult:
        """The JSON the recipe's endpoint answers for the page at `url`."""
        bound = await self._request(url, policy)
        if isinstance(bound, FetchResult):
            return bound
        request, page = bound
        result = (
            self._unserved(url, policy, "unbound_parameter")
            if request is None
            else await self.fetch_json(request, policy)
        )
        # A fetch whose policy names the browser falls back to the browser, not to the HTML page fetched to bind.
        return _after(page, result, fallback=policy.method_hint != "browser")

    async def pages(
        self, url: str, policy: FetchPolicy, *, records: int, limit: int = MAX_PAGES, admit_next: Admit | None = None
    ) -> AsyncIterator[FetchResult]:
        """The listing at `url`, one response per page its pagination names (`pagination.next_request`), until a
        response's `rows` select no object, the pagination names no next page (or one already requested), `records`
        rows were yielded, `limit` requests were sent, or `admit_next` refuses the next request (the site's rate,
        SPEC-02 §4.6). A response with no rows is not yielded; one that is not `ok` is yielded last."""
        pagination = self.recipe.pagination
        if pagination is None:
            raise ValueError("a recipe without pagination serves one response per page")
        bound = await self._request(url, policy)
        if isinstance(bound, FetchResult):
            yield bound
            return
        bound_request, page = bound
        request = None if bound_request is None else first_request(pagination, bound_request)
        if request is None:
            yield _after(page, self._unserved(url, policy, "unbound_parameter"))
            return
        sent: set[tuple[str, str | None]] = set()
        rows = 0
        for number in range(limit):
            sent.add((request.url, request.body))
            result = _after(page, await self.fetch_json(request, policy))
            page = None  # the HTML page is fetched once, and counted with the first response
            if result.block_class != "ok":
                yield result
                return
            # Parsing is CPU work: a thread keeps the event loop serving other tasks meanwhile.
            document, count = await asyncio.to_thread(_rows, result, pagination.rows)
            if not count:
                return
            yield result
            rows += count
            headers = result.bundle.manifest.headers.response
            following = next_request(pagination, request, number + 1, document, headers)
            if rows >= records or following is None or (following.url, following.body) in sent:
                return
            if admit_next is not None and not await admit_next():
                return
            request = following

    async def _request(
        self, url: str, policy: FetchPolicy
    ) -> tuple[JsonRequest | None, FetchResult | None] | FetchResult:
        """The recipe's request for the page (None when a parameter cannot be bound), with the HTML page fetch it
        needed; when that fetch did not reach the page, an `error` result, or the page fetch itself when it asked for
        fewer requests."""
        data: PageData = {}
        page = None
        if self.recipe.requires_page_fetch:
            page = await self.fetch_page(url, policy)
            if slow_down(page):
                return page  # a 429 or 503 asks for fewer requests: `acquire` keeps it, with no fallback request
            if page.block_class != "ok":
                return _after(page, self._unserved(url, policy, f"page_{page.block_class}"))
            # Parsing is CPU work: a thread keeps the event loop serving other tasks meanwhile.
            data = await asyncio.to_thread(_page_data, page)
        return request_for(self.recipe, url, data), page

    def _unserved(self, url: str, policy: FetchPolicy, reason: str) -> FetchResult:
        return unserved(url, policy, self.engine_version, "error", reason)


def unserved(url: str, policy: FetchPolicy, engine_version: str, block_class: BlockClass, reason: str) -> FetchResult:
    """The recipe's result for the page at `url` when it sent no request: `reason` says why."""
    return fetch_result(
        url=url,
        method="api",
        policy=policy,
        engine_version=engine_version,
        fetched_at=datetime.now(UTC),
        started=time.monotonic(),
        exchange=None,
        content=Content(body=b""),
        block_class=block_class,
        error=reason,
    )


def _after(page: FetchResult | None, result: FetchResult, *, fallback: bool = False) -> FetchResult:
    """`result` with the HTML page fetch before it among its attempts. With `fallback`, a `result` that did not serve
    the page, and asked for no fewer requests, gives way to the HTML page when that fetch reached it: it is the page
    `acquire` would fetch again over HTTP (§4.10), one more request."""
    if page is None:
        return result
    unserved = result.block_class != "ok" and not slow_down(result)
    kept = page if fallback and unserved and page.block_class == "ok" else result
    return with_attempts(kept, page.attempts + result.attempts, page.duration_ms + result.duration_ms)


def _page_data(page: FetchResult) -> PageData:
    return page_data(ParsedPage.of(page.bundle))


def _rows(result: FetchResult, query: str) -> tuple[JsonValue, int]:
    """The response's JSON and how many rows `query` selects in it."""
    try:
        document = json_doc.parse(result.bundle.body.decode("utf-8"))
    except ValueError:  # not UTF-8 JSON (RFC 8259 §8.1): the collector reads no rows from it either
        return None, 0
    return document, row_count(query, document)


def row_count(query: str, document: JsonValue) -> int:
    """How many rows `query` selects in `document`: the collector reads only rows that are JSON objects (RFC 8259 §4,
    `collect.api`), so other items are no rows."""
    return sum(isinstance(row, dict) for _, row in json_doc.select(query, document))
