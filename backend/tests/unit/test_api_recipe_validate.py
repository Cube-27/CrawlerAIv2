"""Held-out validation of an API recipe (SPEC-09 §4.7): replay the recipe for each held-out page and accept it only
when every mapped field reproduces the published value on every held-out page that has one; an accepted recipe carries
its proof and enters the validated config, and its report enters the config's validation report.

A stand-in API (`tests.stand_in`, synthetic `.test` hosts) answers the replays through `fetch_json`.
"""

import asyncio
import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime

from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.config_ir.api_recipe.binding import CapturedRequest, Sample
from crawlerai.config_ir.api_recipe.headers import Proven
from crawlerai.config_ir.api_recipe.model import ApiRecipe, Proof, RequestSpec
from crawlerai.config_ir.api_recipe.replay import ReplayPage
from crawlerai.config_ir.api_recipe.validate import HeldOutReplay, RecipeValidated, validate_recipe
from crawlerai.config_ir.validation import RecipeFieldReport, RecipeReport
from crawlerai.core.ids import uuid7
from crawlerai.db.models import CaptureId
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

TYPES = {"title": FieldType.TEXT, "price": FieldType.MONEY}
SCHEMA = SchemaDef.model_validate(
    {
        "id": uuid7(),
        "origin": "user",
        "status": "active",
        "name": "synthetic",
        "page_kind": "detail",
        "fields": {name: FieldSpec(type=type_, description="d", required=True) for name, type_ in TYPES.items()},
    }
)
# `+` joins the amount and currency paths of a money field (SPEC-09 §4.2).
MAP = {"title": "$['data']['name']", "price": "$['data']['price']+$['data']['currency']"}
PRODUCTS = {"desk-lamp": ("Desk Lamp", 19.5), "oak-chair": ("Oak Chair", 120), "tea-cup": ("Tea Cup", 4)}
SITE = "https://shop.example.test"
ENDPOINT = "https://api.example.test/v1/products"
SPEC = RequestSpec(
    method="GET",
    url=f"{ENDPOINT}/{{p1}}",
    params_from_url={"p1": "path:1"},
    headers={"Accept": "application/json"},
)
PROVEN = Proven(SPEC, headers_tried=2)

Answers = Mapping[str, JsonValue]
StandInApi = Callable[[Mapping[str, bytes]], JsonFetcher]  # the `stand_in_api` fixture (conftest)


def _capture(i: int) -> CaptureId:
    return CaptureId(uuid.UUID(int=i + 1))


def _answers(overrides: Answers | None = None) -> dict[str, JsonValue]:
    """The endpoint's answer per product slug: the product's values, unless overridden."""
    answers: dict[str, JsonValue] = {
        slug: {"data": {"name": name, "price": price, "currency": "EUR"}} for slug, (name, price) in PRODUCTS.items()
    }
    return {**answers, **(overrides or {})}


def _values(slug: str) -> dict[str, JsonValue]:
    """The values the engine published for the product's page."""
    name, price = PRODUCTS[slug]
    return {"title": name, "price": {"amount": str(price), "currency": "EUR"}}


def _held_out(
    slugs: Sequence[str] = tuple(PRODUCTS), published: Callable[[str], dict[str, JsonValue]] = _values
) -> list[HeldOutReplay]:
    pages = []
    for i, slug in enumerate(slugs):
        page_url = f"{SITE}/p/{slug}"
        ctx = Context(captured_at=datetime(2026, 10, 14, tzinfo=UTC), base_url=page_url, page_url=page_url)
        sample = Sample(page_url, CapturedRequest("GET", f"{ENDPOINT}/{slug}"))
        pages.append(HeldOutReplay(_capture(i), ReplayPage(sample, published(slug), ctx)))
    return pages


def _run(
    stand_in_api: StandInApi,
    answers: Answers,
    held_out: Sequence[HeldOutReplay],
    fields: Mapping[str, str] = MAP,
) -> tuple[RecipeValidated, list[str]]:
    sent: list[str] = []
    fetcher = stand_in_api({f"{ENDPOINT}/{slug}": json.dumps(answer).encode() for slug, answer in answers.items()})

    async def replay(request: JsonRequest) -> FetchResult:
        sent.append(request.url)
        return await fetcher(request, FetchPolicy(timeout_s=5))

    result = asyncio.run(validate_recipe(PROVEN, "deterministic", fields, held_out, SCHEMA, replay))
    return result, sent


def _report(held_out: Sequence[HeldOutReplay], refused: str | None = None, **fields: tuple[int, int]) -> RecipeReport:
    return RecipeReport(
        held_out=[page.capture_id for page in held_out],
        fields={name: RecipeFieldReport(published=n, reproduced=ok) for name, (n, ok) in fields.items()},
        refused=refused,
    )


def test_a_recipe_that_reproduces_every_held_out_page_is_accepted_with_its_proof(stand_in_api: StandInApi) -> None:
    held_out = _held_out()

    result, sent = _run(stand_in_api, _answers(), held_out)

    assert result == RecipeValidated(
        recipe=ApiRecipe(
            method="GET",
            url=f"{ENDPOINT}/{{p1}}",
            params_from_url={"p1": "path:1"},
            headers={"Accept": "application/json"},
            map=MAP,
            proof=Proof(
                validated_on=[_capture(0), _capture(1), _capture(2)], headers_tried=2, bound_by="deterministic"
            ),
        ),
        report=_report(held_out, title=(3, 3), price=(3, 3)),
    )
    assert sent == [f"{ENDPOINT}/{slug}" for slug in PRODUCTS]


def test_a_value_that_differs_on_one_held_out_page_rejects_the_recipe(stand_in_api: StandInApi) -> None:
    held_out = _held_out()
    answers = _answers({"oak-chair": {"data": {"name": "Oak Chair", "price": 99, "currency": "EUR"}}})

    result, _ = _run(stand_in_api, answers, held_out)

    assert result == RecipeValidated(None, _report(held_out, "not_reproduced: price", title=(3, 3), price=(3, 2)))
