"""What a job's results are exported as, beyond a page of text: its records as one file, `xlsx` or
`parquet`, and its pages as `llms.txt` and `llms-full.txt`. `GET /v1/jobs/{id}/results?format=xlsx|parquet` and
`GET /v1/jobs/{id}/llms.txt` answer with these; so does the MCP `llms_txt` tool.

A file holds every record of the job, newest first, up to `MAX_RECORDS`, with its delta; the exporters write the table
the text exports do (`config_ir.exporters`). The `llms` files are made from the job's reached pages, one per final URL,
in task order, from their captures: the title and description of a page, and for the full file its Markdown. They cover
at most `MAX_PAGES` (`llms.txt`) or `MAX_FULL_PAGES` (`llms-full.txt`) pages.
"""

import asyncio
from collections.abc import Sequence
from typing import Final, NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from snowcrawl.config_ir.exporters.files import MEDIA_TYPES, FileFormat, export_file
from snowcrawl.content.llms import LlmsPage, llms_full_txt, llms_txt
from snowcrawl.content.markdown import markdown
from snowcrawl.content.metadata import metadata
from snowcrawl.content.page import ParsedPage
from snowcrawl.db.models import Capture, Job, JobId, RecordId, UrlTask
from snowcrawl.resolve.records import Delta, RecordContent
from snowcrawl.schemas import registry
from snowcrawl.services.jobs import JobNotFound, NotExportable, record_content
from snowcrawl.services.records import MAX_PAGE, RecordFilter, list_records
from snowcrawl.storage.base import ObjectNotFound, ObjectStore
from snowcrawl.storage.capture_bundle import decode

MAX_RECORDS: Final = 100_000
MAX_PAGES: Final = 5000  # as many as a map returns (`services.map.MAX_LIMIT`)
MAX_FULL_PAGES: Final = 1000


class ExportFile(NamedTuple):
    """A file made of a job's records: its bytes, media type and a name to save it under."""

    data: bytes
    media_type: str
    filename: str


async def export_job_file(conn: AsyncConnection, job_id: JobId, fmt: FileFormat) -> ExportFile:
    """All the job's records as a file in `fmt`. Raises `JobNotFound`, `NotExportable` for a job without a schema, and
    the exporters' `FormatUnavailable` for `parquet` without pyarrow."""
    schema_id = (await conn.execute(select(Job.schema_id).where(Job.id == job_id))).one_or_none()
    if schema_id is None:
        raise JobNotFound(f"no job {job_id}")
    if schema_id[0] is None:
        raise NotExportable(f"job {job_id} has no schema, so it has no records to export")
    schema = await registry.get_by_id(conn, schema_id[0])
    contents: list[RecordContent] = []
    deltas: list[Delta | None] = []
    cursor: RecordId | None = None
    while len(contents) < MAX_RECORDS:
        page = await list_records(conn, RecordFilter(job_id=job_id, cursor=cursor, limit=MAX_PAGE), counted=False)
        contents += [record_content(record) for record in page.items]
        deltas += [record.delta for record in page.items]
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    data = await asyncio.to_thread(export_file, fmt, schema, contents[:MAX_RECORDS], deltas[:MAX_RECORDS])
    return ExportFile(data, MEDIA_TYPES[fmt], f"job-{job_id}.{fmt}")


class _Reached(NamedTuple):
    url: str
    object_key: str


async def job_llms_txt(conn: AsyncConnection, store: ObjectStore, job_id: JobId, *, full: bool) -> str:
    """The job's `llms.txt`, or its `llms-full.txt` with `full`. Raises `JobNotFound`, and `NotExportable` for a job
    that reached no page or keeps none of their captures."""
    if (await conn.execute(select(Job.id).where(Job.id == job_id))).one_or_none() is None:
        raise JobNotFound(f"no job {job_id}")
    limit = MAX_FULL_PAGES if full else MAX_PAGES
    reached = await _reached(conn, job_id, limit)
    if not reached:
        raise NotExportable(f"job {job_id} has reached no page, so it has nothing to list")
    made = await asyncio.to_thread(_made, store, reached, full)
    if not made:
        # Retention deleted every bundle the rows named (`scheduler.retention.expire_captures`).
        raise NotExportable(f"job {job_id} keeps no capture of a page it reached, so it has nothing to list")
    pages = [page for page, _ in made]
    return llms_full_txt(pages, [text for _, text in made]) if full else llms_txt(pages)


async def _reached(conn: AsyncConnection, job_id: JobId, limit: int) -> list[_Reached]:
    """The pages the job reached, one per final URL, in task order: the capture's own URL and bundle."""
    rows = await conn.execute(
        select(Capture.final_url, Capture.object_key)
        .join(UrlTask, UrlTask.capture_id == Capture.id)
        .where(UrlTask.job_id == job_id, Capture.block_class == "ok", Capture.method != "api")
        .order_by(UrlTask.id)
    )
    seen: dict[str, _Reached] = {}
    for url, key in rows:
        seen.setdefault(url, _Reached(url, key))
    return list(seen.values())[:limit]


def _made(store: ObjectStore, reached: Sequence[_Reached], full: bool) -> list[tuple[LlmsPage, str]]:
    made: list[tuple[LlmsPage, str]] = []
    for page_ref in reached:
        try:
            bundle = decode(store.get(page_ref.object_key))
        except ObjectNotFound:
            continue  # the capture expired
        page = ParsedPage.of(bundle)
        found = metadata(page, bundle.manifest.final_url)
        text = markdown(page, bundle.manifest.final_url) if full else ""
        made.append((LlmsPage(page_ref.url, found.title, found.description), text))
    return made
