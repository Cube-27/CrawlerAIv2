"""The locate run: a value the renders publish
is induced in every source document that holds it, each step is validated on the other sample pages for its tier,
and the cheapest tier wins; the config's field sources then plan the fetch.

Pages are synthetic captures on `.test` hosts: a product page whose HTTP capture carries an embedded state document,
and whose render adds the element its script writes and the call it made; a stand-in API answers the call's replays.
"""

import asyncio
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from functools import partial
from ipaddress import ip_address
from pathlib import Path

import httpx
from pydantic import SecretStr

from crawlerai.acquire.api import JsonFetcher, JsonRequest, fetch_json
from crawlerai.acquire.rungs import FetchPlan
from crawlerai.acquire.ssrf import IPAddress, SafeConnector
from crawlerai.acquire.types import CallEndpoint, FetchPolicy, FetchResult, RequestContext
from crawlerai.collect.vocabulary import Vocabulary
from crawlerai.config_ir.active import fetch_plan
from crawlerai.config_ir.api_recipe.model import ContextHeader
from crawlerai.config_ir.executor import EngineExecutor
from crawlerai.config_ir.held_out import StoredPage, read_bundle
from crawlerai.config_ir.induction import SamplePage, source_steps
from crawlerai.config_ir.locate import Calls, Located, Sampled, locate, located_config
from crawlerai.config_ir.model import ExtractionConfigIR, Fetch, FieldSteps, JsonPathStep, Provenance, SchemaRef
from crawlerai.config_ir.validation import Facts, HeldOutPage, Validated, ValidationReport
from crawlerai.core.capture import CaptureMethod
from crawlerai.core.ids import uuid7
from crawlerai.db.models import CaptureId, ExtractionConfigId, JobId
from crawlerai.resolve.task import ActiveConfig
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef, document_digest
from crawlerai.storage.capture_bundle import CaptureBundle
from tests.stand_in import IMPERSONATE, handler_transport
from tests.support.captures import calls, capture
from tests.support.fake_llm import ScriptedClient

SCHEMA_ORG = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
SITE = "https://shop.example.test"
JOB = JobId(uuid7())
SLUGS = ("oak-table", "pine-chair", "elm-shelf")
MATERIALS = ("Oak wood", "Pine wood", "Elm wood")
SCHEMA = SchemaDef.model_validate(
    {
        "id": uuid7(),
        "origin": "user",
        "status": "active",
        "name": "synthetic",
        "page_kind": "detail",
        "fields": {
            "title": FieldSpec(type=FieldType.TEXT, description="d", required=True),
            "material": FieldSpec(type=FieldType.TEXT, description="d"),
        },
    }
)


def _endpoint(n: int) -> str:
    return f"{SITE}/api/items/{SLUGS[n]}"


def _answer(n: int, *, material: bool = True) -> bytes:
    """The item's call answer, which states its slug (the identity check) and, unless left out, its material."""
    item = {"slug": SLUGS[n], **({"material": MATERIALS[n]} if material else {})}
    return json.dumps({"item": item}).encode()


def _html(n: int, *, state: bool, element: bool) -> str:
    props = {"page": {"slug": SLUGS[n], **({"material": MATERIALS[n]} if state else {})}}
    script = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps({"props": props})}</script>'
    written = f'<div class="item-material">{MATERIALS[n]}</div>' if element else ""
    return f"<html><head>{script}</head><body><h1>Item {n}</h1>{written}</body></html>"


def _bundle(n: int, html: str, method: CaptureMethod, bodies: Sequence[tuple[str, bytes]] = ()) -> CaptureBundle:
    network = calls(bodies, method="GET", resource_type="fetch")
    return capture(
        html.encode(),
        url=f"{SITE}/p/{SLUGS[n]}",
        method=method,
        headers=(("content-type", "text/html"),),
        network=network,
    )


def _sampled(n: int, *, state: bool = True, call: bool = True) -> Sampled:
    """Item `n`: its HTTP capture (the state document, no element) and its render (the element and the call too)."""
    http = _bundle(n, _html(n, state=state, element=False), "http")
    page, ctx = read_bundle(http)
    capture = CaptureId(uuid7())
    stored = StoredPage(HeldOutPage(capture, page, ctx, Facts()), SamplePage(page, ctx, {}), http)
    render = _bundle(n, _html(n, state=state, element=True), "browser", [(_endpoint(n), _answer(n, material=call))])
    rendered, rendered_ctx = read_bundle(render)
    return Sampled(stored, render, rendered, rendered_ctx, {"title": f"Item {n}", "material": MATERIALS[n]})


def _base() -> ExtractionConfigIR:
    return ExtractionConfigIR(
        ir_version="1",
        site="shop.example.test",
        schema_=SchemaRef(name=SCHEMA.name, digest=document_digest(SCHEMA)),
        page_kind="detail",
        fetch=Fetch(method="http"),
        fields={},
        provenance=Provenance(
            origin="induced", validated_on=[], learned_at=datetime(2026, 10, 20, tzinfo=UTC), engine_version="test"
        ),
    )


def _api(sent: list[httpx.Request], *, needs: str | None = None) -> JsonFetcher:
    """`fetch_json` against a stand-in of the shop's API: each item's answer, and 401 without the `needs` header."""
    answers = {httpx.URL(_endpoint(n)).raw_path.decode(): _answer(n) for n in range(len(SLUGS))}

    async def resolve(_host: str) -> list[IPAddress]:
        return [ip_address("93.184.215.14")]

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if needs is not None and needs not in request.headers:
            return httpx.Response(401, json={})
        body = answers.get(request.url.raw_path.decode())
        return httpx.Response(404, json={}) if body is None else httpx.Response(200, content=body)

    return partial(
        fetch_json,
        engine_version="test",
        impersonate=IMPERSONATE,
        connector=SafeConnector(resolve),
        transport=handler_transport(handler),
    )


def _locate(
    pages: Sequence[Sampled], *, needs: str | None = None, context: RequestContext | None = None
) -> tuple[Located, list[httpx.Request]]:
    sent: list[httpx.Request] = []
    api = _api(sent, needs=needs)

    async def replay(request: JsonRequest) -> FetchResult:
        return await api(request, FetchPolicy(timeout_s=5))

    calls = Calls(ScriptedClient(), replay, JOB, context)
    return asyncio.run(locate(_base(), SCHEMA, ["material"], pages, SCHEMA_ORG, calls)), sent


# --- (i) every source, the cheapest wins -----------------------------------------------------------------------------


def test_the_value_is_induced_in_the_state_the_call_and_the_dom() -> None:
    page = _sampled(0)

    found = source_steps(page.page, page.ctx, SCHEMA, SCHEMA_ORG, "material", MATERIALS[0])

    assert {"js_state", "xhr", None} <= set(found)


def test_state_in_the_http_page_wins_and_every_source_validates() -> None:
    located, _ = _locate([_sampled(n) for n in range(3)])

    assert set(located.sources["material"]) == {"http", "call", "browser"}
    chosen = located.fields["material"]
    assert chosen.needs == "http"
    assert isinstance(chosen.steps[0], JsonPathStep)
    assert chosen.steps[0].source == "js_state"
    assert located.recipes == {}


def test_without_the_state_the_call_wins_and_its_recipe_replays() -> None:
    located, sent = _locate([_sampled(n, state=False) for n in range(3)])

    chosen = located.fields["material"]
    assert (chosen.needs, chosen.call) == ("call", "material")
    assert isinstance(chosen.steps[0], JsonPathStep)
    assert chosen.steps[0].source == "xhr"
    recipe = located.recipes["material"]
    assert recipe.url == f"{SITE}/api/items/{{p1}}"
    # Replayed over HTTP for each page: to prove the headers, then to validate the step on the other two.
    assert {str(request.url) for request in sent} == {_endpoint(n) for n in range(3)}


def test_without_the_state_and_the_call_only_the_browser_has_it() -> None:
    located, _ = _locate([_sampled(n, state=False, call=False) for n in range(3)])

    assert set(located.sources["material"]) == {"browser"}
    assert located.fields["material"].needs == "browser"


def test_a_field_no_render_publishes_is_not_found_in_render() -> None:
    pages = [_sampled(n) for n in range(3)]
    unpublished = [Sampled(p.stored, p.render, p.page, p.ctx, {"title": "x"}) for p in pages]

    located, _ = _locate(unpublished)

    assert located.reasons == {"material": "not_found_in_render"}


def test_located_fields_join_the_config_with_their_recipes_as_located() -> None:
    located, _ = _locate([_sampled(n, state=False) for n in range(3)])
    refused = Validated(None, ValidationReport(held_out=[], fields={}, listing=None, refused="too_few_held_out"))

    merged = located_config(refused, _base(), located)

    assert merged.ir is not None
    assert merged.report.refused is None
    assert merged.ir.provenance.origin == "located"
    assert merged.ir.recipes == located.recipes
    assert merged.ir.fields["material"].call == "material"


# --- (ii) a credential header is a reference to the request context --------------------------------------------------


def test_a_recipe_needing_authorization_needs_the_request_context_to_name_it() -> None:
    pages = [_sampled(n, state=False) for n in range(3)]

    without, _ = _locate(pages, needs="authorization")
    secret = "Bearer synthetic-secret"  # noqa: S105 - a synthetic value the stand-in checks for
    context = RequestContext(headers=(("Authorization", SecretStr(secret)),))
    located, sent = _locate(pages, needs="authorization", context=context)

    assert without.fields["material"].needs == "browser"
    assert without.recipes == {}
    recipe = located.recipes["material"]
    assert ContextHeader(name="authorization", from_context=True) in recipe.headers
    assert secret not in recipe.model_dump_json()
    assert sent[-1].headers["authorization"] == secret


# --- (iii) the fetch plan of the field sources ------------------------------------------------------------------------


def _active(ir: ExtractionConfigIR) -> ActiveConfig:
    return ActiveConfig(ExtractionConfigId(uuid7()), 1, EngineExecutor(ir, SCHEMA_ORG))


def test_http_and_call_fields_plan_http_with_one_companion_call_per_recipe() -> None:
    located, _ = _locate([_sampled(n, state=False) for n in range(3)])
    ir = _base().model_copy(
        update={
            "fields": {
                "title": FieldSteps(
                    steps=[JsonPathStep(jsonpath="$['props']['page']['slug']", source="js_state")],
                    status="uncorroborated",
                ),
                **located.fields,
            },
            "recipes": located.recipes,
        }
    )

    plan = fetch_plan(_active(ExtractionConfigIR.model_validate(ir.model_dump(by_alias=True))), "off")

    assert not plan.browser
    assert len(plan.calls) == 1
    assert plan.endpoints == (CallEndpoint(method="GET", origin=SITE, segments=("api", "items", None)),)


def test_one_browser_field_plans_the_browser() -> None:
    located, _ = _locate([_sampled(n, state=False, call=False) for n in range(3)])
    ir = _base().model_copy(update={"fields": located.fields})

    assert fetch_plan(_active(ir), "off").browser
    assert fetch_plan(None, "always") == FetchPlan(browser=True)
    assert fetch_plan(None, "locate") == FetchPlan()
