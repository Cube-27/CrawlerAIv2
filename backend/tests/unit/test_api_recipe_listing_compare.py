"""A listing recipe's replay compared with the captured pages (adapters spec, "Held-out validation"): a field is
compared when any captured page has a value for it, so a value found only on a later captured page is still checked."""

import asyncio
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.config_ir.api_recipe.binding import CapturedRequest, Sample
from crawlerai.config_ir.api_recipe.model import ParamPagination, RequestSpec
from crawlerai.config_ir.api_recipe.replay import ReplayPage, compare
from crawlerai.core.ids import uuid7
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

StandInApi = Callable[[Mapping[str, bytes]], JsonFetcher]  # the `stand_in_api` fixture (conftest)

ENDPOINT = "https://api.example.test/v1/items"
PAGE_URL = "https://shop.example.test/c/lamps"
SCHEMA = SchemaDef.model_validate(
    {
        "id": uuid7(),
        "origin": "user",
        "status": "active",
        "name": "synthetic",
        "page_kind": "listing",
        "fields": {"label": FieldSpec(type=FieldType.TEXT, description="d")},
    }
)
SPEC = RequestSpec(
    method="GET",
    url=f"{ENDPOINT}?page=1",
    pagination=ParamPagination(kind="param", where="query", name="page", start=1, step=1, rows="$['items'][*]"),
)


def _items(*labels: str | None) -> JsonValue:
    return {"items": [{"label": label} for label in labels]}


def test_a_field_valued_only_on_the_second_captured_page_is_compared_there(stand_in_api: StandInApi) -> None:
    ctx = Context(captured_at=datetime(2026, 10, 18, tzinfo=UTC), base_url=PAGE_URL, page_url=PAGE_URL)
    page = ReplayPage(
        Sample(PAGE_URL, CapturedRequest("GET", f"{ENDPOINT}?page=1")), {}, ctx, (_items(None), _items("a"))
    )
    answers = {f"{ENDPOINT}?page=1": _items(None), f"{ENDPOINT}?page=2": _items("b")}
    fetcher = stand_in_api({url: json.dumps(answer).encode() for url, answer in answers.items()})

    async def replay(request: JsonRequest) -> FetchResult:
        return await fetcher(request, FetchPolicy(timeout_s=5))

    compared = asyncio.run(compare(SPEC, {"label": "$['label']"}, page, SCHEMA, replay))

    assert compared == {"label": False}
