"""The eval store over a throwaway database and a temporary object root. Synthetic data only: `.test` hosts, made-up
bundles (C9)."""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import delete, insert, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from crawlerai.core.ids import uuid7
from crawlerai.db.models import (
    Capture,
    CaptureId,
    EvalPage,
    EvalPageId,
    EvalRun,
    SchemaDef,
    SchemaId,
    Site,
)
from crawlerai.eval.store import (
    DevEvalStore,
    EvalNotFound,
    EvalPageRow,
    EvalStore,
    Labels,
)
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex
from crawlerai.storage.fs import FsStore

pytestmark = pytest.mark.anyio

HOST = "shop.eval-store.example.test"
SCHEMA_NAME = "eval_store_detail"


@dataclass
class Case:
    store: EvalStore
    root: Path  # the store's object root
    schema_id: SchemaId


@pytest.fixture
async def case(database_url: str, tmp_path: Path) -> AsyncIterator[Case]:
    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        schema_id: SchemaId = (
            await conn.execute(
                insert(SchemaDef)
                .values(name=SCHEMA_NAME, page_kind="detail", fields={}, origin="user", status="active")
                .returning(SchemaDef.id)
            )
        ).scalar_one()
    yield Case(DevEvalStore(engine, FsStore(tmp_path)), tmp_path, schema_id)
    async with engine.begin() as conn:
        await conn.execute(delete(EvalPage))
        await conn.execute(delete(EvalRun))
        await conn.execute(delete(Capture).where(Capture.object_key.like("eval/dev/%")))
        await conn.execute(delete(Site).where(Site.host == HOST))
        await conn.execute(delete(SchemaDef).where(SchemaDef.id == schema_id))
    await engine.dispose()


def _bundle(path: str = "/p/1") -> CaptureBundle:
    body = f"<html><body><h1>Item {path}</h1></body></html>".encode()
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=f"https://{HOST}{path}",
        final_url=f"https://{HOST}{path}",
        fetched_at=datetime(2026, 10, 1, 12, 30, tzinfo=UTC),
        method="http",
        status_code=200,
        block_class="ok",
        headers=Headers(request=(("Accept", "text/html"),), response=(("Content-Type", "text/html"),)),
        timings_ms={"total": 240},
        html_sha256=sha256_hex(body),
        network_bodies=(),
        fetch_policy={"timeout_s": 12.0},
        engine_version="0+cal.0",
    )
    return CaptureBundle(manifest=manifest, body=body, network=())


def _page(case: Case, capture_id: CaptureId, **fields: object) -> EvalPageRow:
    values: dict[str, object] = {
        "capture_id": capture_id,
        "split": case.store.split,
        "schema_id": case.schema_id,
        "schema_name": SCHEMA_NAME,
        "page_kind": "detail",
        "category": "custom_store",
    }
    return EvalPageRow.model_validate(values | fields)


async def test_a_page_round_trips(case: Case) -> None:
    capture_id = await case.store.put_capture(_bundle(), "api_backed")
    page = _page(
        case,
        capture_id,
        category="api_backed",
        page_kind="listing",
        labels={"label_version": 1, "status": "draft", "fields": {}},
        config_snapshot={"version": 3},
    )

    page_id = await case.store.put_page(page)

    assert page_id == page.id
    assert await case.store.get_page(page_id) == page
    unknown = EvalPageId(uuid7())
    with pytest.raises(EvalNotFound):
        await case.store.get_page(unknown)


async def test_the_labeler_cannot_check_their_own_labels(case: Case) -> None:
    capture_id = await case.store.put_capture(_bundle(), "custom_store")
    page_id = await case.store.put_page(_page(case, capture_id))
    await case.store.put_labels(page_id, {"status": "labeled"}, "ana", "labeler", expected={})
    labels: Labels = {"status": "checked"}
    expected: Labels = {"status": "labeled"}

    with pytest.raises(IntegrityError, match="two_people"):
        await case.store.put_labels(page_id, labels, "ana", "checker", expected=expected)

    page = await case.store.get_page(page_id)
    assert (page.labels, page.checker) == ({"status": "labeled"}, None)


@pytest.mark.parametrize("expires_at", [datetime(2026, 10, 31, tzinfo=UTC), None])
async def test_a_dev_page_cannot_reference_a_production_capture(
    database_url: str, tmp_path: Path, expires_at: datetime | None
) -> None:
    """A dev eval page needs a dev eval capture: under `eval/dev/`, never expiring (persistence-storage spec). A
    production capture is refused whether or not it expires (`store_capture` can write one without an expiry)."""
    engine = create_async_engine(database_url)
    store = DevEvalStore(engine, FsStore(tmp_path))
    capture_id = CaptureId(uuid7())
    try:
        async with engine.begin() as conn:
            default_project = text("(SELECT id FROM project WHERE name = 'default')")
            site_id = (
                await conn.execute(insert(Site).values(project_id=default_project, host=HOST).returning(Site.id))
            ).scalar_one()
            await conn.execute(
                insert(Capture).values(
                    id=capture_id,
                    site_id=site_id,
                    url=f"https://{HOST}/p/1",
                    fetched_at=datetime(2026, 10, 1, tzinfo=UTC),
                    method="http",
                    status_code=200,
                    final_url=f"https://{HOST}/p/1",
                    block_class="ok",
                    object_key=f"captures/2026/10/{capture_id}.bundle.zst",
                    html_sha256="0" * 64,
                    expires_at=expires_at,
                    size_bytes=1,
                    duration_ms=1,
                )
            )
        page = EvalPageRow(
            capture_id=capture_id,
            split="dev",
            schema_id=SchemaId(uuid.UUID(int=0)),
            schema_name=SCHEMA_NAME,
            page_kind="detail",
            category="mixed",
        )

        with pytest.raises(EvalNotFound):
            await store.put_page(page)
        with pytest.raises(EvalNotFound):
            await store.get_bundle(capture_id)
    finally:
        async with engine.begin() as conn:
            await conn.execute(delete(Capture).where(Capture.id == capture_id))
            await conn.execute(delete(Site).where(Site.host == HOST))
        await engine.dispose()


async def test_the_database_refuses_pages_and_runs_of_another_split(database_url: str) -> None:
    """The golden set is the one split: the CHECKs on `split` refuse any other."""
    engine = create_async_engine(database_url)
    try:
        for split in ("hidden", "fresh"):
            run = insert(EvalRun).values(split=split, engine_version="x", git_sha="a" * 40, metrics={})
            async with engine.connect() as conn:
                with pytest.raises(IntegrityError, match="ck_eval_run_split"):
                    await conn.execute(run)
            page = insert(EvalPage).values(
                capture_id=uuid7(),
                split=split,
                schema_id=uuid7(),
                schema_name=SCHEMA_NAME,
                page_kind="detail",
                category="mixed",
            )
            async with engine.connect() as conn:
                with pytest.raises(IntegrityError, match="ck_eval_page_split"):
                    await conn.execute(page)
    finally:
        await engine.dispose()
