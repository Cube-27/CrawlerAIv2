"""Record versions (SPEC-11 §4.4, ARCHITECTURE §14 row 3), against a real Postgres: a re-extracted entity whose
required values are unchanged adds no record row, and one whose fingerprint differs adds the next version, pointing at
the one it supersedes and naming its changed fields."""

import uuid
from typing import Any

import pytest
from pydantic import JsonValue
from sqlalchemy import insert, select, update
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
LISTING = SchemaDocument(
    name="synthetic_versioned_listing",
    page_kind="listing",
    fields={
        "title": FieldSpec(type=FieldType.TEXT, description="d", required=True),
        "price": FieldSpec(type=FieldType.MONEY, description="d", required=True),
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


async def test_an_unchanged_entity_adds_no_row_and_answers_with_the_stored_record(site: _Site) -> None:
    (first,) = await site.run(site.draft(KETTLE))

    (again,) = await site.run(site.draft(KETTLE))

    assert again.id == first.id
    assert again.draft == first.draft
    assert [row["id"] for row in await site.rows()] == [first.id]


async def test_a_change_outside_the_required_fields_adds_no_row(site: _Site) -> None:
    (first,) = await site.run(site.draft(KETTLE))

    (again,) = await site.run(site.draft({**KETTLE, "colour": "red"}))

    assert again.id == first.id
    assert again.draft.data == KETTLE
    assert len(await site.rows()) == 1


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


async def test_versions_follow_the_latest_record_not_the_first(site: _Site) -> None:
    await site.run(site.draft(KETTLE))
    (second,) = await site.run(site.draft(CHEAPER))

    (third,) = await site.run(site.draft(KETTLE))

    rows = await site.rows()
    assert [(row["version"], row["supersedes_record_id"]) for row in rows[1:]] == [(2, rows[0]["id"]), (3, second.id)]
    assert rows[2]["id"] == third.id
    assert rows[2]["changed_fields"] == ["price"]


async def test_a_record_stored_without_a_fingerprint_is_superseded(site: _Site, conn: AsyncConnection) -> None:
    (first,) = await site.run(site.draft(KETTLE))
    await conn.execute(update(Record).where(Record.id == first.id).values(fingerprint=None))

    (second,) = await site.run(site.draft(KETTLE))

    assert second.id != first.id
    assert [(row["version"], row["changed_fields"]) for row in await site.rows()] == [(1, []), (2, [])]


async def test_listing_rows_version_one_by_one_in_their_order(conn: AsyncConnection) -> None:
    site = _Site(conn)
    await site.prepare(LISTING)
    first_url, second_url = f"{PAGE_URL}#1", f"{PAGE_URL}#2"
    before = await site.run(site.draft(KETTLE, first_url), site.draft(KETTLE, second_url))

    after = await site.run(site.draft(KETTLE, first_url), site.draft(CHEAPER, second_url))

    assert after[0].id == before[0].id
    assert after[1].id != before[1].id
    assert [row["version"] for row in await site.rows()] == [1, 1, 2]
