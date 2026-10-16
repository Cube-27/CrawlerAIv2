"""What a page task does the same way whether it runs while its caller waits (`scrape`, SPEC-07 §4.4) or in a worker
(`batch_scrape`, SPEC-10 §4.3): the request members both take, the task's site and fetch policy, its capture and the
usage its fetches count, the content formats of its page, and the outcome its extraction settles it with.

These steps write in the caller's transaction and never settle the task themselves: a scrape settles it through the
queue, a worker handler returns the result for the worker loop to settle.
"""

import logging
import math
from collections.abc import Iterable
from dataclasses import replace
from typing import Any, Final, Literal, Self, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Row, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.acquire.persist import store_capture
from crawlerai.acquire.rungs import remember_fetch_method
from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult, check_robots_override
from crawlerai.collect.schema_org_map import VocabularyMissing
from crawlerai.config_ir.active import record_page
from crawlerai.config_ir.drift import MARGINS_FILE, DriftMargins, load_margins
from crawlerai.content.html import cleaned_html
from crawlerai.content.links import links
from crawlerai.content.markdown import markdown
from crawlerai.content.metadata import PageMetadata, metadata
from crawlerai.content.page import ParsedPage
from crawlerai.core.capture import BlockClass, CaptureMethod
from crawlerai.core.engine_version import engine_data_dir
from crawlerai.core.errors import Refusal
from crawlerai.db.models import (
    CaptureId,
    FetchMethod,
    JobId,
    PageKind,
    ProgressiveState,
    Project,
    SchemaId,
    Site,
    SiteId,
    UsageResource,
)
from crawlerai.db.queue import ClaimedTask
from crawlerai.db.usage import record_usage
from crawlerai.llm.client import LLMClient
from crawlerai.llm.roles.s_schema import MAX_FIELD_NAMES, draft_fields, normalize_prompt
from crawlerai.normalize.url import canonical_url
from crawlerai.recurring.versions import store_records
from crawlerai.resolve.pipeline import EngineData
from crawlerai.resolve.task import ActiveConfig, Stored, StoredRecord, store_extraction
from crawlerai.resolve.types import ExtractionResult
from crawlerai.schemas.registry import SchemaNotFound, get_by_id
from crawlerai.schemas.types import Name, SchemaDef
from crawlerai.services import schemas
from crawlerai.services.schemas import NewSchema
from crawlerai.storage.base import ObjectStore

log = logging.getLogger(__name__)

PageFormat = Literal["markdown", "html", "raw_html", "links", "metadata", "records"]
# `url_task.outcome` as a page task reports it (SPEC-07 §4.4).
PageOutcome = Literal["extracted", "partial", "blocked", "shell", "not_found", "failed"]

BLOCK_OUTCOMES: Final[dict[BlockClass, PageOutcome]] = {
    # Without `records` the page is extracted once it is fetched; with them, its record decides (`partial`).
    "ok": "extracted",
    "blocked": "blocked",
    "shell": "shell",
    "not_found": "not_found",
    "error": "failed",
}
# The usage a fetch attempt counts (SPEC-02 §4.7, §4.8): a request per HTTP or API attempt, the seconds of a browser's.
_REQUEST_METHODS: Final[frozenset[CaptureMethod]] = frozenset({"http", "api"})
# Jobs and sites belong to the project migrations create (single tenant, ARCHITECTURE §1).
DEFAULT_PROJECT: Final = select(Project.id).where(Project.name == "default").scalar_subquery()


def load_engine_data() -> EngineData | None:
    """The engine's data files from the engine directory's `data/`, for `records` and replays; None where they are
    not there (no engine directory, or a tree without `crawlerai data fetch`): `records` and replays are then
    unavailable, and the other formats work."""
    data = engine_data_dir()
    if data is None:
        log.warning("no engine directory: records and replays are unavailable")
        return None
    try:
        return EngineData.load(data)
    except VocabularyMissing as e:
        log.warning("records and replays are unavailable: %s", e)
        return None


def load_drift_margins() -> DriftMargins | None:
    """The dev-fitted drift margins (SPEC-08 §4.9); None when none are fitted, and then no field is suspended."""
    data = engine_data_dir()
    return None if data is None else load_margins(data / MARGINS_FILE)


class Input(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def absolute_http_url(url: str) -> str:
    """`url`, for a request model's validator: `ValueError` unless it is an absolute http(s) URL."""
    if canonical_url(url, None) is None:
        raise ValueError("not an absolute http or https URL")
    return url


class SchemaById(Input):
    id: SchemaId


class SchemaInline(Input):
    inline: NewSchema


class SchemaPrompt(Input):
    prompt: str

    @field_validator("prompt")
    @classmethod
    def _not_blank(cls, prompt: str) -> str:
        # Role S reads the prompt whitespace-normalized (SPEC-06 §4.5), so one of only whitespace is empty.
        if not normalize_prompt(prompt):
            raise ValueError("the prompt is empty")
        return prompt


class SchemaFields(Input):
    """Field names, drafted into a schema with exactly those top-level fields by role S (SPEC-14 §4.10, D-0810)."""

    fields: list[Name] = Field(min_length=1, max_length=MAX_FIELD_NAMES)

    @field_validator("fields")
    @classmethod
    def _distinct(cls, fields: list[str]) -> list[str]:
        if len(set(fields)) != len(fields):
            raise ValueError("a field name is given twice")
        return fields


# How a request names its schema: by id, inline, as a prompt or as field names to draft from.
SchemaRequest = SchemaById | SchemaInline | SchemaPrompt | SchemaFields


class FetchOptions(Input):
    method_hint: Literal["auto", "http", "browser"] = "auto"
    respect_robots: bool = True
    robots_override_reason: str | None = None
    proxy_pool: str | None = None

    @model_validator(mode="after")
    def _override_has_a_reason(self) -> Self:
        check_robots_override(self.respect_robots, self.robots_override_reason)
        return self


def check_records(formats: list[PageFormat], schema: SchemaRequest | None, page_kind: PageKind | None) -> None:
    """`records` needs a schema and a `page_kind`, and the schema's page kind must be that one (SPEC-07 §4.4). Raises
    `ValueError`, for a request model's validator."""
    if "records" not in formats:
        return
    if schema is None:
        raise ValueError("the records format needs a schema")
    if page_kind is None:
        raise ValueError("the records format needs a page_kind")
    if isinstance(schema, SchemaInline) and schema.inline.page_kind != page_kind:
        raise ValueError(f"the inline schema is for {schema.inline.page_kind} pages, not {page_kind}")


class SchemaUnusable(Refusal):
    """The request's `schema` is one `records` cannot use: no such id, a retired version, or another page kind."""


async def fields_schema(engine: AsyncEngine, llm: LLMClient, fields: list[Name], page_kind: PageKind) -> SchemaDef:
    """Role S's draft of `fields` for `page_kind` pages, checked usable for them (SPEC-14 §4.10). Raises the LLM
    client's `LLMFailure`, and `SchemaUnusable` for a retired draft."""
    drafted = await draft_fields(engine, llm, fields=fields, page_kind=page_kind)
    check_usable(drafted, page_kind)
    return drafted


async def named_schema(
    engine: AsyncEngine, schema: SchemaRequest | None, page_kind: PageKind | None, llm: LLMClient
) -> SchemaDef | None:
    """The schema a request names by id, stores (or matches) inline, or drafts from field names with `llm`; None for a
    prompt, whose draft needs a page. Raises `SchemaUnusable`, the schemas service's `SchemaConflict` or
    `InvalidSchema` for an inline schema, and the LLM client's `LLMFailure` for field names it could not draft."""
    match schema:
        case SchemaFields(fields=fields):
            if page_kind is None:
                raise SchemaUnusable("field names need a page_kind to draft a schema for")
            return await fields_schema(engine, llm, fields, page_kind)
        case SchemaById(id=schema_id):
            async with engine.connect() as conn:
                try:
                    found = await get_by_id(conn, schema_id)
                except SchemaNotFound as e:
                    raise SchemaUnusable(str(e)) from e
            check_usable(found, page_kind)
            return found
        case SchemaInline(inline=inline):
            async with engine.begin() as conn:
                return await schemas.inline(conn, inline)
    return None


def check_usable(schema: SchemaDef, page_kind: PageKind | None) -> None:
    if schema.status == "retired":
        raise SchemaUnusable(f"schema {schema.name} version {schema.version} is retired")
    if schema.page_kind != page_kind:
        raise SchemaUnusable(f"schema {schema.name} is for {schema.page_kind} pages, not {page_kind}")


SiteRow = Row[SiteId, FetchMethod, str | None, str | None, int | None]


async def site_row(conn: AsyncConnection, host: str) -> SiteRow:
    """The site of `host`, created in the default project the first time one of its pages is fetched."""
    await conn.execute(
        pg_insert(Site).values(project_id=DEFAULT_PROJECT, host=host).on_conflict_do_nothing(index_elements=[Site.host])
    )
    columns = (Site.id, Site.fetch_method, Site.proxy_pool, Site.robots_snapshot, Site.crawl_delay_ms)
    return (await conn.execute(select(*columns).where(Site.host == host))).one()


def fetch_policy(
    options: FetchOptions, locale: str | None, site_pool: str | None, page_kind: PageKind | None
) -> FetchPolicy:
    return FetchPolicy(
        page_kind=page_kind,
        method_hint=options.method_hint,
        proxy_pool=options.proxy_pool or site_pool,
        respect_robots=options.respect_robots,
        robots_override_reason=options.robots_override_reason,
        locale_hint=locale,
    )


async def new_capture(conn: AsyncConnection, store: ObjectStore, site_id: SiteId, page: FetchResult) -> CaptureId:
    await remember_fetch_method(conn, site_id, page)
    return await store_capture(conn, store, page, site_id)


async def record_fetch_usage(
    conn: AsyncConnection, job_id: JobId, attempts: Iterable[AttemptRecord], proxy_pool: str | None
) -> None:
    """Count the fetch `attempts` as the job's usage. Attempts, not fetch results, so that a caller keeps no page body
    only to count it."""
    for attempt in attempts:
        resource: UsageResource
        if attempt.method in _REQUEST_METHODS:
            resource, quantity = "http_requests", 1
        else:
            resource, quantity = "browser_seconds", math.ceil(attempt.duration_ms / 1000)
        await record_usage(
            conn,
            job_id,
            resource,
            provider=None,
            model_or_pool=proxy_pool,
            quantity=quantity,
            metadata={"method": attempt.method},
        )


# The error of a reached caller-supplied page that has no record: resolution failed (SPEC-05 §4.14).
EXTRACTION_ERROR: Final = "extraction_error"


async def store_page_record(
    conn: AsyncConnection,
    task: ClaimedTask,
    extraction: ExtractionResult,
    *,
    capture_id: CaptureId,
    site_id: SiteId,
    schema: SchemaDef,
    config: ActiveConfig | None,
    margins: DriftMargins | None,
    caller_supplied: bool = True,
) -> Stored:
    """Store the extraction of a page and what it keeps: a caller-supplied page keeps its records, complete or not
    (`partial`, ARCHITECTURE §10), and a crawl-discovered one only complete records (else `no_match`, §23); none when
    resolution failed (SPEC-05 §4.14). The outcome is `failed` then, and for a caller-supplied detail page without a
    record; a caller-supplied listing without rows is `partial` with none (its page was read, and listed nothing). A
    page with a record counts toward its progressive state. A page `config` ran on joins the config's drift window
    (SPEC-08 §4.9)."""
    stored = await store_extraction(
        conn,
        task,
        extraction,
        capture_id=capture_id,
        site_id=site_id,
        schema=schema,
        caller_supplied=caller_supplied,
        write_records=store_records,
        config=config,
    )
    if config is not None:
        await record_page(conn, config, extraction, margins=margins, job_id=task.job_id)
    if stored.records:
        await _count_page(conn, site_id, schema)
    elif caller_supplied:
        listed_nothing = schema.page_kind == "listing" and stored.outcome != "failed"
        return replace(stored, outcome="partial" if listed_nothing else "failed")
    return stored


def records_outcome(records: tuple[StoredRecord, ...]) -> Literal["extracted", "partial"]:
    """A caller-supplied page's outcome: `extracted` when it kept records and every one is complete (§10)."""
    return "extracted" if records and all(record.draft.complete for record in records) else "partial"


async def _count_page(conn: AsyncConnection, site_id: SiteId, schema: SchemaDef) -> None:
    """An extracted or partial page counts toward the progressive state of its site, schema version and page kind
    (ARCHITECTURE §8.3; SPEC-08 reads it)."""
    state = ProgressiveState
    await conn.execute(
        pg_insert(state)
        .values(
            site_id=site_id,
            schema_id=schema.id,
            schema_version=schema.version,
            page_kind=schema.page_kind,
            pages_extracted=1,
        )
        .on_conflict_do_update(
            index_elements=[state.site_id, state.schema_id, state.schema_version, state.page_kind],
            set_={"pages_extracted": state.pages_extracted + 1},
        )
    )


def _absent(value: object) -> bool:
    return value is None


def _never_null(schema: dict[str, Any]) -> None:
    # A format's member is left out rather than null, so the document gives it no null branch and no default.
    (branch,) = (branch for branch in schema.pop("anyOf") if branch.get("type") != "null")
    schema.update(branch)
    del schema["default"]


def format_member(alias: str | None = None) -> Any:
    """A member of an answer that is there only when it was asked for: a format, or the draft of a prompt."""
    return Field(default=None, alias=alias, exclude_if=_absent, json_schema_extra=_never_null)


class Formats(TypedDict, total=False):
    markdown: str
    html: str
    raw_html: str
    links: list[str]
    metadata: PageMetadata


def page_formats(page: ParsedPage, final_url: str, requested: list[PageFormat]) -> Formats:
    """The requested content formats of a reached page (ARCHITECTURE §8.5), from its one parse (INV-26)."""
    formats: Formats = {}
    if "markdown" in requested:
        formats["markdown"] = markdown(page, final_url)
    if "html" in requested:
        formats["html"] = cleaned_html(page)
    if "raw_html" in requested:
        formats["raw_html"] = page.html
    if "links" in requested:
        formats["links"] = list(links(page, final_url))
    if "metadata" in requested:
        formats["metadata"] = metadata(page, final_url)
    return formats
