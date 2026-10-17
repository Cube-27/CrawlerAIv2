"""Recipe execution (SPEC-09 §4.8, §4.10): a site with an active recipe is served over `fetch_json` with no browser,
the HTML page fetched first only when a binder reads its JSON documents; what the recipe cannot serve falls back to the
configured rungs; a listing's pages come by incrementing the pagination parameter until the rows run out.

A stand-in API (`tests.stand_in`, synthetic `.test` hosts) answers through `fetch_json` and the SSRF guard.
"""

import asyncio
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import partial
from ipaddress import ip_address

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.acquire.api import JsonFetcher, fetch_json
from crawlerai.acquire.outcome import Content, Exchange, fetch_result
from crawlerai.acquire.politeness import Admit
from crawlerai.acquire.rungs import Rungs, acquire
from crawlerai.acquire.ssrf import IPAddress, SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.collect.base import PAGE
from crawlerai.config_ir.api_recipe.binding import resolve, with_query_value
from crawlerai.config_ir.api_recipe.execute import RecipeExecutor, RecipeRung, recipe_collector
from crawlerai.config_ir.api_recipe.model import (
    ApiRecipe,
    Binder,
    CursorPagination,
    LinkPagination,
    NextUrlPagination,
    Pagination,
    ParamPagination,
    Proof,
)
from crawlerai.content.page import ParsedPage
from crawlerai.core.capture import BlockClass
from crawlerai.core.ids import uuid7
from crawlerai.db.models import CaptureId, FieldStatus, PageKind, SchemaId
from crawlerai.normalize.base import Context, Ok
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from tests.stand_in import IMPERSONATE, handler_transport

SITE = "https://shop.example.test"
ENDPOINT = "https://api.example.test/v1"
POLICY = FetchPolicy()
PROOF = Proof(validated_on=[CaptureId(uuid.UUID(int=1))], headers_tried=1, bound_by="deterministic")
PRODUCTS = {"desk-lamp": ("Desk Lamp", 19.5), "oak-chair": ("Oak Chair", 120)}
DETAIL_RECIPE = ApiRecipe(
    method="GET",
    url=f"{ENDPOINT}/products/{{p1}}",
    params_from_url={"p1": "path:1"},
    headers={"Referer": "{page_url}"},
    map={"title": "$['data']['name']", "price": "$['data']['price']+$['data']['currency']"},
    proof=PROOF,
)


def _schema(page_kind: PageKind, **fields: FieldSpec) -> SchemaDef:
    return SchemaDef(id=SchemaId(uuid7()), origin="user", status="active", name="s", page_kind=page_kind, fields=fields)


DETAIL = _schema(
    "detail",
    title=FieldSpec(type=FieldType.TEXT, description="d", required=True),
    price=FieldSpec(type=FieldType.MONEY, description="d"),
)


@dataclass
class StandIn:
    """An API answering `route(request)` for every request it records; every host resolves to a public address."""

    route: Callable[[httpx.Request], httpx.Response]
    requests: list[httpx.Request] = field(default_factory=list)

    def fetch_json(self) -> JsonFetcher:
        async def resolve_host(_host: str) -> list[IPAddress]:
            return [ip_address("93.184.215.14")]

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return self.route(request)

        return partial(
            fetch_json,
            engine_version="test",
            impersonate=IMPERSONATE,
            connector=SafeConnector(resolve_host),
            transport=handler_transport(handler),
        )


def _sent(request: httpx.Request) -> str:
    """The URL a request was for: the guard connects to the checked address and keeps the name in `Host`."""
    return f"{request.url.scheme}://{request.headers['Host']}{request.url.raw_path.decode()}"


def _products(request: httpx.Request) -> httpx.Response:
    slug = request.url.path.rsplit("/", 1)[-1]
    if slug not in PRODUCTS:
        return httpx.Response(404, json={})
    name, price = PRODUCTS[slug]
    return httpx.Response(200, json={"data": {"name": name, "price": price, "currency": "EUR"}})


@dataclass
class PageRung:
    """The HTTP rung as a stub: answers every URL with `body` and `block_class`, and records the URLs."""

    body: bytes = b"<html></html>"
    block_class: BlockClass = "ok"
    status: int | None = None
    calls: list[str] = field(default_factory=list)

    async def __call__(self, url: str, policy: FetchPolicy) -> FetchResult:
        self.calls.append(url)
        status = self.status or (200 if self.block_class == "ok" else 403)
        return fetch_result(
            url=url,
            method="http",
            policy=policy,
            engine_version="test",
            fetched_at=datetime.now(UTC),
            started=0.0,
            exchange=Exchange(url=url, status=status, request_headers=(), response_headers=()),
            content=Content(body=self.body),
            block_class=self.block_class,
            error=None,
        )


def _rung(recipe: ApiRecipe, api: StandIn, page: PageRung | None = None) -> RecipeRung:
    return RecipeRung(recipe, api.fetch_json(), page or PageRung(), engine_version="test")


def _ctx(url: str) -> Context:
    return Context(captured_at=datetime(2026, 10, 14, tzinfo=UTC), base_url=url, page_url=url)


def test_a_page_is_served_over_the_api_with_no_browser_and_its_values_are_api_candidates() -> None:
    api, http, browser = StandIn(_products), PageRung(), PageRung()
    url = f"{SITE}/p/desk-lamp"

    result = asyncio.run(
        acquire(url, POLICY, "browser", Rungs(http=http, browser=browser), recipe=_rung(DETAIL_RECIPE, api))
    )

    assert (result.method, result.block_class) == ("api", "ok")
    assert [attempt.method for attempt in result.attempts] == ["api"]
    assert (http.calls, browser.calls) == ([], [])
    assert (result.bundle.manifest.url, result.bundle.manifest.final_url) == (url, f"{ENDPOINT}/products/desk-lamp")
    assert [_sent(r) for r in api.requests] == [f"{ENDPOINT}/products/desk-lamp"]
    assert api.requests[0].headers["Referer"] == url
    executed = recipe_collector(DETAIL_RECIPE, "cfg1").collect(ParsedPage.of(result.bundle), DETAIL, _ctx(url))
    assert [
        (c.field, c.source_kind, c.entity_id, c.normalized.value if isinstance(c.normalized, Ok) else None)
        for c in executed.candidates
    ] == [
        ("title", "api", PAGE, "Desk Lamp"),
        ("price", "api", PAGE, {"amount": "19.5", "currency": "EUR"}),
    ]


def test_a_recipe_failure_falls_back_to_the_configured_rung() -> None:
    api, http = StandIn(_products), PageRung(b"<html><h1>Gone Lamp</h1></html>")
    url = f"{SITE}/p/gone-lamp"

    result = asyncio.run(
        acquire(url, POLICY, "http", Rungs(http=http, browser=PageRung()), recipe=_rung(DETAIL_RECIPE, api))
    )

    assert (result.method, result.block_class) == ("http", "ok")
    assert [(a.method, a.block_class) for a in result.attempts] == [("api", "not_found"), ("http", "ok")]


def test_a_page_whose_parameter_cannot_be_bound_sends_no_request() -> None:
    api = StandIn(_products)
    recipe = DETAIL_RECIPE.model_copy(update={"params_from_url": {"p1": "query:id"}})

    result = asyncio.run(_rung(recipe, api)(f"{SITE}/p/desk-lamp", POLICY))

    assert (result.method, result.block_class) == ("api", "error")
    assert result.attempts[0].error == "unbound_parameter"
    assert api.requests == []


SKU_RECIPE = ApiRecipe(
    method="GET",
    url=f"{ENDPOINT}/sku/{{p1}}",
    params_from_url={"p1": "jsonld:$[0]['sku']"},
    requires_page_fetch=True,
    map={"title": "$['name']"},
    proof=PROOF,
)
SKU_PAGE = (
    b"""<html><head><script type="application/ld+json">{"@type": "Product", "sku": 9001}</script></head></html>"""
)


def test_a_binder_that_reads_the_page_fetches_the_html_page_first() -> None:
    api = StandIn(lambda request: httpx.Response(200, json={"name": "Desk Lamp"}))
    page = PageRung(SKU_PAGE)
    url = f"{SITE}/p/desk-lamp"

    result = asyncio.run(_rung(SKU_RECIPE, api, page)(url, POLICY))

    assert page.calls == [url]
    assert [_sent(r) for r in api.requests] == [f"{ENDPOINT}/sku/9001"]
    assert [(a.method, a.block_class) for a in result.attempts] == [("http", "ok"), ("api", "ok")]
    recorded = result.bundle.manifest.fetch_policy["attempts"]
    assert isinstance(recorded, list)
    assert len(recorded) == 2
    assert json.loads(result.bundle.body) == {"name": "Desk Lamp"}


def test_a_page_that_is_not_served_leaves_the_recipe_unserved() -> None:
    api = StandIn(_products)

    result = asyncio.run(_rung(SKU_RECIPE, api, PageRung(block_class="blocked"))(f"{SITE}/p/x", POLICY))

    assert [(a.method, a.block_class, a.error) for a in result.attempts] == [
        ("http", "blocked", None),
        ("api", "error", "page_blocked"),
    ]
    assert api.requests == []


def test_a_page_fetch_asked_to_slow_down_is_kept_with_no_fallback_request() -> None:
    api, http, page = StandIn(_products), PageRung(), PageRung(block_class="blocked", status=429)
    url = f"{SITE}/p/desk-lamp"

    result = asyncio.run(
        acquire(url, POLICY, "http", Rungs(http=http, browser=PageRung()), recipe=_rung(SKU_RECIPE, api, page))
    )

    assert (page.calls, http.calls, api.requests) == ([url], [], [])
    assert result.bundle.manifest.status_code == 429
    assert [(a.method, a.status) for a in result.attempts] == [("http", 429)]


def test_a_recipe_failure_after_the_page_fetch_keeps_that_page_with_no_second_fetch() -> None:
    # §4.10: the fallback is the page over HTTP, which the recipe has just fetched: fetching it again is one more.
    api, http, page = StandIn(lambda _: httpx.Response(500, json={})), PageRung(), PageRung(SKU_PAGE)
    url = f"{SITE}/p/desk-lamp"

    result = asyncio.run(
        acquire(url, POLICY, "http", Rungs(http=http, browser=PageRung()), recipe=_rung(SKU_RECIPE, api, page))
    )

    assert (page.calls, http.calls) == ([url], [])
    assert (result.method, result.block_class, result.bundle.body) == ("http", "ok", SKU_PAGE)
    assert [(a.method, a.block_class) for a in result.attempts] == [("http", "ok"), ("api", "error")]
    assert len(result.bundle.manifest.fetch_policy["attempts"]) == 2  # type: ignore[arg-type]


def test_a_page_fetched_for_an_unbound_recipe_is_kept() -> None:
    api, http, page = StandIn(_products), PageRung(), PageRung(b"<html><h1>No sku</h1></html>")
    url = f"{SITE}/p/desk-lamp"

    result = asyncio.run(
        acquire(url, POLICY, "http", Rungs(http=http, browser=PageRung()), recipe=_rung(SKU_RECIPE, api, page))
    )

    assert (page.calls, http.calls, api.requests) == ([url], [], [])
    assert (result.method, result.block_class) == ("http", "ok")
    assert [(a.method, a.error) for a in result.attempts] == [("http", None), ("api", "unbound_parameter")]


def test_a_page_asked_of_the_browser_falls_back_to_the_browser_after_a_recipe_failure() -> None:
    # A fetch whose policy names the browser is the configured method (§4.10); the HTTP page fetched to bind is not it.
    api, browser, page = StandIn(lambda _: httpx.Response(500, json={})), PageRung(), PageRung(SKU_PAGE)
    url = f"{SITE}/p/desk-lamp"
    policy = FetchPolicy(method_hint="browser")

    result = asyncio.run(
        acquire(url, policy, "http", Rungs(http=PageRung(), browser=browser), recipe=_rung(SKU_RECIPE, api, page))
    )

    assert (page.calls, browser.calls) == ([url], [url])
    assert [(a.method, a.block_class) for a in result.attempts] == [("http", "ok"), ("api", "error"), ("http", "ok")]


# --- pagination (§4.8, ARCHITECTURE §8.6) -----------------------------------------------------------------------------

ITEMS = [f"Lamp {n}" for n in range(5)]
LISTING_RECIPE = ApiRecipe(
    method="GET",
    url=f"{ENDPOINT}/lamps?sort=new&offset=99",
    pagination=ParamPagination(kind="param", where="query", name="offset", start=0, step=2, rows="$['items'][*]"),
    map={"title": "$['name']"},
    proof=PROOF,
)
LISTING = _schema("listing", title=FieldSpec(type=FieldType.TEXT, description="d", required=True))


def _offsets(request: httpx.Request) -> httpx.Response:
    offset = int(request.url.params["offset"])
    return httpx.Response(200, json={"items": [{"name": name} for name in ITEMS[offset : offset + 2]]})


def _pages(api: StandIn, limit: int) -> list[FetchResult]:
    async def run() -> list[FetchResult]:
        return [
            page async for page in _rung(LISTING_RECIPE, api).pages(f"{SITE}/lamps", POLICY, records=100, limit=limit)
        ]

    return asyncio.run(run())


def test_a_listing_is_paged_until_its_rows_run_out() -> None:
    api = StandIn(_offsets)

    pages = _pages(api, limit=10)

    assert [r.url.params.get_list("offset") for r in api.requests] == [["0"], ["2"], ["4"], ["6"]]
    assert all(r.url.params["sort"] == "new" for r in api.requests)
    titles = [
        c.raw
        for page in pages
        for c in recipe_collector(LISTING_RECIPE, "cfg1")
        .collect(ParsedPage.of(page.bundle), LISTING, _ctx(SITE))
        .candidates
    ]
    assert titles == ITEMS


def test_a_listing_stops_at_the_limit() -> None:
    api = StandIn(_offsets)

    pages = _pages(api, limit=2)

    assert len(pages) == 2
    assert [r.url.params["offset"] for r in api.requests] == ["0", "2"]


def test_a_failed_page_ends_the_listing_and_is_yielded_last() -> None:
    def failing(request: httpx.Request) -> httpx.Response:
        return _offsets(request) if request.url.params["offset"] == "0" else httpx.Response(500, json={})

    pages = _pages(StandIn(failing), limit=10)

    assert [page.block_class for page in pages] == ["ok", "error"]


def test_a_response_whose_rows_hold_no_object_ends_the_listing() -> None:
    # The collector reads rows that are JSON objects only (RFC 8259 §4): rows of another kind are no rows to page on.
    def scalars(request: httpx.Request) -> httpx.Response:
        if request.url.params["offset"] == "0":
            return _offsets(request)
        return httpx.Response(200, json={"items": [1, 2]})

    api = StandIn(scalars)

    pages = _pages(api, limit=10)

    assert len(pages) == 1
    assert [r.url.params["offset"] for r in api.requests] == ["0", "2"]


def test_a_recipe_without_pagination_has_no_pages() -> None:
    pages = _rung(DETAIL_RECIPE, StandIn(_products)).pages(SITE, POLICY, records=3)

    async def first() -> FetchResult:
        return await anext(pages)

    coroutine = first()
    with pytest.raises(ValueError, match="without pagination"):
        asyncio.run(coroutine)


def _listing(pagination: Pagination, *, method: str = "GET", body: str | None = None) -> ApiRecipe:
    return ApiRecipe.model_validate(
        {
            "method": method,
            "url": f"{ENDPOINT}/lamps?sort=new",
            "body": None if body is None else {"template": body},
            "pagination": pagination.model_dump(),
            "map": {"title": "$['name']"},
            "proof": PROOF.model_dump(mode="json"),
        }
    )


def _run(recipe: ApiRecipe, api: StandIn, records: int = 100, admit: Admit | None = None) -> list[FetchResult]:
    async def run() -> list[FetchResult]:
        rung = _rung(recipe, api)
        return [page async for page in rung.pages(f"{SITE}/lamps", POLICY, records=records, admit_next=admit)]

    return asyncio.run(run())


def _batch(start: int) -> list[dict[str, str]]:
    return [{"name": name} for name in ITEMS[start : start + 2]]


def test_a_graphql_cursor_in_the_post_body_is_taken_from_each_answer() -> None:
    def graphql(request: httpx.Request) -> httpx.Response:
        after = json.loads(request.content)["variables"]["after"]
        start = 0 if after is None else int(after.removeprefix("c"))
        end = None if start + 2 >= len(ITEMS) else f"c{start + 2}"
        return httpx.Response(200, json={"data": {"items": _batch(start), "page": {"end": end}}})

    paging = CursorPagination(
        kind="cursor",
        where="body",
        name="$['variables']['after']",
        cursor="$['data']['page']['end']",
        rows="$['data']['items'][*]",
    )
    body = '{"query":"lamps","variables":{"after":null,"first":2}}'
    api = StandIn(graphql)

    pages = _run(_listing(paging, method="POST", body=body), api)

    assert [json.loads(r.content)["variables"]["after"] for r in api.requests] == [None, "c2", "c4"]
    assert all(json.loads(r.content)["variables"]["first"] == 2 for r in api.requests)
    assert len(pages) == 3


def test_a_next_url_and_a_link_header_are_followed_on_the_endpoint_s_origin() -> None:
    def linked(request: httpx.Request) -> httpx.Response:
        start = int(request.url.params.get("from", "0"))
        follow = f"/v1/lamps?sort=new&from={start + 2}" if start + 2 < len(ITEMS) else None
        headers = {} if follow is None else {"Link": f'<{follow}>; rel="next"'}
        return httpx.Response(200, json={"items": _batch(start), "next": follow}, headers=headers)

    for paging in (
        NextUrlPagination(kind="next_url", next="$['next']", rows="$['items'][*]"),
        LinkPagination(kind="link", rows="$['items'][*]"),
    ):
        api = StandIn(linked)

        pages = _run(_listing(paging), api)

        assert [r.url.params.get("from") for r in api.requests] == [None, "2", "4"], paging.kind
        assert len(pages) == 3


def test_the_records_target_and_the_site_s_rate_end_the_listing() -> None:
    paging = ParamPagination(kind="param", where="query", name="offset", start=0, step=2, rows="$['items'][*]")
    api = StandIn(_offsets)

    assert len(_run(_listing(paging), api, records=3)) == 2
    assert [r.url.params["offset"] for r in api.requests] == ["0", "2"]

    turns: list[bool] = []

    async def refuse_second(*, after: timedelta = timedelta(0)) -> bool:
        turns.append(True)
        return len(turns) < 2

    refused = StandIn(_offsets)
    assert len(_run(_listing(paging), refused, admit=refuse_second)) == 2
    assert [r.url.params["offset"] for r in refused.requests] == ["0", "2"]


def test_a_cursor_that_comes_back_ends_the_listing() -> None:
    def looping(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": _batch(0), "end": "same"})

    paging = CursorPagination(kind="cursor", where="query", name="after", cursor="$['end']", rows="$['items'][*]")
    api = StandIn(looping)

    assert len(_run(_listing(paging), api)) == 2
    assert [r.url.params.get("after") for r in api.requests] == [None, "same"]


_QUERY_TEXT = st.text(st.characters(codec="utf-8", exclude_categories=["Cs"]), min_size=1, max_size=12)


@given(name=_QUERY_TEXT, value=_QUERY_TEXT, other=_QUERY_TEXT)
def test_a_query_value_set_on_a_url_is_the_value_a_query_binder_reads(name: str, value: str, other: str) -> None:
    base = with_query_value(f"{ENDPOINT}/lamps", name, other)

    url = with_query_value(base, name, value)

    assert resolve(Binder("query", name), url, {}) == value
    assert url.count("&") == 0  # the earlier item of the same name is replaced, not repeated


def test_setting_a_query_value_keeps_the_other_items_as_written() -> None:
    url = with_query_value(f"{ENDPOINT}/lamps?q=a%20b&offset=4&x", "offset", "6")

    assert url == f"{ENDPOINT}/lamps?q=a%20b&x&offset=6"


def test_a_recipes_executor_keeps_the_configs_absent_fields() -> None:
    # D-1341: an absent field is no recipe's, and role C is not asked for it on the recipe's pages either.
    status: dict[str, FieldStatus] = {"title": "corroborated", "brand": "uncorroborated", "sku": "absent"}

    executor = RecipeExecutor.of(DETAIL_RECIPE, "r1", status)

    assert {name: s for name, s in executor.field_status.items() if name not in DETAIL_RECIPE.map} == {"sku": "absent"}
