"""`url_state` upkeep for recurring runs (SPEC-11 §4.1, ARCHITECTURE §6, §14): what a URL of a site last answered with,
read before it is fetched again and written after."""

from typing import Any

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.types import FetchResult, Validators
from crawlerai.db.models import (
    Extraction,
    ExtractionMode,
    Record,
    RecordId,
    SiteId,
    TaskRecord,
    UrlState,
    UrlTaskId,
)
from crawlerai.recurring.conditional import Unchanged, received
from crawlerai.recurring.simhash import hamming
from crawlerai.recurring.versions import latest_versions
from crawlerai.resolve.records import entity_key
from crawlerai.schemas.types import SchemaDef, document_digest

__all__ = [
    "UNCHANGED_BITS",
    "record_content",
    "record_fetch",
    "stand_for_listing",
    "standing_listing",
    "standing_record",
    "stored_validators",
]

# SPEC-11 §4.3, ARCHITECTURE §14 (owner, D-0665): only equal fingerprints are the same content. SimHash still serves
# for what it ignores structurally (nonces, whitespace); any other change, such as a new price, runs extraction.
UNCHANGED_BITS = 0

_OK = 200  # RFC 9110 §15.3.1: the response carries the page itself, and its validators describe it


async def stored_validators(conn: AsyncConnection, site_id: SiteId, canonical_url: str) -> Validators | None:
    """The validators to send with the next fetch of the URL; None when it has none stored."""
    query = select(UrlState.etag, UrlState.last_modified).where(*_url(site_id, canonical_url))
    row = (await conn.execute(query)).first()
    if row is None or (row.etag is None and row.last_modified is None):
        return None
    return Validators(etag=row.etag, last_modified=row.last_modified)


async def record_fetch(
    conn: AsyncConnection, site_id: SiteId, canonical_url: str, fetched: FetchResult | Unchanged
) -> None:
    """Record a fetch of the URL (§4.2). `Unchanged` marks it seen, keeping its validators. An `ok` 200 over HTTP from
    the URL itself stores the validators it answered with, replacing the ones before, and none where it sent none. Any
    other result leaves the state as it is: only the HTTP rung sends validators; an API response describes its
    endpoint and a redirected one another resource, not the page; and a page not fetched whole (an error, a shell)
    must not later be `unchanged`."""
    if isinstance(fetched, Unchanged):
        await conn.execute(update(UrlState).where(*_url(site_id, canonical_url)).values(last_seen_at=func.now()))
        return
    if not _stores_validators(fetched):
        return
    validators = received(fetched)
    values = {"etag": validators.etag, "last_modified": validators.last_modified, "last_seen_at": func.now()}
    await _upsert(conn, site_id, canonical_url, values)


async def standing_record(
    conn: AsyncConnection,
    site_id: SiteId,
    canonical_url: str,
    schema: SchemaDef,
    config_version: int | None,
) -> RecordId | None:
    """The record that stands for the page when it has not changed: the newest of its entity (`entity_key`) under
    `schema` that a task extracting the way it would be now (by config `config_version`, or `adhoc` for None, and
    with `schema`'s document, `record.schema_digest`) stood for since the page's content last changed
    (`record_content`); None when the page must be extracted. A task that extracted the changed content and found its
    record unchanged stands for that record too (SPEC-11 §4.4), so the next run does not extract the page again."""
    mode: ExtractionMode = "adhoc" if config_version is None else "config"
    changed = select(UrlState.last_changed_at).where(*_url(site_id, canonical_url)).scalar_subquery()
    extracted_since = (
        select(TaskRecord.record_id)
        .join(Extraction, Extraction.url_task_id == TaskRecord.url_task_id)
        .where(
            TaskRecord.record_id == Record.id,
            Extraction.mode == mode,
            Extraction.config_version.is_not_distinct_from(config_version),
            changed.is_(None) | (TaskRecord.created_at >= changed),
        )
    )
    query = (
        select(Record.id)
        .where(
            Record.site_id == site_id,
            Record.entity_key == entity_key(site_id, canonical_url),
            Record.schema_id == schema.id,
            Record.schema_digest == document_digest(schema),
            extracted_since.exists(),
        )
        .order_by(Record.id.desc())
        .limit(1)
    )
    return (await conn.execute(query)).scalar_one_or_none()


async def standing_listing(
    conn: AsyncConnection,
    site_id: SiteId,
    canonical_url: str,
    schema: SchemaDef,
    config_version: int | None,
) -> tuple[RecordId, ...]:
    """The records that stand for a listing page when it has not changed (D-1283): the latest version of each entity the
    task named by `url_state.standing_task_id` stood for, when that task extracted the page the way it would be now
    (by config `config_version`, or `adhoc` for None, with `schema`), its links are no older than the page's content
    (`record_content`), and each entity's latest version was extracted with `schema`'s document. Empty when the page
    must be extracted. A listing's rows are keyed by their URLs, so no entity of the page's own stands for it as a
    detail page's does (`standing_record`)."""
    state = select(UrlState.standing_task_id, UrlState.last_changed_at).where(*_url(site_id, canonical_url))
    row = (await conn.execute(state)).first()
    if row is None or row.standing_task_id is None:
        return ()
    mode: ExtractionMode = "adhoc" if config_version is None else "config"
    extracted = select(Extraction.id).where(
        Extraction.url_task_id == row.standing_task_id,
        Extraction.mode == mode,
        Extraction.config_version.is_not_distinct_from(config_version),
    )
    links = select(Record.entity_key, Record.schema_id, TaskRecord.created_at).join(
        TaskRecord, TaskRecord.record_id == Record.id
    )
    stood_for = (await conn.execute(links.where(TaskRecord.url_task_id == row.standing_task_id))).all()
    changed = row.last_changed_at
    unchanged_since = all(
        link.schema_id == schema.id and (changed is None or link.created_at >= changed) for link in stood_for
    )
    if not stood_for or not unchanged_since or not (await conn.execute(select(extracted.exists()))).scalar_one():
        return ()
    latest = await latest_versions(conn, site_id, schema, [link.entity_key for link in stood_for])
    digest = document_digest(schema)
    if any(version["schema_digest"] != digest for version in latest.values()):
        return ()
    return tuple(version["id"] for version in latest.values())


async def stand_for_listing(conn: AsyncConnection, site_id: SiteId, canonical_url: str, task_id: UrlTaskId) -> None:
    """Note that the task's records stand for the listing page now (`standing_listing`). Only a task that extracted the
    page may: one that found it unchanged has no extraction for `standing_listing` to check."""
    await _upsert(conn, site_id, canonical_url, {"standing_task_id": task_id}, last_seen_at=func.now())


async def record_content(conn: AsyncConnection, site_id: SiteId, canonical_url: str, fingerprint: int) -> bool:
    """Whether the page's content changed (§4.3): its fingerprint is more than `UNCHANGED_BITS` from the stored one,
    or none is stored. A change stores the new fingerprint and sets `last_changed_at`."""
    query = select(UrlState.content_fingerprint).where(*_url(site_id, canonical_url))
    stored = (await conn.execute(query)).scalar_one_or_none()
    if stored is not None and hamming(int(stored, 16), fingerprint) <= UNCHANGED_BITS:
        return False
    values = {"content_fingerprint": _hex(fingerprint), "last_changed_at": func.now()}
    await _upsert(conn, site_id, canonical_url, values, last_seen_at=func.now())
    return True


async def _upsert(
    conn: AsyncConnection, site_id: SiteId, canonical_url: str, values: dict[str, Any], **inserted: Any
) -> None:
    """Set `values` on the URL's row, inserting it (with `inserted` too) when it has none."""
    insert = pg_insert(UrlState).values(site_id=site_id, canonical_url=canonical_url, **values, **inserted)
    await conn.execute(
        insert.on_conflict_do_update(index_elements=[UrlState.site_id, UrlState.canonical_url], set_=values)
    )


def _hex(fingerprint: int) -> str:
    """The fingerprint as `url_state.content_fingerprint` stores it: 16 lower-case hex digits."""
    return f"{fingerprint:016x}"


def _stores_validators(fetched: FetchResult) -> bool:
    manifest = fetched.bundle.manifest
    is_page = manifest.final_url == manifest.url and fetched.method == "http"
    return is_page and fetched.block_class == "ok" and manifest.status_code == _OK


def _url(site_id: SiteId, canonical_url: str) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
    return (UrlState.site_id == site_id, UrlState.canonical_url == canonical_url)
