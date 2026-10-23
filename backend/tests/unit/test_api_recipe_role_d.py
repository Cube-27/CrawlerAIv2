"""Role D: when deterministic binding is ambiguous, the model writes a request spec from the sample
requests, and the spec is accepted only by replay: it must reproduce every captured request, then its replay must
reproduce the published values. A spec that does not reproduce gets one repair round, and nothing is fetched for it.

The client is scripted and a stand-in API (`tests.stand_in`, synthetic `.test` hosts) answers the replays through
`fetch_json`.
"""

import asyncio
import json
from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.config_ir.api_recipe.binding import Ambiguous, CapturedRequest, PageData, Sample, bind
from crawlerai.config_ir.api_recipe.headers import NotLearnable, Proven
from crawlerai.config_ir.api_recipe.model import HeaderValue, RequestSpec
from crawlerai.config_ir.api_recipe.replay import ReplayPage
from crawlerai.config_ir.api_recipe.role_d import REPAIR_SYSTEM, SYSTEM, Rejected, bind_by_role_d
from crawlerai.core.ids import uuid7
from crawlerai.db.models import JobId
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from tests.stand_in import StandInApi
from tests.support.fake_llm import ScriptedClient

JOB = JobId(uuid7())
SCHEMA = SchemaDef.model_validate(
    {
        "id": uuid7(),
        "origin": "user",
        "status": "active",
        "name": "synthetic",
        "page_kind": "detail",
        "fields": {
            "title": FieldSpec(type=FieldType.TEXT, description="d", required=True),
            "price": FieldSpec(type=FieldType.MONEY, description="d", required=True),
        },
    }
)
MAP = {"title": "$['data']['name']", "price": "$['data']['price']+$['data']['currency']"}
# The page URL ends in the product's slug and id; the endpoint takes the id alone, which no path segment equals.
PRODUCTS = {"1001": ("desk-lamp", "Desk Lamp", 19.5), "2002": ("oak-chair", "Oak Chair", 120)}
SITE = "https://shop.example.test"
ENDPOINT = "https://api.example.test/v1/products"
REGEX = "regex:^/p/[a-z-]+-([0-9]+)$"
GOOD: dict[str, JsonValue] = {
    "method": "GET",
    "url": f"{ENDPOINT}/{{p1}}",
    "params": [{"name": "p1", "binder": REGEX}],
    "body": None,
}
# Path segment 1 holds `desk-lamp-1001`, not the id the endpoint takes.
WHOLE_SEGMENT: dict[str, JsonValue] = {**GOOD, "params": [{"name": "p1", "binder": "path:1"}]}


def _page_url(product_id: str) -> str:
    return f"{SITE}/p/{PRODUCTS[product_id][0]}-{product_id}"


def _pages(
    headers: Sequence[tuple[str, str]] = (), page_data: PageData | None = None, query: str = ""
) -> list[ReplayPage]:
    pages = []
    for product_id, (_, name, price) in PRODUCTS.items():
        page_url = _page_url(product_id)
        request = CapturedRequest("GET", _endpoint(product_id, query), headers=tuple(headers))
        data = page_data if page_data is not None else {}
        sample = Sample(page_url, request, {kind: _for(value, product_id) for kind, value in data.items()})
        ctx = Context(captured_at=datetime(2026, 10, 14, tzinfo=UTC), base_url=page_url, page_url=page_url)
        values: dict[str, JsonValue] = {"title": name, "price": {"amount": str(price), "currency": "EUR"}}
        pages.append(ReplayPage(sample, values, ctx))
    return pages


def _endpoint(product_id: str, query: str = "") -> str:
    return f"{ENDPOINT}/{product_id}{query.replace('{id}', product_id)}"


def _for(document: JsonValue, product_id: str) -> JsonValue:
    """`document` with `{id}` in its string values replaced by the product's id."""
    replaced: JsonValue = json.loads(json.dumps(document).replace("{id}", product_id))
    return replaced


def _api(stand_in_api: StandInApi, price_offset: float = 0, query: str = "") -> JsonFetcher:
    answers = {
        _endpoint(product_id, query): json.dumps(
            {"data": {"id": product_id, "name": name, "price": price + price_offset, "currency": "EUR"}}
        ).encode()
        for product_id, (_, name, price) in PRODUCTS.items()
    }
    return stand_in_api(answers)


def _run(
    client: ScriptedClient, pages: Sequence[ReplayPage], fetcher: JsonFetcher
) -> tuple[Proven | NotLearnable | Rejected, list[str]]:
    sent: list[str] = []

    async def replay(request: JsonRequest) -> FetchResult:
        sent.append(request.url)
        return await fetcher(request, FetchPolicy(timeout_s=5))

    ambiguous = bind([page.sample for page in pages])
    assert isinstance(ambiguous, Ambiguous)  # the case role D takes
    result = asyncio.run(bind_by_role_d(client, ambiguous, MAP, pages, SCHEMA, replay, job_id=JOB))
    return result, sent


def _accepted() -> Proven:
    spec = RequestSpec(
        method="GET",
        url=f"{ENDPOINT}/{{p1}}",
        params_from_url={"p1": REGEX},
        headers=[HeaderValue(name="Accept", value="application/json")],
    )
    return Proven(spec, headers_tried=0)


def test_a_spec_that_reproduces_the_requests_and_their_values_is_accepted(stand_in_api: StandInApi) -> None:
    client = ScriptedClient(GOOD)

    result, sent = _run(client, _pages(), _api(stand_in_api))

    assert result == _accepted()
    assert sent == [f"{ENDPOINT}/1001", f"{ENDPOINT}/2002"]
    assert [(r.prompt_kind, r.model_class, r.system) for r in client.requests] == [("d_bind", "strong", SYSTEM)]


def test_a_spec_that_does_not_reproduce_a_request_is_repaired_once_and_never_fetched(stand_in_api: StandInApi) -> None:
    client = ScriptedClient(WHOLE_SEGMENT, GOOD)

    result, sent = _run(client, _pages(), _api(stand_in_api))

    assert result == _accepted()
    assert sent == [f"{ENDPOINT}/1001", f"{ENDPOINT}/2002"]  # the replays of the repaired spec only
    repair = client.requests[1]
    assert repair.system == REPAIR_SYSTEM
    assert f"- page 1: url_mismatch({ENDPOINT}/desk-lamp-1001, {ENDPOINT}/1001)" in repair.user
    assert f"- page 2: url_mismatch({ENDPOINT}/oak-chair-2002, {ENDPOINT}/2002)" in repair.user


def test_a_spec_whose_replay_answers_other_values_is_not_accepted(stand_in_api: StandInApi) -> None:
    client = ScriptedClient(GOOD)

    result, sent = _run(client, _pages(), _api(stand_in_api, price_offset=1))

    assert result == NotLearnable("no single captured header makes the replay reproduce the sample values", 0)
    assert sent == [f"{ENDPOINT}/1001"]  # the first page failed; no captured header was left to try
