"""The labeling API against Postgres (SPEC-03 §7: "the labeling tool can create, check and export labels for a dev
capture"): a synthetic dev page is labeled by one person, checked by another and read back, through the app with
`CRAWLERAI_EVAL_UI` on. Throwaway main database (`CRAWLERAI_TEST_DATABASE_URL`) and a temporary object root."""

from collections.abc import AsyncIterator
from contextlib import aclosing
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import JsonValue
from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import create_async_engine

from crawlerai.acquire.types import FetchPolicy
from crawlerai.api.app import create_app
from crawlerai.core.ids import uuid7
from crawlerai.core.settings import Settings
from crawlerai.db.models import Capture, EvalPage, SchemaDef, Site
from crawlerai.eval.store import EvalPageRow, get_store
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex

pytestmark = pytest.mark.anyio

SCHEMA = "labeling_api_detail"
URL = "https://shop.labeling-api.example.test/items/1"
BODY = b"<html><body><h1>Blue mug</h1><p>EUR 19.90</p><script>x()</script></body></html>"
FIELDS = {
    "title": {"type": "text", "required": True, "description": "Item name"},
    "price": {"type": "money", "required": True, "description": "Price"},
}


@pytest.fixture
async def client(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[httpx.AsyncClient, str]]:
    """A client of the app with the labeling API, and the id of one unlabeled dev page."""
    object_store = "fs:///" + tmp_path.as_posix().lstrip("/")
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", database_url)
    monkeypatch.setenv("CRAWLERAI_OBJECT_STORE", object_store)
    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        schema_id = (
            await conn.execute(
                insert(SchemaDef)
                .values(name=SCHEMA, version=1, page_kind="detail", fields=FIELDS, origin="user", status="active")
                .returning(SchemaDef.id)
            )
        ).scalar_one()
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=URL,
        final_url=URL,
        fetched_at=datetime.now(UTC),
        method="http",
        status_code=200,
        block_class="ok",
        headers=Headers(request=(), response=()),
        timings_ms={"total": 1},
        html_sha256=sha256_hex(BODY),
        network_bodies=(),
        fetch_policy=FetchPolicy().model_dump(mode="json"),
        engine_version="test",
    )
    settings = Settings.model_validate({"database_url": database_url, "object_store": object_store})
    async with aclosing(get_store("dev", settings)) as store:
        capture_id = await store.put_capture(CaptureBundle(manifest=manifest, body=BODY, network=()), "custom_store")
        page_id = await store.put_page(
            EvalPageRow(
                capture_id=capture_id,
                split="dev",
                schema_id=schema_id,
                schema_name=SCHEMA,
                page_kind="detail",
                category="custom_store",
            )
        )
    app = create_app(eval_ui=True)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test") as http,
    ):
        yield http, str(page_id)
    async with engine.begin() as conn:
        await conn.execute(delete(EvalPage).where(EvalPage.schema_name == SCHEMA))
        await conn.execute(delete(Capture).where(Capture.id == capture_id))
        await conn.execute(delete(Site).where(Site.host.like("%.labeling-api.example.test")))
        await conn.execute(delete(SchemaDef).where(SchemaDef.name == SCHEMA))
    await engine.dispose()


def _labels(status: str, checker: str | None = None) -> dict[str, JsonValue]:
    return {
        "label_version": 1,
        "status": status,
        "labeler": "ana",
        "checker": checker,
        "fields": {
            "title": {"value": "Blue mug", "absent": False, "locator": "xpath://h1"},
            "price": {"value": {"amount": "19.90", "currency": "EUR"}, "absent": False},
        },
    }


async def test_a_dev_page_is_labeled_checked_and_exported(client: tuple[httpx.AsyncClient, str]) -> None:
    http, page_id = client

    page = (await http.get(f"/v1/eval/pages/{page_id}")).json()
    labeled = await http.put(f"/v1/eval/pages/{page_id}/labels", json=_labels("labeled"))
    self_check = await http.put(f"/v1/eval/pages/{page_id}/labels", json=_labels("checked", checker="ana"))
    checked = await http.put(f"/v1/eval/pages/{page_id}/labels", json=_labels("checked", checker="ben"))
    exported = (await http.get(f"/v1/eval/pages/{page_id}")).json()
    listed = (await http.get(f"/v1/eval/pages?status=checked&schema={SCHEMA}")).json()

    assert (page["status"], page["labels"]) == (None, None)
    assert "<script>" not in page["bundle_html"]
    assert (labeled.status_code, labeled.json()["labeler"]) == (200, "ana")
    assert self_check.status_code == 422
    assert (checked.status_code, checked.json()["checker"]) == (200, "ben")
    assert exported["labels"]["status"] == "checked"
    assert exported["labels"]["fields"]["price"]["value"] == {"amount": "19.90", "currency": "EUR"}
    assert (exported["labeler"], exported["checker"]) == ("ana", "ben")
    assert [row["id"] for row in listed] == [page_id]
