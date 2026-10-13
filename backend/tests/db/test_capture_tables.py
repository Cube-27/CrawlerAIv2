import uuid
from datetime import UTC, datetime
from typing import Any, get_args

import pytest
from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.core.capture import BlockClass, CaptureMethod
from crawlerai.db.models import (
    Candidate,
    Capture,
    CaptureId,
    ConfigOrigin,
    Extraction,
    ExtractionConfig,
    ExtractionId,
    Job,
    JobId,
    NormalizeStatus,
    ProgressiveMode,
    ProgressiveState,
    Project,
    Record,
    SchemaDef,
    SchemaId,
    Site,
    SiteId,
    SourceKind,
    UrlState,
    UrlTask,
    UrlTaskId,
)

pytestmark = pytest.mark.anyio

MISSING_ID = uuid.UUID("00000000-0000-7000-8000-000000000000")
FETCHED_AT = datetime(2026, 10, 1, tzinfo=UTC)
SHA256 = "0" * 64


async def _site(conn: AsyncConnection, host: str = "example.test") -> SiteId:
    default_project = select(Project.id).where(Project.name == "default").scalar_subquery()
    site_id: SiteId = (
        await conn.execute(insert(Site).values(project_id=default_project, host=host).returning(Site.id))
    ).scalar_one()
    return site_id


async def _schema(conn: AsyncConnection, version: int = 1) -> SchemaId:
    values = {"name": "s", "version": version, "page_kind": "detail", "fields": {}, "origin": "user"}
    schema_id: SchemaId = (
        await conn.execute(insert(SchemaDef).values(**values, status="active").returning(SchemaDef.id))
    ).scalar_one()
    return schema_id


async def _task(conn: AsyncConnection) -> UrlTaskId:
    default_project = select(Project.id).where(Project.name == "default").scalar_subquery()
    job_id: JobId = (
        await conn.execute(
            insert(Job)
            .values(project_id=default_project, kind="scrape", request={}, engine_version="0+cal.0")
            .returning(Job.id)
        )
    ).scalar_one()
    url = "https://example.test/p/1"
    task_id: UrlTaskId = (
        await conn.execute(insert(UrlTask).values(job_id=job_id, url=url, canonical_url=url).returning(UrlTask.id))
    ).scalar_one()
    return task_id


async def _capture(conn: AsyncConnection, site_id: SiteId, /, **columns: Any) -> CaptureId:
    url = "https://example.test/p/1"
    values = {
        "site_id": site_id,
        "url": url,
        "fetched_at": FETCHED_AT,
        "method": "http",
        "status_code": 200,
        "final_url": url,
        "block_class": "ok",
        "object_key": f"captures/2026/10/{uuid.uuid4()}.bundle.zst",
        "html_sha256": SHA256,
        "size_bytes": 10,
        "duration_ms": 5,
    }
    capture_id: CaptureId = (
        await conn.execute(insert(Capture).values(**{**values, **columns}).returning(Capture.id))
    ).scalar_one()
    return capture_id


async def _extraction(conn: AsyncConnection, **columns: Any) -> ExtractionId:
    values = {"url_task_id": await _task(conn), "engine_version": "0+cal.0", "mode": "adhoc", **columns}
    extraction_id: ExtractionId = (
        await conn.execute(insert(Extraction).values(**values).returning(Extraction.id))
    ).scalar_one()
    return extraction_id


def _candidate_values(extraction_id: ExtractionId, /, **columns: Any) -> dict[str, Any]:
    values = {
        "extraction_id": extraction_id,
        "entity_ref": "page",
        "field": "title",
        "raw_value": "A title",
        "normalized_value": "A title",
        "normalize_status": "ok",
        "source_kind": "jsonld",
        "independent": True,
        "locator": "jsonld:0:$.name",
    }
    return {**values, **columns}


def _progressive_values(site_id: SiteId, schema_id: SchemaId, /, **columns: Any) -> dict[str, Any]:
    return {"site_id": site_id, "schema_id": schema_id, "schema_version": 1, "page_kind": "detail", **columns}


def _config_values(site_id: SiteId, schema_id: SchemaId, /, **columns: Any) -> dict[str, Any]:
    values = {
        "site_id": site_id,
        "schema_id": schema_id,
        "schema_version": 1,
        "page_kind": "detail",
        "version": 1,
        "ir": {},
        "origin": "induced",
    }
    return {**values, **columns}


async def _record_values(conn: AsyncConnection, **columns: Any) -> dict[str, Any]:
    extraction_id = await _extraction(conn)
    job_id = (await conn.execute(select(Job.id))).scalar_one()
    values = {
        "extraction_id": extraction_id,
        "job_id": job_id,
        "site_id": await _site(conn),
        "schema_id": await _schema(conn),
        "schema_version": 1,
        "entity_key": SHA256,
        "data": {"title": "A title"},
        "field_meta": {"title": {"status": "published"}},
        "complete": True,
        "mode": "adhoc",
    }
    return {**values, **columns}


async def test_new_capture_tables_have_the_indexes_their_queries_need(conn: AsyncConnection) -> None:
    rows = await conn.execute(
        text(
            "SELECT indexname FROM pg_indexes WHERE tablename IN ('capture', 'extraction', 'candidate', 'record',"
            " 'url_state', 'progressive_state', 'extraction_config') OR indexname = 'ix_url_task_capture_id'"
        )
    )

    assert set(rows.scalars()) == {
        "pk_capture",
        "uq_capture_object_key",
        "ix_capture_expires_at",
        "ix_capture_site_id_fetched_at",
        "ix_url_task_capture_id",
        "pk_extraction",
        "ix_extraction_capture_id",
        "pk_candidate",
        "ix_candidate_extraction_id",
        "ix_candidate_created_at",
        "pk_record",
        "ix_record_extraction_id",
        "ix_record_job_id_id",
        "ix_record_schema_id_id",
        "ix_record_site_id_entity_key_schema_id",
        "pk_url_state",
        "pk_progressive_state",
        "pk_extraction_config",
        "uq_extraction_config_site_id_schema_id_page_kind_version",
        "uq_extraction_config_active",
    }


async def test_new_capture_tables_name_their_checks_once(conn: AsyncConnection) -> None:
    rows = await conn.execute(
        text(
            "SELECT conname FROM pg_constraint WHERE contype = 'c' AND conrelid::regclass::text IN ('capture',"
            " 'extraction', 'candidate', 'record', 'url_state', 'progressive_state', 'extraction_config')"
        )
    )

    assert set(rows.scalars()) == {
        "ck_capture_method",
        "ck_capture_block_class",
        "ck_capture_size_bytes_non_negative",
        "ck_capture_duration_ms_non_negative",
        "ck_extraction_mode",
        "ck_extraction_llm_calls_non_negative",
        "ck_candidate_normalize_status",
        "ck_candidate_source_kind",
        "ck_record_mode",
        "ck_record_version_positive",
        "ck_url_state_missing_runs_non_negative",
        "ck_progressive_state_page_kind",
        "ck_progressive_state_mode",
        "ck_progressive_state_pages_extracted_non_negative",
        "ck_extraction_config_version_positive",
        "ck_extraction_config_page_kind",
        "ck_extraction_config_status",
        "ck_extraction_config_origin",
    }


async def test_the_expiry_index_leaves_out_captures_that_never_expire(conn: AsyncConnection) -> None:
    definition: str = (
        await conn.execute(text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_capture_expires_at'"))
    ).scalar_one()

    assert definition.endswith("WHERE (expires_at IS NOT NULL)")


async def test_a_new_capture_never_expires_and_has_an_empty_fetch_policy(conn: AsyncConnection) -> None:
    capture_id = await _capture(conn, await _site(conn))

    row = (await conn.execute(select(Capture).where(Capture.id == capture_id))).one()

    assert (row.fetch_policy, row.expires_at, row.id.version) == ({}, None, 7)


async def test_capture_accepts_every_method_and_block_class(conn: AsyncConnection) -> None:
    site_id = await _site(conn)
    for method in get_args(CaptureMethod):
        await _capture(conn, site_id, method=method)
    for block_class in get_args(BlockClass):
        await _capture(conn, site_id, block_class=block_class)

    rows = (await conn.execute(select(Capture.method, Capture.block_class))).all()

    assert {row.method for row in rows} == set(get_args(CaptureMethod))
    assert {row.block_class for row in rows} == set(get_args(BlockClass))


@pytest.mark.parametrize(
    ("columns", "constraint"),
    [
        ({"method": "ftp"}, "ck_capture_method"),
        ({"block_class": "captcha"}, "ck_capture_block_class"),
        ({"size_bytes": -1}, "ck_capture_size_bytes_non_negative"),
        ({"duration_ms": -1}, "ck_capture_duration_ms_non_negative"),
        ({"site_id": MISSING_ID}, "fk_capture_site_id_site"),
    ],
)
async def test_capture_rejects_values_outside_its_domain(
    conn: AsyncConnection, columns: dict[str, Any], constraint: str
) -> None:
    site_id = await _site(conn)

    with pytest.raises(IntegrityError, match=constraint):
        await _capture(conn, site_id, **columns)


async def test_two_captures_cannot_share_an_object_key(conn: AsyncConnection) -> None:
    site_id = await _site(conn)
    await _capture(conn, site_id, object_key="captures/2026/10/a.bundle.zst")

    with pytest.raises(IntegrityError, match="uq_capture_object_key"):
        await _capture(conn, site_id, object_key="captures/2026/10/a.bundle.zst")


async def test_deleting_an_expired_capture_keeps_its_task_and_extraction(conn: AsyncConnection) -> None:
    capture_id = await _capture(conn, await _site(conn))
    extraction_id = await _extraction(conn, capture_id=capture_id)
    await conn.execute(update(UrlTask).values(capture_id=capture_id))

    await conn.execute(delete(Capture).where(Capture.id == capture_id))

    assert (await conn.execute(select(UrlTask.capture_id))).scalar_one() is None
    assert (await conn.execute(select(Extraction.id, Extraction.capture_id))).one() == (extraction_id, None)


async def test_task_capture_must_exist(conn: AsyncConnection) -> None:
    await _task(conn)

    statement = update(UrlTask).values(capture_id=MISSING_ID)
    with pytest.raises(IntegrityError, match="fk_url_task_capture_id_capture"):
        await conn.execute(statement)


async def test_a_new_extraction_has_no_llm_calls_and_no_config(conn: AsyncConnection) -> None:
    extraction_id = await _extraction(conn)

    row = (await conn.execute(select(Extraction).where(Extraction.id == extraction_id))).one()

    assert (row.llm_calls, row.config_version, row.capture_id, row.mode) == (0, None, None, "adhoc")


@pytest.mark.parametrize(
    ("columns", "constraint"),
    [
        ({"mode": "learned"}, "ck_extraction_mode"),
        ({"llm_calls": -1}, "ck_extraction_llm_calls_non_negative"),
        ({"capture_id": MISSING_ID}, "fk_extraction_capture_id_capture"),
        ({"url_task_id": MISSING_ID}, "fk_extraction_url_task_id_url_task"),
    ],
)
async def test_extraction_rejects_values_outside_its_domain(
    conn: AsyncConnection, columns: dict[str, Any], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        await _extraction(conn, **columns)


async def test_a_new_candidate_is_not_chosen_and_has_a_utc_creation_time(conn: AsyncConnection) -> None:
    await conn.execute(insert(Candidate).values(**_candidate_values(await _extraction(conn))))

    row = (await conn.execute(select(Candidate))).one()

    assert (row.chosen, row.reject_reason) == (False, None)
    assert row.created_at.utcoffset().total_seconds() == 0


async def test_candidate_accepts_every_source_kind_and_normalize_status(conn: AsyncConnection) -> None:
    extraction_id = await _extraction(conn)
    rows = [_candidate_values(extraction_id, source_kind=kind) for kind in get_args(SourceKind)]
    rows += [_candidate_values(extraction_id, normalize_status=status) for status in get_args(NormalizeStatus)]

    await conn.execute(insert(Candidate), rows)

    stored = (await conn.execute(select(Candidate.source_kind, Candidate.normalize_status))).all()
    assert {row.source_kind for row in stored} == set(get_args(SourceKind))
    assert {row.normalize_status for row in stored} == set(get_args(NormalizeStatus))


async def test_candidate_keeps_structured_raw_values_and_a_missing_normalized_value(conn: AsyncConnection) -> None:
    raw = {"price": "12.50", "priceCurrency": "EUR", "list": [1, None]}
    values = _candidate_values(
        await _extraction(conn), raw_value=raw, normalized_value=None, normalize_status="invalid"
    )

    await conn.execute(insert(Candidate).values(**values))

    assert (await conn.execute(select(Candidate.raw_value, Candidate.normalized_value))).one() == (raw, None)


@pytest.mark.parametrize(
    ("columns", "constraint"),
    [
        ({"source_kind": "css"}, "ck_candidate_source_kind"),
        ({"normalize_status": "guessed"}, "ck_candidate_normalize_status"),
        ({"extraction_id": MISSING_ID}, "fk_candidate_extraction_id_extraction"),
    ],
)
async def test_candidate_rejects_values_outside_its_domain(
    conn: AsyncConnection, columns: dict[str, Any], constraint: str
) -> None:
    values = _candidate_values(await _extraction(conn), **columns)

    statement = insert(Candidate).values(**values)
    with pytest.raises(IntegrityError, match=constraint):
        await conn.execute(statement)


async def test_a_new_record_is_version_1_with_no_changed_fields(conn: AsyncConnection) -> None:
    await conn.execute(insert(Record).values(**await _record_values(conn)))

    row = (await conn.execute(select(Record))).one()

    assert (row.version, row.changed_fields, row.supersedes_record_id, row.fingerprint) == (1, [], None, None)
    assert row.id.version == 7


async def test_a_record_version_points_at_the_record_it_supersedes(conn: AsyncConnection) -> None:
    values = await _record_values(conn)
    first = (await conn.execute(insert(Record).values(**values).returning(Record.id))).scalar_one()

    second = (
        await conn.execute(
            insert(Record)
            .values(**values, version=2, changed_fields=["title"], supersedes_record_id=first)
            .returning(Record.id)
        )
    ).scalar_one()

    row = (await conn.execute(select(Record).where(Record.id == second))).one()
    assert (row.version, row.changed_fields, row.supersedes_record_id) == (2, ["title"], first)


@pytest.mark.parametrize(
    ("columns", "constraint"),
    [
        ({"mode": "learned"}, "ck_record_mode"),
        ({"version": 0}, "ck_record_version_positive"),
        ({"schema_version": 2}, "fk_record_schema_id_schema_def"),
        ({"supersedes_record_id": MISSING_ID}, "fk_record_supersedes_record_id_record"),
        ({"extraction_id": MISSING_ID}, "fk_record_extraction_id_extraction"),
        ({"job_id": MISSING_ID}, "fk_record_job_id_job"),
        ({"site_id": MISSING_ID}, "fk_record_site_id_site"),
    ],
)
async def test_record_rejects_values_outside_its_domain(
    conn: AsyncConnection, columns: dict[str, Any], constraint: str
) -> None:
    values = await _record_values(conn)

    statement = insert(Record).values(**{**values, **columns})
    with pytest.raises(IntegrityError, match=constraint):
        await conn.execute(statement)


async def test_a_new_url_state_has_no_missing_runs_and_is_not_gone(conn: AsyncConnection) -> None:
    site_id = await _site(conn)
    url = "https://example.test/p/1"

    await conn.execute(insert(UrlState).values(site_id=site_id, canonical_url=url, last_seen_at=FETCHED_AT))

    row = (await conn.execute(select(UrlState))).one()
    assert (row.missing_runs, row.gone_at, row.etag, row.last_modified, row.content_fingerprint) == (
        0,
        None,
        None,
        None,
        None,
    )


async def test_url_state_holds_one_row_per_site_and_canonical_url(conn: AsyncConnection) -> None:
    url = "https://example.test/p/1"
    first, second = await _site(conn, "a.example.test"), await _site(conn, "b.example.test")
    await conn.execute(insert(UrlState).values(site_id=first, canonical_url=url, last_seen_at=FETCHED_AT))
    await conn.execute(insert(UrlState).values(site_id=second, canonical_url=url, last_seen_at=FETCHED_AT))

    statement = insert(UrlState).values(site_id=first, canonical_url=url, last_seen_at=FETCHED_AT)
    with pytest.raises(IntegrityError, match="pk_url_state"):
        await conn.execute(statement)


async def test_url_state_rejects_negative_missing_runs(conn: AsyncConnection) -> None:
    values = {"site_id": await _site(conn), "canonical_url": "https://example.test/", "last_seen_at": FETCHED_AT}

    statement = insert(UrlState).values(**values, missing_runs=-1)
    with pytest.raises(IntegrityError, match="ck_url_state_missing_runs_non_negative"):
        await conn.execute(statement)


@pytest.mark.parametrize("mode", get_args(ProgressiveMode))
async def test_progressive_state_accepts_every_mode(conn: AsyncConnection, mode: str) -> None:
    values = _progressive_values(await _site(conn), await _schema(conn), mode=mode)

    await conn.execute(insert(ProgressiveState).values(**values))

    assert (await conn.execute(select(ProgressiveState.mode))).scalar_one() == mode


async def test_a_new_progressive_state_starts_cold_with_no_pages(conn: AsyncConnection) -> None:
    await conn.execute(insert(ProgressiveState).values(**_progressive_values(await _site(conn), await _schema(conn))))

    assert (await conn.execute(select(ProgressiveState.mode, ProgressiveState.pages_extracted))).one() == ("cold", 0)


async def test_progressive_state_is_one_row_per_site_schema_version_and_page_kind(conn: AsyncConnection) -> None:
    site_id = await _site(conn)
    v1, v2 = await _schema(conn, version=1), await _schema(conn, version=2)
    await conn.execute(insert(ProgressiveState).values(**_progressive_values(site_id, v1)))
    await conn.execute(insert(ProgressiveState).values(**_progressive_values(site_id, v1, page_kind="listing")))
    await conn.execute(insert(ProgressiveState).values(**_progressive_values(site_id, v2, schema_version=2)))

    statement = insert(ProgressiveState).values(**_progressive_values(site_id, v1))
    with pytest.raises(IntegrityError, match="pk_progressive_state"):
        await conn.execute(statement)


@pytest.mark.parametrize(
    ("columns", "constraint"),
    [
        ({"mode": "warm"}, "ck_progressive_state_mode"),
        ({"page_kind": "index"}, "ck_progressive_state_page_kind"),
        ({"pages_extracted": -1}, "ck_progressive_state_pages_extracted_non_negative"),
        ({"schema_version": 2}, "fk_progressive_state_schema_id_schema_def"),
        ({"site_id": MISSING_ID}, "fk_progressive_state_site_id_site"),
    ],
)
async def test_progressive_state_rejects_values_outside_its_domain(
    conn: AsyncConnection, columns: dict[str, Any], constraint: str
) -> None:
    values = _progressive_values(await _site(conn), await _schema(conn), **columns)

    statement = insert(ProgressiveState).values(**values)
    with pytest.raises(IntegrityError, match=constraint):
        await conn.execute(statement)


@pytest.mark.parametrize("origin", get_args(ConfigOrigin))
async def test_a_new_config_is_a_draft_with_no_field_status(conn: AsyncConnection, origin: str) -> None:
    values = _config_values(await _site(conn), await _schema(conn), origin=origin)

    await conn.execute(insert(ExtractionConfig).values(**values))

    row = (await conn.execute(select(ExtractionConfig))).one()
    assert (row.status, row.origin, row.field_status, row.validation_report) == ("draft", origin, {}, None)


async def test_a_site_has_one_active_config_per_schema_and_page_kind(conn: AsyncConnection) -> None:
    site_id, schema_id = await _site(conn), await _schema(conn)
    await conn.execute(insert(ExtractionConfig).values(**_config_values(site_id, schema_id, status="active")))
    await conn.execute(insert(ExtractionConfig).values(**_config_values(site_id, schema_id, version=2)))
    await conn.execute(
        insert(ExtractionConfig).values(**_config_values(site_id, schema_id, version=3, status="suspended"))
    )
    await conn.execute(
        insert(ExtractionConfig).values(**_config_values(site_id, schema_id, page_kind="listing", status="active"))
    )

    statement = insert(ExtractionConfig).values(**_config_values(site_id, schema_id, version=4, status="active"))
    with pytest.raises(IntegrityError, match="uq_extraction_config_active"):
        await conn.execute(statement)


async def test_activating_a_new_config_after_suspending_the_old_one_succeeds(conn: AsyncConnection) -> None:
    site_id, schema_id = await _site(conn), await _schema(conn)
    old = (
        await conn.execute(
            insert(ExtractionConfig)
            .values(**_config_values(site_id, schema_id, status="active"))
            .returning(ExtractionConfig.id)
        )
    ).scalar_one()
    new = (
        await conn.execute(
            insert(ExtractionConfig)
            .values(**_config_values(site_id, schema_id, version=2))
            .returning(ExtractionConfig.id)
        )
    ).scalar_one()

    await conn.execute(update(ExtractionConfig).where(ExtractionConfig.id == old).values(status="suspended"))
    await conn.execute(update(ExtractionConfig).where(ExtractionConfig.id == new).values(status="active"))

    active = (await conn.execute(select(ExtractionConfig.id).where(ExtractionConfig.status == "active"))).scalars()
    assert list(active) == [new]


@pytest.mark.parametrize(
    ("columns", "constraint"),
    [
        ({"status": "retired"}, "ck_extraction_config_status"),
        ({"origin": "manual"}, "ck_extraction_config_origin"),
        ({"page_kind": "index"}, "ck_extraction_config_page_kind"),
        ({"version": 0}, "ck_extraction_config_version_positive"),
        ({"schema_version": 2}, "fk_extraction_config_schema_id_schema_def"),
        ({"site_id": MISSING_ID}, "fk_extraction_config_site_id_site"),
    ],
)
async def test_config_rejects_values_outside_its_domain(
    conn: AsyncConnection, columns: dict[str, Any], constraint: str
) -> None:
    values = _config_values(await _site(conn), await _schema(conn), **columns)

    statement = insert(ExtractionConfig).values(**values)
    with pytest.raises(IntegrityError, match=constraint):
        await conn.execute(statement)


async def test_config_versions_are_unique_per_site_schema_and_page_kind(conn: AsyncConnection) -> None:
    site_id, schema_id = await _site(conn), await _schema(conn)
    await conn.execute(insert(ExtractionConfig).values(**_config_values(site_id, schema_id)))

    statement = insert(ExtractionConfig).values(**_config_values(site_id, schema_id))
    with pytest.raises(IntegrityError, match="uq_extraction_config_site_id_schema_id_page_kind_version"):
        await conn.execute(statement)
