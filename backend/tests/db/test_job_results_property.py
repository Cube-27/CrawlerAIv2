"""INV-27 at the results endpoint (SPEC-10 §6): for generated records stored under a job, the values that
`GET /v1/jobs/{id}/results` answers, as JSON and in each export format, equal the stored `record` values.

The comparison is with the values read back from `record`, so it holds whatever JSONB keeps of a generated value.
Each example runs in its own event loop and engine, and deletes what it stored.
"""

import asyncio
import csv
import io
import json
import uuid
from pathlib import Path
from typing import Any, get_args

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import JsonValue
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from crawlerai.config_ir.exporters.records import RecordFormat, export_records
from crawlerai.core.ids import uuid7
from crawlerai.db.models import Extraction, Job, JobId, Project, Record, SchemaDef, Site, UrlTask
from crawlerai.resolve.records import FieldMeta, RecordContent
from crawlerai.schemas import registry
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDocument
from crawlerai.schemas.types import SchemaDef as Schema
from crawlerai.services import jobs
from crawlerai.services.jobs import ExportPage, ResultsQuery
from crawlerai.services.records import MAX_PAGE, RecordPage, StoredRecord
from crawlerai.storage.fs import FsStore

FIELDS = ("alpha", "beta", "gamma")
# Records are read from the database; a job with a schema never reads a capture.
NO_STORE = FsStore(Path("unused"))
# PostgreSQL's jsonb holds no U+0000 (PostgreSQL docs, "JSON Types").
_text = st.text(st.characters(codec="utf-8", exclude_characters="\x00"), max_size=8)
_scalars = st.booleans() | st.integers(-(2**53), 2**53) | st.floats(allow_nan=False, allow_infinity=False) | _text
_values: st.SearchStrategy[JsonValue] = st.recursive(
    _scalars, lambda inner: st.lists(inner, max_size=3) | st.dictionaries(_text, inner, max_size=3), max_leaves=6
)
_records = st.lists(st.dictionaries(st.sampled_from(FIELDS), _values), min_size=1, max_size=4)


def _metas(data: dict[str, JsonValue]) -> dict[str, FieldMeta]:
    return {name: FieldMeta.model_validate(_meta(name in data)) for name in FIELDS}


def _meta(published: bool) -> dict[str, Any]:
    return {
        "status": "published" if published else "missing",
        "reason": None if published else "no candidate",
        "evidence": "structured" if published else None,
        "confidence": None,
        "calibrated": False,
        "source_kind": "jsonld" if published else None,
        "locator": "jsonld:0:$.name" if published else None,
        "derived_by": None,
    }


async def _store(conn: AsyncConnection, schema: Schema, records: list[dict[str, JsonValue]]) -> JobId:
    project = select(Project.id).where(Project.name == "default").scalar_subquery()
    host = f"shop-{uuid7().hex[-12:]}.example.test"
    site_id = (await conn.execute(insert(Site).values(project_id=project, host=host).returning(Site.id))).scalar_one()
    job = insert(Job).values(
        project_id=project, kind="batch_scrape", request={}, engine_version="e", schema_id=schema.id
    )
    job_id: JobId = (await conn.execute(job.returning(Job.id))).scalar_one()
    for data in records:
        url = f"https://{host}/p/{uuid7().hex}"
        task = insert(UrlTask).values(job_id=job_id, url=url, canonical_url=url, status="done", outcome="partial")
        task_id = (await conn.execute(task.returning(UrlTask.id))).scalar_one()
        extraction = insert(Extraction).values(url_task_id=task_id, engine_version="e", mode="adhoc")
        extraction_id = (await conn.execute(extraction.returning(Extraction.id))).scalar_one()
        field_meta = {name: meta.model_dump() for name, meta in _metas(data).items()}
        values = {"data": data, "field_meta": field_meta, "complete": False, "mode": "adhoc", "entity_key": url}
        values |= {"schema_id": schema.id, "schema_version": schema.version}
        await conn.execute(insert(Record).values(extraction_id=extraction_id, job_id=job_id, site_id=site_id, **values))
    return job_id


async def _delete(conn: AsyncConnection, job_id: JobId, schema_name: str) -> None:
    sites = select(Record.site_id).where(Record.job_id == job_id).scalar_subquery()
    site_ids = (await conn.execute(select(Site.id).where(Site.id.in_(sites)))).scalars().all()
    tasks = select(UrlTask.id).where(UrlTask.job_id == job_id).scalar_subquery()
    await conn.execute(delete(Record).where(Record.job_id == job_id))
    await conn.execute(delete(Extraction).where(Extraction.url_task_id.in_(tasks)))
    await conn.execute(delete(UrlTask).where(UrlTask.job_id == job_id))
    await conn.execute(delete(Job).where(Job.id == job_id))
    await conn.execute(delete(Site).where(Site.id.in_(site_ids)))
    await conn.execute(delete(SchemaDef).where(SchemaDef.name == schema_name))


async def _records_page(conn: AsyncConnection, job_id: JobId) -> RecordPage:
    page = await jobs.job_results(conn, job_id, ResultsQuery(limit=MAX_PAGE), store=NO_STORE)
    assert isinstance(page, RecordPage)
    return page


async def _export(conn: AsyncConnection, job_id: JobId, fmt: RecordFormat) -> str:
    page = await jobs.job_results(conn, job_id, ResultsQuery(format=fmt, limit=MAX_PAGE), store=NO_STORE)
    assert isinstance(page, ExportPage)
    return page.content


def _cell(value: JsonValue) -> str:
    """The exporters' cell text (SPEC-08 §4.11): nothing for no value, a string as itself, else JSON."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _published(record: StoredRecord) -> dict[str, JsonValue]:
    return {name: field.value for name, field in record.fields.items() if field.value is not None}


def _without_nulls(row: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {name: row[name] for name in FIELDS if row[name] is not None}


def _csv_values(content: str) -> list[dict[str, str]]:
    return [{name: row[name] for name in FIELDS} for row in csv.DictReader(io.StringIO(content, newline=""))]


async def _compare(engine: AsyncEngine, schema: Schema, job_id: JobId) -> None:
    async with engine.connect() as conn:
        stored_rows = await conn.execute(select(Record.id, Record.data).where(Record.job_id == job_id))
        stored = {row.id: row.data for row in stored_rows}
        as_json = await _records_page(conn, job_id)
        exports = {fmt: await _export(conn, job_id, fmt) for fmt in get_args(RecordFormat)}
    assert {record.id: _published(record) for record in as_json.items} == stored
    # Exports carry no record id; rows come in the order of the JSON page.
    expected = [stored[record.id] for record in as_json.items]
    assert [_without_nulls(row) for row in json.loads(exports["json_records"])] == expected
    assert _csv_values(exports["csv_records"]) == [{n: _cell(data.get(n)) for n in FIELDS} for data in expected]
    # Markdown escapes its cells (SPEC-08 §4.11); the exporter's own properties cover that, so here it is fed the
    # stored values unchanged.
    contents = [RecordContent(data=data, field_meta=_metas(data), complete=False) for data in expected]
    assert exports["markdown"] == export_records("markdown", schema, contents)


async def _check(database_url: str, records: list[dict[str, JsonValue]]) -> None:
    engine = create_async_engine(database_url)
    name = f"synthetic_{uuid.uuid4().hex[:12]}"
    text = FieldSpec(type=FieldType.TEXT, description="d")
    document = SchemaDocument(name=name, version=1, page_kind="detail", fields=dict.fromkeys(FIELDS, text))
    async with engine.begin() as conn:
        schema = await registry.create(conn, document, "user")
        job_id = await _store(conn, schema, records)
    try:
        await _compare(engine, schema, job_id)
    finally:
        async with engine.begin() as conn:
            await _delete(conn, job_id, name)
        await engine.dispose()


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(records=_records)
def test_results_answer_the_stored_values_unchanged(database_url: str, records: list[dict[str, JsonValue]]) -> None:
    asyncio.run(_check(database_url, records))
