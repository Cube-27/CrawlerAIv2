"""Recipe learning in a learning run (SPEC-09 §2 "integration into SPEC-08 learning", §4.3 to §4.7): from the sample
pages' browser captures, find the endpoint that carries the published values, bind its request (deterministically, or
by role D when that is ambiguous), prove its headers by replay and validate it on the held-out pages. Only a recipe
that passed all of it comes back with its proof; one that failed comes back refused with the reason.

Pages are synthetic browser captures on `.test` hosts whose network bodies hold the endpoint's JSON; a stand-in API
(`httpx.MockTransport`) answers the replays through `fetch_json`, and role D is the fake provider's scripted client.
"""

import asyncio
import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime

from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.config_ir.api_recipe.learn import learn_recipe
from crawlerai.config_ir.api_recipe.model import ApiRecipe, Proof
from crawlerai.config_ir.api_recipe.validate import RecipeValidated
from crawlerai.config_ir.held_out import StoredPage
from crawlerai.config_ir.induction import SamplePage
from crawlerai.config_ir.validation import Facts, HeldOutPage, RecipeFieldReport, RecipeReport
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import CaptureId, JobId
from crawlerai.llm.providers.fake import ScriptedClient
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, NetworkBody, sha256_hex

StandInApi = Callable[[Mapping[str, bytes]], JsonFetcher]  # the `stand_in_api` fixture (conftest)
JOB = JobId(uuid7())
SITE = "https://shop.example.test"
ENDPOINT = "https://api.example.test/v1/products"
# `+` joins the amount and currency paths of a money field (SPEC-09 §4.2).
MAP = {"title": "$['data']['name']", "price": "$['data']['price']+$['data']['currency']"}
# Eight products: the first five are the learning sample, the rest held out (ARCHITECTURE §8.3).
PRODUCTS = [(f"{100 + n}", f"item-{chr(97 + n)}", f"Item {chr(65 + n)}", f"{n + 1}.50") for n in range(8)]


def _schema(page_kind: str = "detail") -> SchemaDef:
    return SchemaDef.model_validate(
        {
            "id": uuid7(),
            "origin": "user",
            "status": "active",
            "name": "synthetic",
            "version": 1,
            "page_kind": page_kind,
            "fields": {
                "title": FieldSpec(type=FieldType.TEXT, description="d", required=True),
                "price": FieldSpec(type=FieldType.MONEY, description="d", required=True),
            },
        }
    )


def _capture(n: int) -> CaptureId:
    return CaptureId(uuid.UUID(int=n + 1))


def _answer(name: str, amount: str) -> bytes:
    return json.dumps({"data": {"name": name, "price": amount, "currency": "EUR"}}).encode()


def _bundle(page_url: str, html: str, bodies: Sequence[tuple[str, bytes]]) -> CaptureBundle:
    body = html.encode()
    entries = tuple(
        NetworkBody(
            url=url,
            status=200,
            content_type="application/json",
            sha256=sha256_hex(data),
            file=f"network/{i + 1:04d}.json",
            method="GET",
        )
        for i, (url, data) in enumerate(bodies)
    )
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=page_url,
        final_url=page_url,
        fetched_at=datetime(2026, 10, 14, tzinfo=UTC),
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
    return CaptureBundle(manifest=manifest, body=body, network=tuple(data for _, data in bodies))


def _page(n: int, page_url: str, endpoint: str | None) -> StoredPage:
    """Product `n`'s stored page at `page_url`: the browser rendered its values, and fetched them from `endpoint`."""
    _, _, name, amount = PRODUCTS[n]
    bodies = [] if endpoint is None else [(endpoint, _answer(name, amount))]
    bundle = _bundle(page_url, f"<html><body><h1>{name}</h1><p>{amount} EUR</p></body></html>", bodies)
    parsed = ParsedPage.of(bundle)
    ctx = Context(captured_at=datetime(2026, 10, 14, tzinfo=UTC), base_url=page_url, page_url=page_url)
    values: dict[str, JsonValue] = {"title": name, "price": {"amount": amount, "currency": "EUR"}}
    held_out = HeldOutPage(_capture(n), parsed, ctx, Facts(published=values))
    return StoredPage(held_out, SamplePage(parsed, ctx, {}), bundle)


def _by_slug(n: int, *, captured: bool = True) -> StoredPage:
    """Page `/p/<slug>`, whose endpoint takes the slug (a path segment of the page URL)."""
    _, slug, _, _ = PRODUCTS[n]
    return _page(n, f"{SITE}/p/{slug}", f"{ENDPOINT}/{slug}" if captured else None)


def _by_id(n: int) -> StoredPage:
    """Page `/p/<slug>-<id>`, whose endpoint takes the id, which no path segment of the page URL equals."""
    product_id, slug, _, _ = PRODUCTS[n]
    return _page(n, f"{SITE}/p/{slug}-{product_id}", f"{ENDPOINT}/{product_id}")


def _routes(key: Callable[[int], str]) -> dict[str, bytes]:
    return {f"{ENDPOINT}/{key(n)}": _answer(name, amount) for n, (_, _, name, amount) in enumerate(PRODUCTS)}


BY_SLUG = _routes(lambda n: PRODUCTS[n][1])


def _learn(
    stand_in_api: StandInApi,
    pages: Sequence[StoredPage],
    routes: Mapping[str, bytes] = BY_SLUG,
    client: ScriptedClient | None = None,
    schema: SchemaDef | None = None,
) -> tuple[RecipeValidated, list[str]]:
    sent: list[str] = []
    fetcher = stand_in_api(routes)

    async def replay(request: JsonRequest) -> FetchResult:
        sent.append(request.url)
        return await fetcher(request, FetchPolicy(timeout_s=5))

    learned = learn_recipe(client or ScriptedClient(), pages[:5], pages[5:], schema or _schema(), replay, job_id=JOB)
    return asyncio.run(learned), sent


def _held_out_report(*captures: int) -> RecipeReport:
    every = RecipeFieldReport(published=len(captures), reproduced=len(captures))
    return RecipeReport(held_out=[_capture(n) for n in captures], fields={"title": every, "price": every})


def test_an_endpoint_that_carries_the_sample_values_becomes_a_validated_recipe(stand_in_api: StandInApi) -> None:
    client = ScriptedClient()

    learned, sent = _learn(stand_in_api, [_by_slug(n) for n in range(8)], client=client)

    assert learned == RecipeValidated(
        recipe=ApiRecipe(
            method="GET",
            url=f"{ENDPOINT}/{{p1}}",
            params_from_url={"p1": "path:1"},
            headers={"Accept": "application/json"},
            map=MAP,
            proof=Proof(
                validated_on=[_capture(5), _capture(6), _capture(7)], headers_tried=0, bound_by="deterministic"
            ),
        ),
        report=_held_out_report(5, 6, 7),
    )
    # The five sample pages are replayed to prove the headers, then the three held-out ones; role D is not asked.
    assert sent == [f"{ENDPOINT}/{PRODUCTS[n][1]}" for n in range(8)]
    assert client.requests == []


def test_an_ambiguous_binding_is_bound_by_role_d_and_accepted_by_replay(stand_in_api: StandInApi) -> None:
    spec: dict[str, JsonValue] = {
        "method": "GET",
        "url": f"{ENDPOINT}/{{p1}}",
        "params": [{"name": "p1", "binder": "regex:^/p/[a-z-]+-([0-9]+)$"}],
        "body": None,
    }
    client = ScriptedClient(spec)

    learned, _ = _learn(stand_in_api, [_by_id(n) for n in range(8)], _routes(lambda n: PRODUCTS[n][0]), client)

    assert learned is not None
    assert learned.report == _held_out_report(5, 6, 7)
    assert learned.recipe is not None
    assert (learned.recipe.params_from_url, learned.recipe.proof.bound_by) == (
        {"p1": "regex:^/p/[a-z-]+-([0-9]+)$"},
        "role_d",
    )
    assert [request.prompt_kind for request in client.requests] == ["d_bind"]


def test_a_role_d_spec_that_reproduces_no_request_refuses_the_recipe(stand_in_api: StandInApi) -> None:
    whole_segment: dict[str, JsonValue] = {
        "method": "GET",
        "url": f"{ENDPOINT}/{{p1}}",
        "params": [{"name": "p1", "binder": "path:1"}],
        "body": None,
    }
    client = ScriptedClient(whole_segment, whole_segment)

    learned, sent = _learn(stand_in_api, [_by_id(n) for n in range(8)], _routes(lambda n: PRODUCTS[n][0]), client)

    assert learned is not None
    assert learned.recipe is None
    assert learned.report.held_out == []
    assert learned.report.refused is not None
    assert learned.report.refused.startswith("role_d_rejected: page 1: url_mismatch(")
    assert sent == []


def test_an_endpoint_whose_replay_fails_refuses_the_recipe_as_not_learnable(stand_in_api: StandInApi) -> None:
    learned, sent = _learn(stand_in_api, [_by_slug(n) for n in range(8)], routes={})

    assert learned == RecipeValidated(
        None,
        RecipeReport(
            held_out=[],
            fields={},
            refused="not_learnable: no single captured header makes the replay reproduce the sample values",
        ),
    )
    assert sent == [f"{ENDPOINT}/{PRODUCTS[0][1]}"]


def test_a_held_out_page_without_a_response_of_the_endpoint_is_not_validated_on(stand_in_api: StandInApi) -> None:
    # §4.7: the recipe is validated on held-out browser captures of the endpoint; the last page has none.
    pages = [_by_slug(n, captured=n != 7) for n in range(8)]

    learned, _ = _learn(stand_in_api, pages)

    assert learned == RecipeValidated(
        None, RecipeReport(held_out=[_capture(5), _capture(6)], fields={}, refused="too_few_held_out")
    )


# --- why a run has no recipe (D-0583: the report says) ---


def test_pages_without_network_responses_say_so(stand_in_api: StandInApi) -> None:
    learned, sent = _learn(stand_in_api, [_by_slug(n, captured=False) for n in range(8)])

    assert learned.recipe is None
    assert (learned.report.refused or "").startswith("no_network_bodies:")
    assert sent == []


def test_responses_that_carry_no_published_value_say_no_endpoint(stand_in_api: StandInApi) -> None:
    def unrelated(n: int) -> StoredPage:
        page = _by_slug(n)
        other = _bundle(page.bundle.manifest.url, page.bundle.body.decode(), [(f"{ENDPOINT}/x{n}", b'{"ok": true}')])
        return StoredPage(page.held_out, page.sample, other)

    learned, _ = _learn(stand_in_api, [unrelated(n) for n in range(8)])

    assert learned.recipe is None
    assert (learned.report.refused or "").startswith("no_endpoint:")


def test_a_listing_says_its_recipe_needs_pagination(stand_in_api: StandInApi) -> None:
    learned, sent = _learn(stand_in_api, [_by_slug(n) for n in range(8)], schema=_schema("listing"))

    assert learned.recipe is None
    assert (learned.report.refused or "").startswith("listing:")
    assert sent == []
