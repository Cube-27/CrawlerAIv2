"""What a page task does the same way whether it runs while its caller waits (`scrape`, rest-api spec) or in a worker
(`batch_scrape`, jobs spec): the request members both take, the task's site and fetch policy, its capture and the
usage its fetches count, the content formats of its page, and the outcome its extraction settles it with.

These steps write in the caller's transaction and never settle the task themselves: a scrape settles it through the
queue, a worker handler returns the result for the worker loop to settle.
"""

import logging
import math
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field, replace
from typing import Any, Final, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.acquire.challenge import LEGAL, vendor_block
from crawlerai.acquire.memory import Coverage, Remembered, learn_extraction, learn_fetch, remembered
from crawlerai.acquire.persist import store_capture
from crawlerai.acquire.rungs import NO_PLAN, FetchPlan
from crawlerai.acquire.types import AttemptRecord, FetchResult, fetched_as
from crawlerai.collect.run import Adapters
from crawlerai.collect.schema_org_map import VocabularyMissing
from crawlerai.config_ir.active import fetch_plan, record_page
from crawlerai.config_ir.drift import MARGINS_FILE, DriftMargins, load_margins
from crawlerai.config_ir.locate import Extract
from crawlerai.config_ir.progressive import LocateRequest, StateKey, render_mode, request_locate, set_render_mode
from crawlerai.config_ir.role_c import role_c
from crawlerai.content.chunks import Chunk, ChunkOptions, chunks
from crawlerai.content.fit import FitOptions, markdown_fit
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
    JobId,
    PageKind,
    ProgressiveState,
    Project,
    RenderMode,
    SchemaId,
    Site,
    SiteId,
    UsageResource,
)
from crawlerai.db.queue import ClaimedTask
from crawlerai.db.usage import record_usage
from crawlerai.llm.client import LLMClient
from crawlerai.llm.roles.s_labels import with_labels
from crawlerai.llm.roles.s_schema import MAX_FIELD_NAMES, draft_fields, normalize_prompt
from crawlerai.normalize.url import canonical_url
from crawlerai.normalize.url_key import canonicalize
from crawlerai.recurring.versions import store_records
from crawlerai.resolve.pipeline import EngineData, RoleC, extract_page
from crawlerai.resolve.task import ActiveConfig, Stored, StoredRecord, store_extraction
from crawlerai.resolve.types import ExtractionResult
from crawlerai.schemas.registry import SchemaNotFound, get_by_id
from crawlerai.schemas.types import Name, SchemaDef
from crawlerai.services import schemas
from crawlerai.services.fetch_options import CAPTURE_FORMATS as CAPTURE_FORMATS
from crawlerai.services.fetch_options import FetchOptions as FetchOptions
from crawlerai.services.fetch_options import fetch_policy as fetch_policy
from crawlerai.services.schemas import NewSchema
from crawlerai.storage.artifacts import PDF, SCREENSHOT, Artifact, artifact_of
from crawlerai.storage.base import ObjectStore
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest

log = logging.getLogger(__name__)

PageFormat = Literal[
    "markdown", "markdown_fit", "chunks", "html", "raw_html", "links", "metadata", "screenshot", "pdf", "records"
]
# The formats that are files the browser makes of the rendered page (`storage.artifacts`).


# `url_task.outcome` as a page task reports it (rest-api spec).
class FetchSummary(BaseModel):
    """The fetch of the page: the method, status and class of the kept attempt, the platform adapter that read an `api`
    capture (INV-39; null for any other), and every attempt made."""

    method: CaptureMethod
    status_code: int | None  # None when no response arrived
    block_class: BlockClass
    adapter: str | None
    attempts: tuple[AttemptRecord, ...]


def fetch_summary(
    method: CaptureMethod,
    status_code: int | None,
    block_class: BlockClass,
    attempts: Iterable[AttemptRecord],
    *,
    adapters: Adapters | None,
    url: str,
    final_url: str,
) -> FetchSummary:
    """The summary of the fetch of `url`, whose kept attempt ended at `final_url`. An `api` capture names the active
    adapter that reads it, as the collectors do (`Registry.reader`); an API recipe's has none, and none is named
    without `adapters`."""
    found = adapters.reader(url, final_url) if method == "api" and adapters is not None else None
    return FetchSummary(
        method=method,
        status_code=status_code,
        block_class=block_class,
        adapter=None if found is None else found[0].name,
        attempts=tuple(attempts),
    )


# The outcomes of a page the fetch reached.
ReachedOutcome = Literal[
    "extracted",
    "partial",
    "blocked",
    "shell",
    "not_found",
    "auth_wall",
    "soft_404",
    "geo_redirect",
    "redirected_to_listing",
    "unsupported_media",
    "geo_blocked",
]
# The outcome a page task reports (rest-api spec): a reached page's, or its fetch's failure (`FetchFailure`).
PageOutcome = Literal[ReachedOutcome, "timeout", "failed"]

# The outcome of each block class but `error`, which is a fetch failure (`fetch_failure`).
BLOCK_OUTCOMES: Final[dict[BlockClass, ReachedOutcome]] = {
    # Without `records` the page is extracted once it is fetched; with them, its record decides (`partial`).
    "ok": "extracted",
    "blocked": "blocked",
    "shell": "shell",
    "not_found": "not_found",
    "auth_wall": "auth_wall",
    "soft_404": "soft_404",
    "geo_redirect": "geo_redirect",
    "redirected_to_listing": "redirected_to_listing",
    "unsupported_media": "unsupported_media",
}


def reached_outcome(result: FetchResult) -> ReachedOutcome:
    """The outcome of a page the fetch reached, from its block class (`BLOCK_OUTCOMES`), except that a `blocked` page
    whose kept attempt is labelled `LEGAL` (a 451, RFC 7725) is `geo_blocked`: withheld where the request came from."""
    outcome = BLOCK_OUTCOMES[result.block_class]
    kept = next((a for a in reversed(result.attempts) if a.method == result.method), None)
    return "geo_blocked" if outcome == "blocked" and kept is not None and kept.challenge == LEGAL else outcome


# The `AttemptRecord.error` of a rung that got no answer within its deadline (acquisition spec, "Error outcomes and
# reasons").
TIMEOUT: Final = "timeout"


# The outcomes of a fetch that got no page for want of an answer (`fetch_failure`).
FetchFailure = Literal["failed", "timeout"]


def fetch_failure(result: FetchResult) -> FetchFailure | None:
    """How the fetch failed, from the kept attempt alone (rest-api spec, one outcome model): `timeout` when its rung
    got no answer within its deadline, `failed` for any other error, None when the fetch got an answer."""
    if result.bundle.manifest.block_class != "error":
        return None
    return "timeout" if result.attempts[-1].error == TIMEOUT else "failed"


# The reason a page a vendor's challenge kept from being reached ends `blocked` with (`challenge.vendor_block`).
CHALLENGE_REASON: Final = "challenge: {vendor}"


def blocked_reason(result: FetchResult) -> str | None:
    """Why the fetched page ended `blocked`, when a vendor's challenge says (`CHALLENGE_REASON`); else None."""
    vendor = vendor_block(result)
    return None if vendor is None else CHALLENGE_REASON.format(vendor=vendor)


# The usage a fetch attempt counts (acquisition spec): a request per HTTP or API attempt, the seconds of a browser's.
_REQUEST_METHODS: Final[frozenset[CaptureMethod]] = frozenset({"http", "api"})
# Jobs and sites belong to the project migrations create (single tenant).
DEFAULT_PROJECT: Final = select(Project.id).where(Project.name == "default").scalar_subquery()


def load_engine_data(adapters: Adapters) -> EngineData | None:
    """The engine's data files from the engine directory's `data/`, with the process's active `adapters` to read their
    captures, for `records` and replays; None where they are not there (no engine directory, or a tree without
    `crawlerai data fetch`): `records` and replays are then unavailable, and the other formats work."""
    data = engine_data_dir()
    if data is None:
        log.warning("no engine directory: records and replays are unavailable")
        return None
    try:
        return EngineData.load(data, adapters)
    except VocabularyMissing as e:
        log.warning("records and replays are unavailable: %s", e)
        return None


def load_drift_margins() -> DriftMargins | None:
    """The dev-fitted drift margins (learning-configs spec); None when none are fitted, and then no field is
    suspended."""
    data = engine_data_dir()
    return None if data is None else load_margins(data / MARGINS_FILE)


class Input(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# The description of the `min_confidence` member of the requests that extract `records` (resolution spec, "Evidence and
# confidence"): a field whose calibrated bucket is below it is left unpublished, else every value publishes.
MIN_CONFIDENCE_DESCRIPTION: Final = (
    "Leave unpublished (abstained) a records field whose calibrated confidence is below this. "
    "Unset: every value publishes with its confidence."
)
# The description of the `render` member of the requests that extract `records` (rest-api spec, "Render mode"): HTTP by
# default; the caller asks the system to find where fields live (`locate`) or to render every page (`always`).
RENDER_DESCRIPTION: Final = (
    "How pages are rendered for fields. `off` (default): HTTP, the browser only when HTTP is refused; a field the HTTP "
    "page does not carry is `missing`. `locate`: find where the fields the HTTP pages leave missing (or `fields`) are "
    "shown, then fetch each page as they need. `always`: render every page."
)
MAX_RENDER_FIELDS: Final = 50


class RenderOptions(Input):
    """The `render` member (rest-api spec, "Render mode"): its mode, and the schema fields `locate` looks for (else the
    fields the HTTP extraction left missing). Pinned with the request (INV-28)."""

    mode: RenderMode = "off"
    fields: list[Name] = Field(default_factory=list, max_length=MAX_RENDER_FIELDS)


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
        # Role S reads the prompt whitespace-normalized (llm spec), so one of only whitespace is empty.
        if not normalize_prompt(prompt):
            raise ValueError("the prompt is empty")
        return prompt


class SchemaFields(Input):
    """Field names, drafted into a schema with exactly those top-level fields by role S (frontend spec, D-0810)."""

    fields: list[Name] = Field(min_length=1, max_length=MAX_FIELD_NAMES)

    @field_validator("fields")
    @classmethod
    def _distinct(cls, fields: list[str]) -> list[str]:
        if len(set(fields)) != len(fields):
            raise ValueError("a field name is given twice")
        return fields


# How a request names its schema: by id, inline, as a prompt or as field names to draft from.
SchemaRequest = SchemaById | SchemaInline | SchemaPrompt | SchemaFields


def check_formats(
    formats: list[PageFormat], fetch: FetchOptions, fit: FitOptions | None, chunking: ChunkOptions | None
) -> None:
    """The options a request's formats take. Raises `ValueError`, for a request model's validator: a screenshot or PDF
    is made in the browser, so `method_hint` cannot be `http`; `fit` and `chunking` are the options of `markdown_fit`
    and `chunks`."""
    if CAPTURE_FORMATS.intersection(formats) and fetch.method_hint == "http":
        raise ValueError("screenshot and pdf are made in the browser, so method_hint cannot be http")
    if CAPTURE_FORMATS.intersection(formats) and fetch.headers:
        raise ValueError("headers are sent over HTTP only (INV-44), so they cannot go with screenshot or pdf")
    if fit is not None and "markdown_fit" not in formats:
        raise ValueError("fit is the option of the markdown_fit format")
    if chunking is not None and "chunks" not in formats:
        raise ValueError("chunking is the option of the chunks format")


def check_records(formats: list[PageFormat], schema: SchemaRequest | None, page_kind: PageKind | None) -> None:
    """`records` needs a schema and a `page_kind`, and the schema's page kind must be that one (rest-api spec). Raises
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
    """Role S's draft of `fields` for `page_kind` pages, checked usable for them (frontend spec). Raises the LLM
    client's `LLMFailure`, and `SchemaUnusable` for a retired draft."""
    drafted = await draft_fields(engine, llm, fields=fields, page_kind=page_kind)
    check_usable(drafted, page_kind)
    return drafted


async def named_schema(
    engine: AsyncEngine, schema: SchemaRequest | None, page_kind: PageKind | None, llm: LLMClient
) -> SchemaDef | None:
    """The schema a request names by id, stores (or matches) inline, or drafts from field names with `llm`, with its
    label synonyms (`s_labels.with_labels`); None for a prompt, whose draft needs a page. Raises `SchemaUnusable`, the
    schemas service's `SchemaConflict` or `InvalidSchema` for an inline schema, and the LLM client's `LLMFailure` for
    field names it could not draft."""
    found = await _stated_schema(engine, schema, page_kind, llm)
    return None if found is None else await with_labels(engine, llm, found)


async def _stated_schema(
    engine: AsyncEngine, schema: SchemaRequest | None, page_kind: PageKind | None, llm: LLMClient
) -> SchemaDef | None:
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


def stored_request(request: BaseModel, context: dict[str, object] | None = None) -> dict[str, Any]:
    """`request` as a job row stores it; a `render` member the caller left out is left out, so the job inherits the
    surface's render mode (rest-api spec, "Render mode")."""
    stored: dict[str, Any] = request.model_dump(mode="json", by_alias=True, context=context)
    if "render" in type(request).model_fields and "render" not in request.model_fields_set:
        stored.pop("render", None)
    return stored


def check_render(render: RenderOptions, schema: SchemaDef | None) -> None:
    """`SchemaUnusable` when `render.fields` names a field the request's schema does not have (rest-api spec, "Render
    mode"): no locate run fills it. Without a resolved schema (a prompt, drafted on the page), none is checked."""
    if schema is None:
        return
    unknown = [name for name in render.fields if name not in schema.fields]
    if unknown:
        raise SchemaUnusable(f"render.fields names fields schema {schema.name} lacks: {', '.join(unknown)}")


def check_usable(schema: SchemaDef, page_kind: PageKind | None) -> None:
    if schema.status == "retired":
        raise SchemaUnusable(f"schema {schema.name} is retired")
    if schema.page_kind != page_kind:
        raise SchemaUnusable(f"schema {schema.name} is for {schema.page_kind} pages, not {page_kind}")


@dataclass(frozen=True, slots=True)
class SiteRow:
    """A site as a fetch reads it: its id, what its memory says of the page kind fetched (`acquire.memory`), its proxy
    pool, robots.txt snapshot and interval setting, the adapters that declined its host (`Registry.for_host`), and
    whether the browser loads all its resources."""

    id: SiteId
    remembered: Remembered
    proxy_pool: str | None
    robots_snapshot: str | None
    crawl_delay_ms: int | None
    adapter_declined: dict[str, str] = field(default_factory=dict)
    load_all_resources: bool = False


async def site_row(conn: AsyncConnection, host: str, page_kind: PageKind | None = None) -> SiteRow:
    """The site of `host`, created in the default project the first time one of its pages is fetched, with what its
    memory says of its pages of `page_kind` (`acquire.memory.remembered`)."""
    await conn.execute(
        pg_insert(Site).values(project_id=DEFAULT_PROJECT, host=host).on_conflict_do_nothing(index_elements=[Site.host])
    )
    columns = (
        Site.id,
        Site.proxy_pool,
        Site.robots_snapshot,
        Site.crawl_delay_ms,
        Site.adapter_declined,
        Site.load_all_resources,
    )
    row = (await conn.execute(select(*columns).where(Site.host == host))).one()
    return SiteRow(
        row.id,
        await remembered(conn, row.id, page_kind),
        row.proxy_pool,
        row.robots_snapshot,
        row.crawl_delay_ms,
        row.adapter_declined,
        row.load_all_resources,
    )


async def new_capture(conn: AsyncConnection, store: ObjectStore, site_id: SiteId, page: FetchResult) -> CaptureId:
    """Store the fetched page's capture, and remember on its site what the fetch learned
    (`acquire.memory.learn_fetch`)."""
    await learn_fetch(conn, site_id, page)
    return await store_capture(conn, store, page, site_id)


async def record_fetch_usage(
    conn: AsyncConnection, job_id: JobId, attempts: Iterable[AttemptRecord], proxy_pool: str | None
) -> None:
    """Count the fetch `attempts` as the job's usage: a request or the browser's seconds per attempt, and, for a fetch
    through `proxy_pool`, the bytes each attempt moved through it (`proxy_bytes`, D-1381). Attempts, not fetch results,
    so that a caller keeps no page body only to count it."""
    for attempt in attempts:
        resource: UsageResource
        if attempt.method in _REQUEST_METHODS:
            resource, quantity = "http_requests", 1
        else:
            resource, quantity = "browser_seconds", math.ceil(attempt.duration_ms / 1000)
        metadata = {"method": attempt.method}
        await record_usage(
            conn, job_id, resource, provider=None, model_or_pool=proxy_pool, quantity=quantity, metadata=metadata
        )
        if proxy_pool is not None and attempt.transferred:
            await record_usage(
                conn,
                job_id,
                "proxy_bytes",
                provider=None,
                model_or_pool=proxy_pool,
                quantity=attempt.transferred,
                metadata=metadata,
            )


# The error of a reached caller-supplied page that has no record: resolution failed (extraction spec).
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
    page_url: str | None = None,
    render: RenderOptions | None = None,
) -> Stored:
    """Store the extraction of a page and what it keeps: a caller-supplied page keeps its records, complete or not
    (`partial`), and a crawl-discovered one only complete records (else `no_match`, §23); none when resolution failed
    (extraction spec). The outcome is `failed` then; a caller-supplied detail page that states no entity of the schema
    is `no_match` (`resolve.records.states_entity`); a caller-supplied listing without rows is `partial` with none (its
    page was read, and listed nothing). A page with a record, or a caller-supplied listing that listed nothing, counts
    toward its progressive state (an `extracted` or `partial` page: a locate run renders it) and applies the job's
    `render` (None: the job inherits the surface's) to its surface (`render_surface`): a listing's rows the HTTP page
    does not carry are for a locate run to find, as any field's are. A page with a record freshens the site's contract
    with its coverage; a caller-supplied page without one counts towards its staleness
    (`acquire.memory.learn_extraction`). A page `config` ran on joins the config's drift window (learning-configs spec).
    `page_url` is `store_extraction`'s."""
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
        page_url=page_url,
    )
    if config is not None:
        await record_page(conn, config, extraction, margins=margins, job_id=task.job_id)
    if stored.records:
        await learn_extraction(conn, site_id, schema.page_kind, coverage(schema, extraction))
        await _count_page(conn, site_id, schema)
        await render_surface(conn, task.job_id, site_id, schema, render, extraction)
    elif caller_supplied:
        # A caller-supplied page is of the schema's kind by the caller's word, so no record is a quality failure; a
        # crawl-discovered page may be of no kind the schema reads.
        await learn_extraction(conn, site_id, schema.page_kind, None)
        # A listing read whole that held no row; one whose rows state no item is `no_match` as a detail page is.
        read = stored.outcome != "failed" and extraction.entity is not None
        listed_nothing = schema.page_kind == "listing" and read and not extraction.rows
        if listed_nothing:
            await _count_page(conn, site_id, schema)
            await render_surface(conn, task.job_id, site_id, schema, render, extraction)
            return replace(stored, outcome="partial")
        # A page that states no entity of the schema (resolution spec, "Incomplete pages") is `no_match`; one whose
        # resolution failed, `failed`.
        return stored if stored.outcome == "no_match" else replace(stored, outcome="failed")
    return stored


# A listing's further page (a kept state of its browser actions, or a page its recipe served), its extraction, and the
# site's active config as it ran on it.
Further = tuple[FetchResult, ExtractionResult, ActiveConfig | None]


@dataclass(frozen=True)
class StoredFurther:
    """A listing's further pages as stored: each record with the extraction it came from, and whether any page's
    extraction failed."""

    records: tuple[tuple[StoredRecord, ExtractionResult], ...] = ()
    failed: bool = False


async def extract_further(
    pages: Iterable[FetchResult],
    schema: SchemaDef,
    config: ActiveConfig | None,
    data: EngineData,
    gap_fill: RoleC | None,
) -> list[Further]:
    """The extraction of each further page of a listing that was reached, with the first page's schema, each with the
    site's config for its own capture."""
    extracted: list[Further] = []
    for page in pages:
        if page.block_class != "ok":
            continue
        own = None if config is None else config.for_capture(page.bundle.manifest, data.adapters)
        executor = None if own is None else own.executor
        parsed = ParsedPage.of(page.bundle)
        extraction = await extract_page(page.bundle, schema, executor, gap_fill, data=data, parsed=parsed)
        extracted.append((page, extraction, own))
    return extracted


async def store_further(
    conn: AsyncConnection,
    store: ObjectStore,
    task: ClaimedTask,
    site_id: SiteId,
    schema: SchemaDef,
    extracted: Iterable[Further],
    margins: DriftMargins | None,
    *,
    caller_supplied: bool = True,
) -> StoredFurther:
    """Store each further page: its capture, its extraction and its records, under the listing's task, each under the
    canonical URL of the document it read (a row without its own URL is keyed by its page and position)."""
    records: list[tuple[StoredRecord, ExtractionResult]] = []
    failed = False
    for page, extraction, config in extracted:
        capture_id = await new_capture(conn, store, site_id, page)
        kept = await store_page_record(
            conn,
            task,
            extraction,
            capture_id=capture_id,
            site_id=site_id,
            schema=schema,
            config=config,
            margins=margins,
            caller_supplied=caller_supplied,
            page_url=canonicalize(page.bundle.manifest.final_url),
        )
        failed = failed or kept.outcome == "failed"
        records.extend((record, extraction) for record in kept.records)
    return StoredFurther(tuple(records), failed)


def coverage(schema: SchemaDef, extraction: ExtractionResult) -> Coverage:
    """The schema's fields an extraction published, on its entity or on any of its rows, and those it did not."""
    sets = (extraction.entity or {}, *extraction.rows)
    found = {name for fields in sets for name, outcome in fields.items() if outcome.status == "published"}
    return {"found": sorted(found & schema.fields.keys()), "missing": sorted(schema.fields.keys() - found)}


def records_outcome(records: tuple[StoredRecord, ...]) -> Literal["extracted", "partial"]:
    """A caller-supplied page's outcome: `extracted` when it kept records and every one is complete (§10)."""
    return "extracted" if records and all(record.draft.complete for record in records) else "partial"


async def surface_plan(
    conn: AsyncConnection,
    site_id: SiteId,
    schema: SchemaDef | None,
    config: ActiveConfig | None,
    render: RenderOptions | None,
) -> FetchPlan:
    """How a page of the surface is fetched (acquisition spec, "Fetch plan"): by its `config`'s field sources, in the
    job's `render` mode, else the surface's (rest-api spec, "Render mode"). A page read for no schema has no plan."""
    if schema is None:
        return NO_PLAN
    key = StateKey(site_id, schema.id, schema.page_kind)
    return fetch_plan(config, render.mode if render is not None else await render_mode(conn, key))


async def render_surface(
    conn: AsyncConnection,
    job_id: JobId,
    site_id: SiteId,
    schema: SchemaDef,
    render: RenderOptions | None,
    extraction: ExtractionResult,
) -> RenderMode:
    """Apply a job's `render` to its surface (rest-api spec, "Render mode"), and return the mode its pages are fetched
    by: the job's mode is stored as the surface's, and a job without one inherits it. In `locate` or `always` the
    surface's locate run is started once per job (`request_locate`), for the job's `render.fields`, else the fields
    `extraction` left unpublished (`always` locates even when none is: the sources of every field the config does not
    read, so the surface can fall back to HTTP)."""
    key = StateKey(site_id, schema.id, schema.page_kind)
    if render is not None:
        await set_render_mode(conn, key, render.mode)
    mode = render.mode if render is not None else await render_mode(conn, key)
    fields = list(render.fields) if render is not None and render.fields else unpublished(extraction, schema)
    if mode == "always" or (mode == "locate" and fields):
        await request_locate(conn, key, LocateRequest(job_id=job_id, fields=fields))
    return mode


def learning_extract(data: EngineData, llm: LLMClient) -> Extract:
    """A locate run's extraction of a render (learning-configs spec, "Locate run" step 2): the page's pipeline, cold,
    with role C on `llm` charged to the run's job."""

    async def extract(bundle: CaptureBundle, schema: SchemaDef, job_id: JobId) -> ExtractionResult:
        return await extract_page(bundle, schema, None, role_c(llm, job_id=job_id), data=data)

    return extract


def unpublished(extraction: ExtractionResult, schema: SchemaDef) -> list[str]:
    """The fields `extraction` publishes no value of: the entity's, and a listing's row fields no row publishes (each
    of `schema`'s row fields when it has no row)."""
    entity = extraction.entity or {}
    names = [name for name, outcome in entity.items() if outcome.status != "published"]
    rows = [row for row in extraction.rows]
    row_names = {name for row in rows for name in row} or {
        name for name, spec in schema.fields.items() if spec.scope == "row"
    }
    names += sorted(n for n in row_names if all(row.get(n) is None or row[n].status != "published" for row in rows))
    return names


async def _count_page(conn: AsyncConnection, site_id: SiteId, schema: SchemaDef) -> None:
    """An extracted or partial page counts toward the progressive state of its site, schema and page kind
    (learning-configs spec reads it)."""
    state = ProgressiveState
    await conn.execute(
        pg_insert(state)
        .values(
            site_id=site_id,
            schema_id=schema.id,
            page_kind=schema.page_kind,
            pages_extracted=1,
        )
        .on_conflict_do_update(
            index_elements=[state.site_id, state.schema_id, state.page_kind],
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
    markdown_fit: str
    chunks: list[Chunk]
    html: str
    raw_html: str
    links: list[str]
    metadata: PageMetadata
    screenshot: Artifact
    pdf: Artifact


class FormatOptions(Input):
    """The options of the formats that take any: `fit` (`markdown_fit`) and `chunking` (`chunks`)."""

    fit: FitOptions | None = None
    chunking: ChunkOptions | None = None


def _markdown_formats(
    page: ParsedPage, manifest: CaptureManifest, requested: list[PageFormat], options: FormatOptions
) -> Formats:
    """`markdown`, `markdown_fit` and `chunks`, which read the same markdown: each is made once."""
    formats: Formats = {}
    final_url, kind = manifest.final_url, fetched_as(manifest.fetch_policy)
    pieces = options.chunking or ChunkOptions()
    chunked = "chunks" in requested
    plain = fitted = ""
    if "markdown" in requested or (chunked and pieces.source == "markdown"):
        plain = markdown(page, final_url, kind)
    if "markdown_fit" in requested or (chunked and pieces.source == "markdown_fit"):
        fitted = markdown_fit(page, final_url, kind, options.fit)
    if "markdown" in requested:
        formats["markdown"] = plain
    if "markdown_fit" in requested:
        formats["markdown_fit"] = fitted
    if chunked:
        formats["chunks"] = chunks(plain if pieces.source == "markdown" else fitted, pieces)
    return formats


def page_formats(
    page: ParsedPage,
    manifest: CaptureManifest,
    requested: list[PageFormat],
    options: FormatOptions | None = None,
    artifacts: Collection[str] = (),
) -> Formats:
    """The requested content formats of a reached page, from its one parse (INV-26) and its
    capture's manifest: a format is a function of the capture alone (§15), the page kind it was fetched as included.
    `artifacts` names the files stored for the capture; a screenshot or PDF is a member only when it was made."""
    formats = _markdown_formats(page, manifest, requested, options or FormatOptions())
    if "screenshot" in requested and SCREENSHOT in artifacts:
        formats["screenshot"] = artifact_of(manifest.capture_id, SCREENSHOT)
    if "pdf" in requested and PDF in artifacts:
        formats["pdf"] = artifact_of(manifest.capture_id, PDF)
    final_url = manifest.final_url
    if "html" in requested:
        formats["html"] = cleaned_html(page)
    if "raw_html" in requested:
        formats["raw_html"] = page.html
    if "links" in requested:
        formats["links"] = list(links(page, final_url))
    if "metadata" in requested:
        formats["metadata"] = metadata(page, final_url)
    return formats
