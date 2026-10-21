"""A listing's rows in the locate run (learning-configs spec, "Locate run"; listings spec, "Rows from page state"): the
rows the renders published are located in the HTTP page's state as a `jsonpath` row step, else through the listing
recipe of the renders' calls, else in the render's item blocks as a `browser` listing.

Pages are synthetic captures on `.test` hosts: listing pages whose HTTP capture may carry an embedded state document
listing the items, and whose render adds the item cards the script writes.
"""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.config_ir.active import fetch_plan
from crawlerai.config_ir.api_recipe.validate import RecipeValidated, refused
from crawlerai.config_ir.executor import EngineExecutor
from crawlerai.config_ir.held_out import StoredPage, read_bundle
from crawlerai.config_ir.induction import SamplePage
from crawlerai.config_ir.locate import Located, Sampled, locate, located_config
from crawlerai.config_ir.model import ExtractionConfigIR, Fetch, JsonPathStep, Provenance, SchemaRef
from crawlerai.config_ir.release_executor import ReleasePage, release_run
from crawlerai.config_ir.release_rules import release_rules
from crawlerai.config_ir.validation import Facts, HeldOutPage, Validated, ValidationReport
from crawlerai.core.capture import CaptureMethod
from crawlerai.core.ids import uuid7
from crawlerai.db.models import CaptureId, ExtractionConfigId
from crawlerai.resolve.task import ActiveConfig
from crawlerai.schemas.types import SchemaDef, document_digest
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
SITE = "https://shop.example.test"
ITEMS = 4
SCHEMA = SchemaDef.model_validate(
    {
        "id": uuid7(),
        "origin": "user",
        "status": "active",
        "name": "synthetic_listing",
        "page_kind": "listing",
        "fields": {
            "title": {"type": "text", "required": True, "description": "d", "schema_org": "Product.name"},
            "url": {"type": "url", "required": True, "description": "d", "schema_org": "Product.url"},
        },
    }
)


def _html(page: int, *, state: bool, cards: bool) -> str:
    items = [{"name": f"Item {page}-{n}", "href": f"/p/{page}-{n}"} for n in range(ITEMS)]
    data = {"props": {"listing": {"items": items if state else []}}}
    script = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'
    grid = "".join(
        f"<li class='card'><a href='/p/{page}-{n}'><h3>Item {page}-{n}</h3></a>"
        f"<img src='/i/{page}-{n}.jpg' alt='Item {page}-{n}'><span class='badge'>Tag {n}</span></li>"
        for n in range(ITEMS)
    )
    body = f"<ul class='grid'>{grid}</ul>" if cards else "<div id='app'></div>"
    return f"<html><head>{script}</head><body><nav><a href='/'>Home</a></nav>{body}</body></html>"


def _bundle(page: int, html: str, method: CaptureMethod) -> CaptureBundle:
    body = html.encode()
    url = f"{SITE}/list/{page}"
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=url,
        final_url=url,
        fetched_at=datetime(2026, 10, 20, tzinfo=UTC),
        method=method,
        status_code=200,
        block_class="ok",
        headers=Headers(request=(), response=(("content-type", "text/html"),)),
        timings_ms={},
        html_sha256=sha256_hex(body),
        network_bodies=(),
        fetch_policy={},
        engine_version="test",
    )
    return CaptureBundle(manifest=manifest, body=body, network=())


def _sampled(page: int, *, state: bool) -> Sampled:
    """Listing page `page`: its HTTP capture (the state when `state`, no cards) and its render (the cards too)."""
    http = _bundle(page, _html(page, state=state, cards=False), "http")
    parsed, ctx = read_bundle(http)
    stored = StoredPage(HeldOutPage(CaptureId(uuid7()), parsed, ctx, Facts()), SamplePage(parsed, ctx, {}), http)
    render = _bundle(page, _html(page, state=state, cards=True), "browser")
    rendered, rendered_ctx = read_bundle(render)
    rows = [{"title": f"Item {page}-{n}", "url": f"{SITE}/p/{page}-{n}"} for n in range(ITEMS)]
    return Sampled(stored, render, rendered, rendered_ctx, {}, rows)


def _base() -> ExtractionConfigIR:
    return ExtractionConfigIR(
        ir_version="1",
        site="shop.example.test",
        schema_=SchemaRef(name=SCHEMA.name, digest=document_digest(SCHEMA)),
        page_kind="listing",
        fetch=Fetch(method="http"),
        fields={},
        provenance=Provenance(
            origin="induced", validated_on=[], learned_at=datetime(2026, 10, 20, tzinfo=UTC), engine_version="test"
        ),
    )


def _locate(pages: list[Sampled], recipe: RecipeValidated | None = None) -> tuple[Located, list[str]]:
    asked: list[str] = []

    async def learned() -> RecipeValidated:
        asked.append("recipe")
        return recipe or refused("no_endpoint: synthetic")

    located = asyncio.run(locate(_base(), SCHEMA, ["title", "url"], pages, VOCABULARY, None, learned))
    return located, asked


def _merged(located: Located) -> ExtractionConfigIR:
    report = ValidationReport(held_out=[], fields={}, listing=None, refused="too_few_held_out")
    merged = located_config(Validated(None, report), _base(), located)
    assert merged.ir is not None
    return merged.ir


def test_rows_in_the_http_state_become_a_jsonpath_listing_read_by_both_executors() -> None:
    located, asked = _locate([_sampled(page, state=True) for page in range(3)])

    ir = _merged(located)
    assert ir.listing is not None
    assert ir.listing.row == JsonPathStep(jsonpath="$['props']['listing']['items'][*]", source="js_state")
    assert {steps.needs for steps in ir.listing.fields.values()} == {"http"}
    assert asked == []  # the cheaper tier validated: no recipe is learned
    assert not fetch_plan(ActiveConfig(ExtractionConfigId(uuid7()), 1, EngineExecutor(ir, VOCABULARY)), "off").browser
    html, url = _html(7, state=True, cards=False), f"{SITE}/list/7"
    _, ctx = read_bundle(_bundle(7, html, "http"))
    released = release_run(ir, ReleasePage(html=html, base_url=url), release_rules(SCHEMA, ctx))
    assert released.rows[1] == {"title": "Item 7-1", "url": "/p/7-1"}  # as the state writes it


def test_without_the_state_the_listing_recipe_is_asked_then_the_render_cards_make_it_browser_bound() -> None:
    located, asked = _locate([_sampled(page, state=False) for page in range(3)])

    ir = _merged(located)
    assert asked == ["recipe"]
    assert ir.listing is not None
    assert {steps.needs for steps in ir.listing.fields.values()} == {"browser"}
    assert fetch_plan(ActiveConfig(ExtractionConfigId(uuid7()), 1, EngineExecutor(ir, VOCABULARY)), "off").browser


def test_a_listing_no_render_gives_rows_is_not_found_in_render() -> None:
    pages = [_sampled(page, state=True) for page in range(3)]
    rowless = [Sampled(p.stored, p.render, p.page, p.ctx, {}, []) for p in pages]

    located, _ = _locate(rowless)

    assert located.reasons == {"title": "not_found_in_render", "url": "not_found_in_render"}
