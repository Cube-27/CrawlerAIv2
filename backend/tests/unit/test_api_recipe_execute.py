"""Recipe execution: a site with an active recipe is served over `fetch_json` with no browser,
the HTML page fetched first only when a binder reads its JSON documents; what the recipe cannot serve falls back to the
configured rungs; a listing's pages come by incrementing the pagination parameter until the rows run out. A custom
recipe's warm-up and calls are one fetch: a cookie the warm-up's answer sets goes with the calls after it.

A stand-in API (`tests.stand_in`, synthetic `.test` hosts) answers through `fetch_json` and the SSRF guard.
"""

import asyncio
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from ipaddress import ip_address

import httpx

from crawlerai.acquire.api import JsonFetcher, fetch_json
from crawlerai.acquire.memory import Remembered
from crawlerai.acquire.rungs import Rungs, acquire
from crawlerai.acquire.ssrf import IPAddress, SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.collect.base import PAGE
from crawlerai.config_ir.api_recipe.execute import Custom, RecipeRung, recipe_collector
from crawlerai.config_ir.api_recipe.model import (
    ApiRecipe,
    CursorPagination,
    HeaderValue,
    Pagination,
    Proof,
)
from crawlerai.config_ir.model import WarmUp
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import CaptureId, PageKind, SchemaId
from crawlerai.normalize.base import Context, Ok
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from tests.stand_in import IMPERSONATE, handler_transport
from tests.support.captures import ScriptedRung

SITE = "https://shop.example.test"
ENDPOINT = "https://api.example.test/v1"
POLICY = FetchPolicy()
PROOF = Proof(validated_on=[CaptureId(uuid.UUID(int=1))], headers_tried=1, bound_by="deterministic")
PRODUCTS = {"desk-lamp": ("Desk Lamp", 19.5), "oak-chair": ("Oak Chair", 120)}
DETAIL_RECIPE = ApiRecipe(
    method="GET",
    url=f"{ENDPOINT}/products/{{p1}}",
    params_from_url={"p1": "path:1"},
    headers=[HeaderValue(name="Referer", value="{page_url}")],
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
    # The answer states the product it was asked for (its slug), as the identity check requires.
    return httpx.Response(200, json={"data": {"slug": slug, "name": name, "price": price, "currency": "EUR"}})


def _rung(recipe: ApiRecipe, api: StandIn, page: ScriptedRung | None = None) -> RecipeRung:
    return RecipeRung(recipe, api.fetch_json(), page or ScriptedRung(), engine_version="test")


def _ctx(url: str) -> Context:
    return Context(captured_at=datetime(2026, 10, 14, tzinfo=UTC), base_url=url, page_url=url)


def test_a_page_is_served_over_the_api_with_no_browser_and_its_values_are_api_candidates() -> None:
    api, http, browser = StandIn(_products), ScriptedRung(), ScriptedRung()
    url = f"{SITE}/p/desk-lamp"

    result = asyncio.run(
        acquire(url, POLICY, Remembered("browser"), Rungs(http=http, browser=browser), recipe=_rung(DETAIL_RECIPE, api))
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


def test_a_cookie_the_warm_up_sets_goes_with_the_main_call_of_the_same_fetch_only() -> None:
    def site(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/session":
            return httpx.Response(200, text="<!doctype html><p>hi</p>", headers={"Set-Cookie": "sid=s1; Path=/"})
        return _products(request)

    api = StandIn(site)
    recipe = ApiRecipe(
        method="GET", url=f"{SITE}/api/{{p1}}", params_from_url={"p1": "pattern:slug"}, map={"t": "$['data']['name']"}
    )
    custom = Custom("cfg1", ("shop.example.test/p/{slug}",), warm_up=WarmUp(url=f"{SITE}/session"))
    rung = RecipeRung(recipe, api.fetch_json(), ScriptedRung(), "test", custom)
    url = f"{SITE}/p/desk-lamp"

    async def twice() -> FetchResult:
        await rung(url, POLICY)
        return await rung(url, POLICY)

    result = asyncio.run(twice())

    # Each fetch starts with a jar of its own: the second warm-up carries no cookie of the first fetch.
    assert [(r.url.path, r.headers.get("Cookie")) for r in api.requests] == [
        ("/session", None),
        ("/api/desk-lamp", "sid=s1"),
        ("/session", None),
        ("/api/desk-lamp", "sid=s1"),
    ]
    assert result.block_class == "ok"
    assert [(a.method, a.recipe) for a in result.attempts] == [("api", "cfg1"), ("api", "cfg1")]


# --- pagination -----------------------------------------------------------------------------

ITEMS = [f"Lamp {n}" for n in range(5)]


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


def _run(recipe: ApiRecipe, api: StandIn, records: int = 100, deadline: float | None = None) -> list[FetchResult]:
    async def run() -> list[FetchResult]:
        rung = _rung(recipe, api)
        return [page async for page in rung.pages(f"{SITE}/lamps", POLICY, records=records, deadline=deadline)]

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
