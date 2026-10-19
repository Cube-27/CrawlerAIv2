"""The `render` member of the requests that extract `records` (rest-api spec, "Render mode"): `{mode, fields}`, and the
`render_fields` list it replaces is refused."""

import asyncio
import uuid

import httpx
import pytest
from pydantic import ValidationError

from crawlerai.api.app import create_app
from crawlerai.api.auth import require_api_key
from crawlerai.core.ids import uuid7
from crawlerai.db.models import ApiKeyId, SchemaId
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from crawlerai.services.batch import BatchScrapeRequest
from crawlerai.services.crawl import CrawlRequest
from crawlerai.services.scrape import ScrapeRequest
from crawlerai.services.scrape_steps import RenderOptions, SchemaUnusable, check_render

URL = "https://shop.example.test/p/1"
BODY = {"urls": [URL], "formats": ["records"], "schema": {"id": str(uuid.UUID(int=1))}, "page_kind": "detail"}


def _post(path: str, body: object) -> httpx.Response:
    app = create_app(eval_ui=False)
    app.dependency_overrides[require_api_key] = lambda: ApiKeyId(uuid.UUID(int=1))

    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as client:
            return await client.post(path, json=body)

    return asyncio.run(send())


def test_render_fields_is_refused() -> None:
    response = _post("/v1/batch/scrape", {**BODY, "render_fields": ["size"]})

    assert response.status_code == 422
    assert [error["field"] for error in response.json()["errors"]] == ["render_fields"]


def test_render_takes_a_mode_and_fields() -> None:
    request = BatchScrapeRequest.model_validate({**BODY, "render": {"mode": "locate", "fields": ["size"]}})

    assert request.render == RenderOptions(mode="locate", fields=["size"])
    assert BatchScrapeRequest.model_validate(BODY).render == RenderOptions(mode="off", fields=[])
    for model, body in (
        (ScrapeRequest, {"url": URL, "formats": ["markdown"]}),
        (CrawlRequest, {"url": URL, "formats": ["markdown"]}),
    ):
        assert model.model_validate({**body, "render": {"mode": "always"}}).render.mode == "always"


@pytest.mark.parametrize("render", [{"mode": "sometimes"}, {"fields": "size"}, {"mode": "off", "names": []}])
def test_render_refuses_an_unknown_mode_or_member(render: object) -> None:
    with pytest.raises(ValidationError):
        BatchScrapeRequest.model_validate({**BODY, "render": render})


def test_render_fields_are_the_schemas() -> None:
    fields = {"title": FieldSpec(type=FieldType.TEXT, description="d", required=True)}
    schema = SchemaDef(
        id=SchemaId(uuid7()), origin="user", status="active", name="s", page_kind="detail", fields=fields
    )

    check_render(RenderOptions(mode="locate", fields=["title"]), schema)
    with pytest.raises(SchemaUnusable, match="size"):
        check_render(RenderOptions(mode="locate", fields=["title", "size"]), schema)
