"""Listing recipe learning (Appendix A #59): from the series of calls that loaded a listing's rows, learn the endpoint,
its row map, its pagination and its request, and accept it only when replaying its first two pages for each held-out
page gives the rows that page's calls gave. Pages without the calls to learn from are rendered in the browser.

Pages are synthetic browser captures on `.test` hosts (C9): listing `/c/<category>` loads its rows from
`/v1/search?cat=<category>&page=<n>`, three rows a page; a stand-in API answers the replays through `fetch_json`.
"""

import asyncio
import json
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.config_ir.api_recipe.learn import learn_recipe
from crawlerai.config_ir.api_recipe.model import ParamPagination
from crawlerai.config_ir.api_recipe.validate import RecipeValidated
from crawlerai.config_ir.held_out import StoredPage
from crawlerai.config_ir.induction import SamplePage
from crawlerai.config_ir.validation import Facts, HeldOutPage, RecipeFieldReport
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import CaptureId, JobId, PageKind
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, NetworkBody, sha256_hex
from tests.support.fake_llm import ScriptedClient

ScriptedApi = Callable[[Callable[[JsonRequest], bytes], list[JsonRequest]], JsonFetcher]
JOB = JobId(uuid7())
SITE = "https://shop.example.test"
API = "https://api.example.test/v1/search"
CATEGORIES = ["lamps", "chairs", "desks", "rugs", "beds", "sofas", "shelves", "mirrors"]
ROWS = "$['data']['items'][*]"
PAGES = 3  # each category's listing has three pages of three rows
SCHEMA = SchemaDef.model_validate(
    {
        "id": uuid7(),
        "origin": "user",
        "status": "active",
        "name": "synthetic_listing",
        "page_kind": "listing",
        "fields": {
            "title": FieldSpec(type=FieldType.TEXT, description="d", required=True),
            "price": FieldSpec(type=FieldType.MONEY, description="d"),
        },
    }
)


def _title(category: str, page: int, row: int) -> str:
    return f"{category.title()} model {chr(64 + page)}{chr(65 + row)}"


def _answer(category: str, page: int) -> bytes:
    rows = (
        []
        if page > PAGES
        else [{"name": _title(category, page, r), "cost": f"{page}{r}.00", "cur": "EUR"} for r in range(3)]
    )
    return json.dumps({"data": {"items": rows, "total": PAGES * 3}}).encode()


def _api(request: JsonRequest) -> bytes:
    query = parse_qs(urlsplit(request.url).query)
    return _answer(query["cat"][0], int(query["page"][0]))


def _bundle(page_url: str, pages: Sequence[int]) -> CaptureBundle:
    category = page_url.rsplit("/", 1)[1].rsplit("-", 1)[-1]  # `/c/<category>` or `/c/<n>-<category>`
    shown = [_title(category, page, row) for page in pages for row in range(3)]
    body = ("<html><body><ul>" + "".join(f"<li>{text}</li>" for text in shown) + "</ul></body></html>").encode()
    calls = [(f"{API}?cat={category}&page={page}", _answer(category, page)) for page in pages]
    entries = tuple(
        NetworkBody(
            url=url,
            status=200,
            content_type="application/json",
            sha256=sha256_hex(data),
            file=f"network/{i + 1:04d}.json",
            method="GET",
            request_headers=(("Accept", "application/json"),),
            action=i,
        )
        for i, (url, data) in enumerate(calls)
    )
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=page_url,
        final_url=page_url,
        fetched_at=datetime(2026, 10, 17, tzinfo=UTC),
        method="browser",
        status_code=200,
        block_class="ok",
        headers=Headers(request=(), response=()),
        timings_ms={},
        html_sha256=sha256_hex(body),
        network_bodies=entries,
        fetch_policy={},
        engine_version="test",
    )
    return CaptureBundle(manifest=manifest, body=body, network=tuple(data for _, data in calls))


def _capture(n: int) -> CaptureId:
    return CaptureId(uuid.UUID(int=n + 1))


def _page(n: int, pages: Sequence[int] = (1, 2), *, numbered: bool = False) -> StoredPage:
    """Category `n`'s stored listing (`/c/<n>-<category>` when `numbered`): the browser loaded `pages` of it; the
    engine published the first page's rows."""
    category = CATEGORIES[n]
    page_url = f"{SITE}/c/{n}-{category}" if numbered else f"{SITE}/c/{category}"
    bundle = _bundle(page_url, pages)
    parsed = ParsedPage.of(bundle)
    ctx = Context(captured_at=datetime(2026, 10, 17, tzinfo=UTC), base_url=page_url, page_url=page_url)
    rows: list[dict[str, JsonValue]] = [
        {"title": _title(category, 1, r), "price": {"amount": f"1{r}.00", "currency": "EUR"}} for r in range(3)
    ]
    held_out = HeldOutPage(_capture(n), parsed, ctx, Facts(), tuple(Facts(published=row) for row in rows))
    return StoredPage(held_out, SamplePage(parsed, ctx, {}), bundle)


def _learn(
    scripted_api: ScriptedApi,
    pages: Sequence[StoredPage],
    render: Callable[[str, PageKind], Sequence[CaptureBundle]] | None = None,
    client: ScriptedClient | None = None,
) -> tuple[RecipeValidated, list[JsonRequest], list[str]]:
    sent: list[JsonRequest] = []
    fetcher = scripted_api(_api, sent)
    rendered: list[str] = []

    async def replay(request: JsonRequest) -> FetchResult:
        return await fetcher(request, FetchPolicy(timeout_s=5))

    async def render_page(url: str, kind: PageKind) -> Sequence[CaptureBundle]:
        rendered.append(url)
        assert render is not None
        return render(url, kind)

    learned = learn_recipe(
        client or ScriptedClient(),
        pages[:5],
        pages[5:],
        SCHEMA,
        replay,
        job_id=JOB,
        render=None if render is None else render_page,
    )
    return asyncio.run(learned), sent, rendered


def test_a_listing_s_paged_calls_become_a_listing_recipe_validated_on_two_pages(scripted_api: ScriptedApi) -> None:
    learned, sent, _ = _learn(scripted_api, [_page(n) for n in range(8)])

    recipe = learned.recipe
    assert recipe is not None, learned.report
    assert (recipe.method, recipe.url, recipe.params_from_url) == ("GET", f"{API}?cat={{p1}}&page=1", {"p1": "path:1"})
    assert recipe.pagination == ParamPagination(kind="param", where="query", name="page", start=1, step=1, rows=ROWS)
    assert recipe.map == {"title": "$['name']", "price": "$['cost']+$['cur']"}
    assert recipe.proof.validated_on == [_capture(5), _capture(6), _capture(7)]
    assert learned.report.fields == {name: RecipeFieldReport(published=3, reproduced=3) for name in ("title", "price")}
    # Each page is replayed for its first two pages: the five samples to prove the headers, then the held-out three.
    replayed = [(parse_qs(urlsplit(r.url).query)["cat"][0], parse_qs(urlsplit(r.url).query)["page"][0]) for r in sent]
    assert replayed == [(CATEGORIES[n], page) for n in range(8) for page in ("1", "2")]


def test_role_d_binds_an_ambiguous_listing_request_and_the_pagination_joins_its_spec(
    scripted_api: ScriptedApi,
) -> None:
    spec: dict[str, JsonValue] = {
        "method": "GET",
        "url": f"{API}?cat={{c}}&page=1",
        "params": [{"name": "c", "binder": "regex:^/c/[0-9]+-([a-z]+)$"}],
        "body": None,
    }
    client = ScriptedClient(spec)

    learned, _, _ = _learn(scripted_api, [_page(n, numbered=True) for n in range(8)], client=client)

    assert learned.recipe is not None, learned.report
    assert learned.recipe.proof.bound_by == "role_d"
    assert learned.recipe.pagination == ParamPagination(
        kind="param", where="query", name="page", start=1, step=1, rows=ROWS
    )
    (request,) = client.requests
    assert (
        "Listing pagination (set by the engine on every page; keep its value as captured): param, query value page."
        in (request.user)
    )
    assert "A listing's sample request is the request for its first page." in request.system
