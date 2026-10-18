"""Record versions (SPEC-11 §4.4, ARCHITECTURE §14 row 3), against a real Postgres: a re-extracted entity whose
required values are unchanged adds no record row, and one whose fingerprint differs adds the next version, pointing at
the one it supersedes and naming its changed fields."""

import uuid
from typing import Any

import pytest
from pydantic import JsonValue
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.models import Extraction, Job, JobId, Project, Record, Site, SiteId
from crawlerai.db.queue import insert_claimed
from crawlerai.recurring.record_fp import record_fingerprint
from crawlerai.recurring.versions import store_records
from crawlerai.resolve.records import FieldMeta, RecordDraft, entity_key
from crawlerai.resolve.task import RecordSource, StoredRecord
from crawlerai.schemas import registry
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef, SchemaDocument

pytestmark = pytest.mark.anyio

PAGE_URL = "https://shop.example.test/p/1"
DOCUMENT = SchemaDocument(
    name="synthetic_versioned_product",
    page_kind="detail",
    fields={
        "title": FieldSpec(type=FieldType.TEXT, description="d", required=True),
        "price": FieldSpec(type=FieldType.MONEY, description="d", required=True),
        "colour": FieldSpec(type=FieldType.TEXT, description="d"),
    },
)
KETTLE: dict[str, JsonValue] = {"title": "Synthetic kettle", "price": {"amount": "19.90", "currency": "EUR"}}
CHEAPER: dict[str, JsonValue] = {**KETTLE, "price": {"amount": "17.50", "currency": "EUR"}}
META = FieldMeta(
    status="published",
    reason=None,
    evidence=None,
    confidence=None,
    calibrated=False,
    source_kind="jsonld",
    locator=None,
    derived_by=None,
)


class _Site:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def prepare(self, document: SchemaDocument = DOCUMENT) -> None:
        project = select(Project.id).where(Project.name == "default").scalar_subquery()
        self.project = project
        host = f"shop-{uuid.uuid4().hex[:12]}.example.test"
        insert_site = insert(Site).values(project_id=project, host=host).returning(Site.id)
        self.site_id: SiteId = (await self.conn.execute(insert_site)).scalar_one()
        self.schema: SchemaDef = await registry.create(self.conn, document.model_copy(update={"name": _name()}), "user")

    def draft(self, data: dict[str, JsonValue], url: str = PAGE_URL) -> RecordDraft:
        meta = dict.fromkeys(data, META)
        return RecordDraft(data=data, field_meta=meta, complete=True, entity_key=entity_key(self.site_id, url))

    async def run(self, *drafts: RecordDraft) -> tuple[StoredRecord, ...]:
        """One extraction of the page in a job of its own, as a re-run of the crawl stores it."""
        job = insert(Job).values(
            project_id=self.project, kind="scrape", request={}, schema_id=self.schema.id, engine_version="e"
        )
        job_id: JobId = (await self.conn.execute(job.returning(Job.id))).scalar_one()
        task = await insert_claimed(self.conn, job_id, PAGE_URL, PAGE_URL, self.schema.page_kind, "test-worker")
        extraction = insert(Extraction).values(url_task_id=task.id, engine_version="e", mode="adhoc")
        extraction_id = (await self.conn.execute(extraction.returning(Extraction.id))).scalar_one()
        source = RecordSource(
            extraction_id=extraction_id,
            task_id=task.id,
            job_id=job_id,
            site_id=self.site_id,
            mode="adhoc",
            page_url=PAGE_URL,
        )
        return await store_records(self.conn, self.schema, drafts, source)

    async def rows(self) -> list[dict[str, Any]]:
        columns = (
            Record.id,
            Record.version,
            Record.supersedes_record_id,
            Record.changed_fields,
            Record.fingerprint,
            Record.data,
        )
        query = select(*columns).where(Record.site_id == self.site_id).order_by(Record.id)
        return [dict(row) for row in (await self.conn.execute(query)).mappings()]


def _name() -> str:
    return f"synthetic_{uuid.uuid4().hex[:12]}"


@pytest.fixture
async def site(conn: AsyncConnection) -> _Site:
    prepared = _Site(conn)
    await prepared.prepare()
    return prepared


async def test_a_first_extraction_is_version_1_with_its_fingerprint(site: _Site) -> None:
    (stored,) = await site.run(site.draft(KETTLE))

    assert await site.rows() == [
        {
            "id": stored.id,
            "version": 1,
            "supersedes_record_id": None,
            "changed_fields": [],
            "fingerprint": record_fingerprint(KETTLE, site.schema),
            "data": KETTLE,
        }
    ]


async def test_a_changed_price_adds_version_2_naming_price(site: _Site) -> None:
    (first,) = await site.run(site.draft(KETTLE))

    (second,) = await site.run(site.draft(CHEAPER))

    assert second.id != first.id
    assert second.draft.data == CHEAPER
    assert (await site.rows())[1] == {
        "id": second.id,
        "version": 2,
        "supersedes_record_id": first.id,
        "changed_fields": ["price"],
        "fingerprint": record_fingerprint(CHEAPER, site.schema),
        "data": CHEAPER,
    }
