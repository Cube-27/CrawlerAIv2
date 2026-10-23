"""The extraction step of a page task: the extraction, its candidates and
the page's record, as resolution decided them."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.acquire.persist import store_capture
from crawlerai.acquire.types import AttemptRecord, FetchResult
from crawlerai.collect.vocabulary import Vocabulary
from crawlerai.config_ir.role_c import role_c
from crawlerai.core.capture import BlockClass
from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.core.ids import uuid7
from crawlerai.db.models import Candidate, Extraction, Job, JobId, Project, Record, Site, SiteId, SourceKind, UsageEvent
from crawlerai.db.queue import ClaimedTask, insert_claimed
from crawlerai.llm.client import MeteredClient, ProviderReply
from crawlerai.recurring.versions import store_records
from crawlerai.resolve.pipeline import EngineData, RoleC, extract_page
from crawlerai.resolve.preference import PRECEDENCE_TYPES
from crawlerai.resolve.records import entity_key
from crawlerai.resolve.task import Stored, store_extraction
from crawlerai.schemas import registry
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef, SchemaDocument
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex
from crawlerai.storage.fs import FsStore
from tests.support.fake_llm import FakeProvider

pytestmark = pytest.mark.anyio

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")
DATA = EngineData(vocabulary=VOCABULARY, orders=dict.fromkeys(PRECEDENCE_TYPES, ORDER), calibration=None)
PAGE_URL = "https://shop.example.test/p/1"
DOCUMENT = SchemaDocument(
    name="synthetic_product",
    page_kind="detail",
    fields={
        "title": FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name"),
        "price": FieldSpec(
            type=FieldType.MONEY, description="d", required=True, schema_org="Offer.price+priceCurrency"
        ),
    },
)


def _product(name: str, url: str, *, offers: bool = True) -> dict[str, Any]:
    node: dict[str, Any] = {"@context": "https://schema.org", "@type": "Product", "name": name, "url": url}
    if offers:
        node["offers"] = {"@type": "Offer", "price": "19.90", "priceCurrency": "EUR"}
    return node


def _page(*nodes: dict[str, Any], body: str = "") -> str:
    scripts = "".join(f'<script type="application/ld+json">{json.dumps(node)}</script>' for node in nodes)
    return f"<html><head>{scripts}</head><body>{body}</body></html>"


class _Setup:
    def __init__(self, conn: AsyncConnection, tmp_path: Path) -> None:
        self.conn = conn
        self.store = FsStore(tmp_path)

    async def prepare(
        self, document: SchemaDocument, job_id: JobId | None = None
    ) -> tuple[SiteId, SchemaDef, ClaimedTask]:
        project = select(Project.id).where(Project.name == "default").scalar_subquery()
        site_id: SiteId = (
            await self.conn.execute(
                insert(Site).values(project_id=project, host="shop.example.test").returning(Site.id)
            )
        ).scalar_one()
        schema = await registry.create(self.conn, document, "user")
        if job_id is None:
            job_id = (
                await self.conn.execute(
                    insert(Job)
                    .values(project_id=project, kind="scrape", request={}, schema_id=schema.id, engine_version="e")
                    .returning(Job.id)
                )
            ).scalar_one()
        task = await insert_claimed(self.conn, job_id, PAGE_URL, PAGE_URL, document.page_kind, "test-worker")
        return site_id, schema, task

    async def run(
        self,
        body: str,
        *,
        document: SchemaDocument = DOCUMENT,
        block_class: BlockClass = "ok",
        caller_supplied: bool = True,
        role_c: RoleC | None = None,
        job_id: JobId | None = None,
    ) -> Stored:
        site_id, schema, task = await self.prepare(document, job_id)
        raw = body.encode()
        manifest = CaptureManifest(
            capture_id=uuid7(),
            url=PAGE_URL,
            final_url=PAGE_URL,
            fetched_at=datetime(2026, 10, 1, tzinfo=UTC),
            method="http",
            status_code=200,
            block_class=block_class,
            headers=Headers(request=(), response=(("Content-Type", "text/html"),)),
            timings_ms={},
            html_sha256=sha256_hex(raw),
            network_bodies=(),
            fetch_policy={},
            engine_version="0+cal.0",
        )
        bundle = CaptureBundle(manifest=manifest, body=raw, network=())
        attempt = AttemptRecord(method="http", status=200, block_class=block_class, duration_ms=1)
        fetched = FetchResult(bundle=bundle, duration_ms=1, attempts=(attempt,))
        capture_id = await store_capture(self.conn, self.store, fetched, site_id)
        self.site_id, self.schema = site_id, schema
        result = await extract_page(bundle, schema, None, role_c, data=DATA)
        return await store_extraction(
            self.conn,
            task,
            result,
            capture_id=capture_id,
            site_id=site_id,
            schema=schema,
            caller_supplied=caller_supplied,
            write_records=store_records,
        )

    async def candidates(self, stored: Stored) -> list[tuple[Any, ...]]:
        rows = await self.conn.execute(
            select(
                Candidate.field,
                Candidate.source_kind,
                Candidate.normalize_status,
                Candidate.chosen,
                Candidate.reject_reason,
            )
            .where(Candidate.extraction_id == stored.extraction_id)
            .order_by(Candidate.field, Candidate.entity_ref)
        )
        return [tuple(row) for row in rows]


@pytest.fixture
def setup(conn: AsyncConnection, tmp_path: Path) -> _Setup:
    return _Setup(conn, tmp_path)


async def test_a_complete_page_stores_its_extraction_candidates_and_record(setup: _Setup) -> None:
    stored = await setup.run(_page(_product("Widget One", PAGE_URL)))

    assert stored.outcome == "extracted"
    extraction = (
        await setup.conn.execute(select(Extraction.__table__).where(Extraction.id == stored.extraction_id))
    ).one()
    assert (extraction.mode, extraction.llm_calls, extraction.config_version, extraction.engine_version) == (
        "adhoc",
        0,
        None,
        ENGINE_VERSION,
    )
    assert await setup.candidates(stored) == [
        ("price", "jsonld", "ok", True, None),
        ("title", "jsonld", "ok", True, None),
    ]
    record = (await setup.conn.execute(select(Record.__table__).where(Record.id == stored.records[0].id))).one()
    assert record.data == {"title": "Widget One", "price": {"amount": "19.90", "currency": "EUR"}}
    assert record.complete is True
    assert (record.entity_key, record.schema_id, record.mode) == (
        entity_key(setup.site_id, PAGE_URL),
        setup.schema.id,
        "adhoc",
    )
    assert record.field_meta["title"] == {
        "status": "published",
        "reason": None,
        "evidence": "structured",
        "confidence": None,
        "calibrated": False,
        "source_kind": "jsonld",
        "locator": "jsonld:0:$['name']",
        "derived_by": None,
    }


async def test_role_c_runs_inside_the_task_without_waiting_on_its_transaction(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    # The client commits usage on its own connection; the step writes nothing before role C's call, so the
    # call's usage commits while the task's transaction is open, and stays when that transaction rolls back.
    project = select(Project.id).where(Project.name == "default").scalar_subquery()
    async with engine.begin() as committed:
        job_id: JobId = (
            await committed.execute(
                insert(Job).values(project_id=project, kind="scrape", request={}, engine_version="e").returning(Job.id)
            )
        ).scalar_one()
    price = {"shown": True, "ref": "", "value": "19.90 EUR", "start": 11, "end": 20}
    answer = json.dumps({"fields": {"price": price}})
    provider = FakeProvider([ProviderReply(model="fake-fast", text=answer, tokens_in=7, tokens_out=3)])
    client = MeteredClient([provider], engine)
    async with engine.connect() as conn:
        transaction = await conn.begin()
        setup = _Setup(conn, tmp_path)
        page = _page(_product("Widget One", PAGE_URL, offers=False), body="<h1>Widget One</h1><p>19.90 EUR</p>")
        with anyio.fail_after(30):
            stored = await setup.run(
                page,
                role_c=role_c(client, job_id=job_id),
                job_id=job_id,
            )
        assert await setup.candidates(stored) == [
            ("price", "llm", "ok", True, None),
            ("title", "jsonld", "ok", True, None),
        ]
        await transaction.rollback()
    async with engine.connect() as conn:
        usage = (await conn.execute(select(UsageEvent.resource).where(UsageEvent.job_id == job_id))).scalars().all()
    assert sorted(usage) == ["llm_calls", "llm_tokens_in", "llm_tokens_out"]
