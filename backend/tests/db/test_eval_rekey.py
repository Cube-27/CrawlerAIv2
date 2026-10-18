"""`crawlerai eval re-key` against a throwaway database (`CRAWLERAI_TEST_DATABASE_URL`) and a temporary object root:
draft labels recomputed from the label file against the stored capture, rows the capture lacks marked stale, pages
that are not drafts or not in the golden set left alone. Synthetic `.test` pages only (C9)."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import create_async_engine

from crawlerai.core.ids import uuid7
from crawlerai.db.models import Capture, EvalPage, SchemaDef, SchemaId, Site
from crawlerai.eval.cli import PageRequest
from crawlerai.eval.label_file import LabeledPage
from crawlerai.eval.labels import Labels
from crawlerai.eval.rekey import NotRekeyed, Rekeyed, rekey_pages
from crawlerai.eval.store import DevEvalStore, EvalPageRow
from crawlerai.schemas.types import FieldSpec, FieldType
from crawlerai.schemas.types import SchemaDef as Schema
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex
from crawlerai.storage.fs import FsStore

pytestmark = pytest.mark.anyio

HOST = "shop.eval-rekey.example.test"
NAME = "eval_rekey_listing"
BODY = b'<html><body><ul><li><a href="/p/lamp">Table Lamp</a></li></ul></body></html>'


def _bundle(path: str) -> CaptureBundle:
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=f"https://{HOST}{path}",
        final_url=f"https://{HOST}{path}",
        fetched_at=datetime(2026, 10, 1, 12, 30, tzinfo=UTC),
        method="http",
        status_code=200,
        block_class="ok",
        headers=Headers(request=(), response=(("Content-Type", "text/html; charset=utf-8"),)),
        timings_ms={"total": 1},
        html_sha256=sha256_hex(BODY),
        network_bodies=(),
        fetch_policy={},
        engine_version="0+cal.0",
    )
    return CaptureBundle(manifest=manifest, body=BODY, network=())


@pytest.fixture
async def store(database_url: str, tmp_path: Path) -> AsyncIterator[tuple[DevEvalStore, Schema]]:
    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        schema_id: SchemaId = (
            await conn.execute(
                insert(SchemaDef)
                .values(name=NAME, page_kind="listing", fields={}, origin="user", status="active")
                .returning(SchemaDef.id)
            )
        ).scalar_one()
    schema = Schema(
        id=schema_id,
        origin="user",
        status="active",
        name=NAME,
        page_kind="listing",
        fields={
            "title": FieldSpec(type=FieldType.TEXT, description="d", scope="row"),
            "url": FieldSpec(type=FieldType.URL, description="d", scope="row"),
        },
    )
    yield DevEvalStore(engine, FsStore(tmp_path)), schema
    async with engine.begin() as conn:
        await conn.execute(delete(EvalPage))
        await conn.execute(delete(Capture).where(Capture.object_key.like("eval/dev/%")))
        await conn.execute(delete(Site).where(Site.host == HOST))
        await conn.execute(delete(SchemaDef).where(SchemaDef.id == schema_id))
    await engine.dispose()


async def _stored(store: DevEvalStore, schema: Schema, path: str, status: str) -> EvalPageRow:
    capture_id = await store.put_capture(_bundle(path), "custom_store")
    page = EvalPageRow(
        capture_id=capture_id,
        split="dev",
        schema_id=schema.id,
        schema_name=NAME,
        page_kind="listing",
        category="custom_store",
        labels={"label_version": 1, "status": status, "prefill_source": "none", "fields": {}, "rows": []}
        if status == "draft"
        else {},
    )
    await store.put_page(page)
    return page


def _file_page(n: int, path: str) -> LabeledPage:
    rows = (
        {"title": "Table Lamp", "url": f"https://{HOST}/p/lamp"},
        {"title": "Sofa", "url": f"https://{HOST}/p/sofa"},
    )
    return LabeledPage(PageRequest(n, f"https://{HOST}{path}", NAME, "custom_store"), {}, rows, "")


async def test_draft_labels_are_recomputed_and_rows_the_capture_lacks_marked_stale(
    store: tuple[DevEvalStore, Schema],
) -> None:
    eval_store, schema = store
    page = await _stored(eval_store, schema, "/c/1", "draft")
    await _stored(eval_store, schema, "/c/2", "unlabeled")
    pages = [_file_page(1, "/c/1"), _file_page(2, "/c/2"), _file_page(3, "/c/3")]

    outcomes = await rekey_pages(eval_store, {NAME: schema}, pages)

    assert outcomes == [
        Rekeyed(1, rows=2, stale=1, labeled=4, declined=()),
        NotRekeyed(2, "not_draft"),
        NotRekeyed(3, "not_in_split"),
    ]
    labels = Labels.model_validate((await eval_store.get_page(page.id)).labels)
    assert [(row.fields["title"].value, row.stale) for row in labels.rows] == [("Table Lamp", False), ("Sofa", True)]
