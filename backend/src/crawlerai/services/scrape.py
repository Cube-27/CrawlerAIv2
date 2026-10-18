"""The scrape service (SPEC-07 §4.4, §4.7): one URL fetched while the caller waits, and returned in the content formats
it asks for. `POST /v1/scrape` calls it; the MCP `scrape` tool will (SPEC-10).

A scrape is a `job` of kind `scrape` with one `url_task`, run here rather than through the queue, so its usage and
events are kept like any job's. The task is fetched as a worker fetches one: robots.txt, the site's rate, the rungs
(SPEC-02). A fetch that does not reach the page is an outcome, not an error (§4.8). The whole scrape is bounded by
`timeout_s`; past it the job fails and nothing is returned. A target the SSRF guard refuses is never fetched (INV-16).

A `schema.prompt` is drafted into a schema by role S (SPEC-06 §4.5) from the cleaned text of the fetched page, and the
draft is returned; the same prompt returns the stored draft without a call. A page that was not reached is not drafted
from. A draft the LLM could not give (no provider, no budget, an invalid reply) fails the job, like a timeout.
`schema.fields` is drafted from the names before the job starts (SPEC-14 §4.10), so a draft that fails stores nothing.

`records` extracts the page with `extract_page` (SPEC-05) against the schema named by id, given inline, or drafted, and
stores the extraction and the records (`resolve.task`: a listing has one per row). A scrape URL is caller-supplied, so a
page whose required fields don't all publish keeps its record, `complete=false`, with outcome `partial` (ARCHITECTURE
§10). A site with an active config for the schema extracts in `config` mode (SPEC-08 §4.8), and the page joins
the config's drift window (§4.9). A scrape that asks for the record only is served by the config's API recipe when it
has one (SPEC-09 §4.8): a JSON body has no markdown, links or metadata of the page, so other formats fetch the page. The
formats, the draft and the records all read one parse of the page (INV-26). With `max_age`, a capture of the same
canonical URL that reached its page within that many seconds is read again instead of fetching.
"""

import asyncio
import os
import socket
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Final, NamedTuple, Self, TypedDict
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.acquire.types import ActionsReport, AttemptRecord, BrowserActions, FetchPolicy, FetchResult, PagedFetch
from crawlerai.collect.run import Adapters
from crawlerai.config_ir.active import active_config, recipe_of
from crawlerai.config_ir.drift import DriftMargins
from crawlerai.config_ir.role_c import role_c
from crawlerai.content.chunks import Chunk, ChunkOptions
from crawlerai.content.fit import FitOptions
from crawlerai.content.metadata import PageMetadata
from crawlerai.content.page import ParsedPage
from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.core.errors import Refusal
from crawlerai.db.models import CaptureId, Job, JobId, PageKind, SiteId
from crawlerai.db.queue import ClaimedTask, complete_task, fail_task, insert_claimed
from crawlerai.llm.client import NO_LLM, LLMClient, LLMFailure
from crawlerai.llm.roles.s_schema import draft_schema
from crawlerai.normalize.url_key import canonicalize
from crawlerai.resolve.pipeline import EngineData, extract_page
from crawlerai.resolve.task import ActiveConfig, StoredRecord
from crawlerai.resolve.types import ExtractionResult
from crawlerai.schemas.types import SchemaDef
from crawlerai.services.fetch_options import CacheMode, check_proxy_pool
from crawlerai.services.fetching import Fetching, PagePlan, TargetRejected, check_target, fetch_now, site_rungs
from crawlerai.services.records import RecordField, ScrapedRecord, page_fields
from crawlerai.services.scrape_paging import check_browser_actions, paged_fetch
from crawlerai.services.scrape_steps import (
    BLOCK_OUTCOMES,
    CAPTURE_FORMATS,
    DEFAULT_PROJECT,
    EXTRACTION_ERROR,
    FetchOptions,
    FetchSummary,
    FormatOptions,
    Formats,
    Further,
    Input,
    PageFormat,
    PageOutcome,
    RenderNeed,
    SchemaPrompt,
    SchemaRequest,
    SchemaUnusable,
    StoredFurther,
    check_formats,
    check_records,
    check_usable,
    extract_further,
    fetch_policy,
    fetch_summary,
    format_member,
    named_schema,
    new_capture,
    page_formats,
    parsed_page,
    record_fetch_usage,
    records_outcome,
    render_need,
    site_row,
    store_further,
    store_page_record,
)
from crawlerai.services.stored_captures import NOT_CACHED, CaptureRow, NotCached, Recent, recent_capture, reread
from crawlerai.storage.artifacts import Artifact
from crawlerai.storage.base import ObjectStore
from crawlerai.storage.capture_bundle import CaptureManifest

MAX_TIMEOUT_S: Final = 120  # D-0028
# A scrape task's `last_error` when it failed for no reason the service declares.
INTERNAL_ERROR: Final = "internal_error"
# The process that runs a scrape's task, named as a worker names itself (`crawlerai.worker.loop`).
_CLAIMANT: Final = f"api:{socket.gethostname()}:{os.getpid()}"


class Budget(Input):
    """A request's own bound on its job's LLM calls. A request without one takes the project's `llm_call_cap`, and a
    project without a cap bounds none (owner, 2026-10-16; `db.usage.budget_remaining`)."""

    llm_calls: NonNegativeInt


class ScrapeRequest(Input):
    """The body of `POST /v1/scrape` (§4.4). `records` needs a schema and a `page_kind`, and the schema's page kind
    must be that one. A `schema.prompt` is drafted and returned, and `budget.llm_calls` (else the project's cap) bounds
    its draft; `schema.fields` is drafted before the job, which no budget counts. `max_age` reuses a capture fetched
    within that many seconds. `browser_actions` collects more of a listing's rows in the browser (owner #52)."""

    url: str
    formats: list[PageFormat] = Field(min_length=1)
    schema_: SchemaRequest | None = Field(default=None, alias="schema")
    page_kind: PageKind | None = None
    max_age: NonNegativeInt = 0  # seconds
    fetch: FetchOptions = FetchOptions()
    locale: str | None = None
    timeout_s: float = Field(default=60, gt=0, le=MAX_TIMEOUT_S)
    budget: Budget | None = None
    browser_actions: BrowserActions | None = None
    fit: FitOptions | None = None  # `markdown_fit`'s query and block limit
    chunking: ChunkOptions | None = None  # `chunks`' strategy, size and overlap

    @field_validator("url")
    @classmethod
    def _absolute_http_url(cls, url: str) -> str:
        if canonicalize(url) is None:
            raise ValueError("not an absolute http or https URL")
        return url

    @model_validator(mode="after")
    def _records_have_a_schema(self) -> Self:
        check_records(self.formats, self.schema_, self.page_kind)
        check_browser_actions(self.browser_actions, self.page_kind, self.max_age, self.fetch)
        check_formats(self.formats, self.fetch, self.fit, self.chunking)
        if self.browser_actions is not None and CAPTURE_FORMATS.intersection(self.formats):
            raise ValueError("screenshot and pdf are of the page as first rendered, so browser_actions cannot ask them")
        return self

    @property
    def format_options(self) -> FormatOptions:
        return FormatOptions(fit=self.fit, chunking=self.chunking)


class Usage(BaseModel):
    """What the scrape's job used (ARCHITECTURE §17)."""

    llm_calls: int = 0
    llm_tokens_in: int = 0
    llm_tokens_out: int = 0
    browser_seconds: int = 0
    http_requests: int = 0


class ScrapeResult(BaseModel):
    """The answer to a scrape (§4.4). A page that robots.txt kept from being fetched has no capture, so
    `capture_id`, `final_url`, `fetched_at` and `fetch` are None, and `reason` says why, as the task's `last_error`
    does (SPEC-02 §4.6): `robots` for a disallow, `robots_unreachable` for a robots.txt that could not be read (RFC
    9309 §2.3.1.4); for a fetched listing whose extraction gave no rows, `no_rows: <cause>` (`no_rows` in
    `resolve.pipeline`, D-1475); None for any other page that was fetched. `schema` is the draft of a
    `schema.prompt`."""

    model_config = ConfigDict(validate_by_name=True, serialize_by_alias=True)

    job_id: JobId
    capture_id: CaptureId | None
    url: str
    final_url: str | None
    fetched_at: datetime | None
    outcome: PageOutcome
    reason: str | None
    fetch: FetchSummary | None
    markdown: str | None = format_member()
    markdown_fit: str | None = format_member()
    chunks: list[Chunk] | None = format_member()
    html: str | None = format_member()
    raw_html: str | None = format_member()
    links: list[str] | None = format_member()
    metadata: PageMetadata | None = format_member()
    screenshot: Artifact | None = format_member()
    pdf: Artifact | None = format_member()
    schema_: SchemaDef | None = format_member(alias="schema")
    records: list[ScrapedRecord] | None = format_member()
    # A listing that kept no record: its page-scope fields (`next_page_url`), in the record field shape (D-1476).
    page: dict[str, RecordField] | None = format_member()
    browser_actions: ActionsReport | None = format_member()
    usage: Usage


class ScrapeTimedOut(Refusal):
    def __init__(self, timeout_s: float) -> None:
        super().__init__(f"the scrape did not finish within {timeout_s:g} s")


class RecordsUnavailable(Refusal):
    """`records` was asked of a process without the engine's data files (`EngineData`, D-0492)."""


@dataclass(frozen=True)
class _Work:
    """What a scrape works with besides fetching: the LLM client, the engine's data and drift margins, and the schema
    `records` extracts with when the request names it (a prompt's is drafted after the fetch)."""

    llm: LLMClient
    data: EngineData | None
    margins: DriftMargins | None
    schema: SchemaDef | None


@dataclass(frozen=True)
class _Derived:
    """What a scrape makes of a page it reached: the formats, the draft of a prompt, and the page's extraction with
    the schema it extracted against."""

    formats: Formats
    drafted: SchemaDef | None = None
    schema: SchemaDef | None = None
    extraction: ExtractionResult | None = None
    config: ActiveConfig | None = None


_NOTHING: Final = _Derived(Formats())


class _FetchMembers(TypedDict):
    capture_id: CaptureId | None
    final_url: str | None
    fetched_at: datetime | None
    fetch: FetchSummary | None


_NOT_FETCHED = _FetchMembers(capture_id=None, final_url=None, fetched_at=None, fetch=None)


async def scrape(
    engine: AsyncEngine,
    fetching: Fetching,
    request: ScrapeRequest,
    *,
    llm: LLMClient = NO_LLM,
    data: EngineData | None = None,
    margins: DriftMargins | None = None,
) -> ScrapeResult:
    """Run `request` as a scrape job; `records` reads `data`, and an active config's drift `margins`. Raises, before
    any job is created: `TargetRejected` for a target refused outright, `RecordsUnavailable` for `records` without
    `data`, `SchemaUnusable` for a schema id `records` cannot use, and the schemas service's `SchemaConflict` or
    `InvalidSchema` for an inline schema, and the LLM client's `LLMFailure` for field names it could not draft.
    Raises, failing the job: `TargetRejected` for a refused redirect,
    `ScrapeTimedOut` past `request.timeout_s`, the LLM client's `LLMFailure` when a prompt could not be drafted, and
    `SchemaUnusable` for a draft of another page kind. Any other exception fails the job with `internal_error` and
    propagates."""
    await check_target(fetching.connector, request.url)
    check_proxy_pool(request.fetch, fetching.proxy_pools)
    work = _Work(llm, data, margins, await _named_schema(engine, request, data, llm))
    task = await _start(engine, request, work.schema)
    try:
        async with asyncio.timeout(request.timeout_s):
            return await _run(engine, fetching, work, request, task)
    except TimeoutError as e:
        await _fail(engine, task, "timeout")
        raise ScrapeTimedOut(request.timeout_s) from e
    except TargetRejected as e:
        await _fail(engine, task, e.reason)
        raise
    except SchemaUnusable:
        await _fail(engine, task, "invalid_schema")
        raise
    except LLMFailure as e:
        await _fail(engine, task, e.code)
        raise
    except NotCached:
        await _fail(engine, task, NOT_CACHED)
        raise
    except Exception:
        # Anything else is this process's fault; the job still ends now, not when the task's lease runs out.
        await _fail(engine, task, INTERNAL_ERROR)
        raise


async def _named_schema(
    engine: AsyncEngine, request: ScrapeRequest, data: EngineData | None, llm: LLMClient
) -> SchemaDef | None:
    """The schema `records` extracts with when the request names it by id, inline or by field names; None without
    `records`, and for a prompt, whose draft needs the page."""
    if "records" not in request.formats:
        return None
    if data is None:
        raise RecordsUnavailable("this process has not loaded the engine's data files")
    return await named_schema(engine, request.schema_, request.page_kind, llm)


async def _start(engine: AsyncEngine, request: ScrapeRequest, schema: SchemaDef | None) -> ClaimedTask:
    """The running job, with its task claimed by this process. Committed on its own, so that a scrape that fails
    or times out can still record that on them."""
    async with engine.begin() as conn:
        job_id = (
            await conn.execute(
                pg_insert(Job)
                .values(
                    project_id=DEFAULT_PROJECT,
                    kind="scrape",
                    request=request.model_dump(mode="json", by_alias=True),
                    schema_id=None if schema is None else schema.id,
                    status="running",
                    started_at=func.now(),
                    engine_version=ENGINE_VERSION,
                )
                .returning(Job.id)
            )
        ).scalar_one()
        canonical = canonicalize(request.url) or request.url
        return await insert_claimed(conn, job_id, request.url, canonical, request.page_kind, _CLAIMANT)


async def _fail(engine: AsyncEngine, task: ClaimedTask, error: str) -> None:
    async with engine.begin() as conn:
        await fail_task(conn, task, error, transient=False)


async def _run(
    engine: AsyncEngine, fetching: Fetching, work: _Work, request: ScrapeRequest, task: ClaimedTask
) -> ScrapeResult:
    """The fetch runs outside any transaction, so a slow page holds no connection or row lock; what it found is
    written in one transaction after it. A recent capture `max_age` allows is read instead of fetching."""
    host = urlsplit(request.url).hostname or ""
    records_only = set(request.formats) == {"records"}
    async with engine.begin() as conn:
        site = await site_row(conn, host, request.page_kind)
        config = await _config(conn, site.id, work)
        recipe = recipe_of(config) if config is not None and records_only else None
        policy = fetch_policy(
            request.fetch, request.locale, site.proxy_pool, page_kind=request.page_kind, formats=request.formats
        )
        row = await _stored(conn, request, policy, site.id, task.canonical_url, api=recipe is not None)
    recent = await _read_stored(fetching.store, row, request.fetch.cache, request.formats)
    attempts: list[AttemptRecord] = []
    check = _render_need(work, request, config)
    further: tuple[FetchResult, ...] = ()
    report: ActionsReport | None = None
    page: FetchResult | str
    if recent is not None:
        page = recent.result
    elif request.browser_actions is not None:
        paged = await paged_fetch(
            engine, fetching, request.url, policy, attempts, request.browser_actions, request.timeout_s, recipe=recipe
        )
        page, further, report = _pages(paged)
    else:
        rungs = site_rungs(fetching, host, site)
        page_request = PagePlan(rungs, site, policy, attempts, recipe=recipe, needs_render=check)
        page = await fetch_now(engine, fetching, request.url, page_request)
    # Formats, the draft and the extraction come before the write, so a timeout or an LLM failure while they are made
    # still finds the task claimed. They are made only from a page that was reached (§4.8: no partial formats).
    derived = await _derive_reached(engine, work, request, task, page, recent, config, check)
    extra = await _extract_more(work, task, derived, config, further)
    members, finished = _NOT_FETCHED, _Finished("blocked")
    async with engine.begin() as conn:
        if isinstance(page, FetchResult):
            capture_id = recent.capture_id if recent else await new_capture(conn, fetching.store, site.id, page)
            more = partial(_store_more, conn, fetching.store, task, site.id, derived, extra, work.margins)
            finished = await _finish(conn, task, site.id, page, capture_id, derived, work.margins, more)
            members = _fetch_members(page, capture_id, fetching.rungs.adapters)
        else:
            finished = _Finished("blocked", reason=page)
            await complete_task(conn, task, "blocked", reason=page)
        await record_fetch_usage(conn, task.job_id, attempts, policy.proxy_pool)
        usage = await _usage(conn, task.job_id)
    if finished.outcome == "failed":
        derived = _NOTHING  # §4.8: nothing derived from the page is returned on failure
    return ScrapeResult(
        job_id=task.job_id,
        url=request.url,
        outcome=finished.outcome,
        reason=finished.reason,
        usage=usage,
        schema_=derived.drafted,
        records=finished.records,
        page=finished.page,
        browser_actions=report,
        **members,
        **derived.formats,
    )


async def _stored(
    conn: AsyncConnection, request: ScrapeRequest, policy: FetchPolicy, site_id: SiteId, canonical: str, *, api: bool
) -> CaptureRow | None:
    """The stored capture the request reads instead of fetching (D-1435): within `max_age` by default, none with
    `cache: bypass`, and with `cache: only` within `max_age`, or of any age when it is 0."""
    cache = request.fetch.cache
    if cache == "bypass" or (cache == "default" and not request.max_age):
        return None
    max_age = request.max_age or (None if cache == "only" else 0)
    return await recent_capture(conn, site_id, canonical, policy, max_age=max_age, api=api)


async def _read_stored(
    store: ObjectStore, row: CaptureRow | None, cache: CacheMode, formats: Collection[str]
) -> Recent | None:
    """The stored capture `row` names, read again with the files `formats` ask of it; with `cache: only`, `NotCached`
    when there is none to read."""
    recent = None if row is None else await reread(store, row, formats)
    if recent is None and cache == "only":
        raise NotCached("no stored capture of the page was made the way this request fetches it")
    return recent


async def _derive_reached(
    engine: AsyncEngine,
    work: _Work,
    request: ScrapeRequest,
    task: ClaimedTask,
    page: FetchResult | str,
    recent: Recent | None,
    config: ActiveConfig | None,
    check: RenderNeed | None,
) -> _Derived:
    """What `_derive` makes of the page when it was reached, else nothing; `recent` is the capture reread instead of a
    fetch, whose stored files the answer names."""
    if not isinstance(page, FetchResult) or page.block_class != "ok":
        return _NOTHING
    files = frozenset(page.artifacts) if recent is None else recent.artifacts
    reached = (page, parsed_page(page.bundle, check))
    return await _derive(engine, work, request, task, reached, config, files=files)


def _pages(paged: PagedFetch | str) -> tuple[FetchResult | str, tuple[FetchResult, ...], ActionsReport | None]:
    """The first page of a paged fetch (the scrape's capture and formats), the other kept states, and the report."""
    if isinstance(paged, str):
        return paged, (), None
    return paged.pages[0], paged.pages[1:], paged.report


async def _extract_more(
    work: _Work, task: ClaimedTask, derived: _Derived, config: ActiveConfig | None, pages: tuple[FetchResult, ...]
) -> list[Further]:
    """The extraction of each further kept state that was reached, with the first page's schema, as `_derive`'s."""
    schema, data = derived.schema, work.data
    if derived.extraction is None or schema is None or data is None:
        return []
    return await extract_further(pages, schema, config, data, role_c(work.llm, job_id=task.job_id))


async def _store_more(
    conn: AsyncConnection,
    store: ObjectStore,
    task: ClaimedTask,
    site_id: SiteId,
    derived: _Derived,
    extracted: list[Further],
    margins: DriftMargins | None,
) -> StoredFurther:
    """Store each further kept state under the scrape's task (`store_further`)."""
    if derived.schema is None:
        return StoredFurther()
    return await store_further(conn, store, task, site_id, derived.schema, extracted, margins)


def _render_need(work: _Work, request: ScrapeRequest, config: ActiveConfig | None) -> RenderNeed | None:
    """The check that renders an HTTP page lacking the offer data or the items `records` reads (owner #49, #54); None
    without `records`."""
    if "records" not in request.formats:
        return None
    return render_need(work.schema, work.data, config)


async def _config(conn: AsyncConnection, site_id: SiteId, work: _Work) -> ActiveConfig | None:
    """The site's active config for the schema `records` names; a prompt's draft is new, so it has none."""
    if work.schema is None or work.data is None:
        return None
    return await active_config(conn, site_id, work.schema, work.data.vocabulary)


async def _derive(
    engine: AsyncEngine,
    work: _Work,
    request: ScrapeRequest,
    task: ClaimedTask,
    reached: tuple[FetchResult, ParsedPage],
    config: ActiveConfig | None,
    *,
    files: frozenset[str] = frozenset(),
) -> _Derived:
    """The requested formats, the draft of a prompt, and the extraction for `records`, from the page's one parse
    (INV-26), with the site's active `config` when there is one; `files` names the artifacts stored for the capture."""
    result, page = reached
    prompt = request.schema_.prompt if isinstance(request.schema_, SchemaPrompt) else None
    manifest = result.bundle.manifest
    formats, sample = await asyncio.to_thread(_content, page, manifest, request, files, sample=prompt is not None)
    drafted = None
    if prompt is not None and sample is not None:
        # Role S's one sample page is the page's cleaned text (SPEC-06 §4.5).
        drafted = await draft_schema(engine, work.llm, prompt=prompt, samples=[sample], job_id=task.job_id)
    schema = work.schema if drafted is None else drafted
    if "records" not in request.formats or schema is None or work.data is None:
        return _Derived(formats, drafted)
    if drafted is not None:
        check_usable(drafted, request.page_kind)
    # §4.4 step 3: role C fills required fields left missing, charged to the job. No write to the job's row is open
    # here: the job was committed before the fetch, and the task is written after (D-0346).
    config = None if config is None else config.for_capture(result.bundle.manifest, work.data.adapters)
    executor = None if config is None else config.executor
    gap_fill = role_c(work.llm, job_id=task.job_id)
    extraction = await extract_page(result.bundle, schema, executor, gap_fill, data=work.data, parsed=page)
    return _Derived(formats, drafted, schema, extraction, config)


def _fetch_members(result: FetchResult, capture_id: CaptureId, adapters: Adapters) -> _FetchMembers:
    manifest = result.bundle.manifest
    return _FetchMembers(
        capture_id=capture_id,
        final_url=manifest.final_url,
        fetched_at=manifest.fetched_at,
        fetch=fetch_summary(
            manifest.method,
            manifest.status_code or None,
            manifest.block_class,
            result.attempts,
            adapters=adapters,
            url=manifest.url,
            final_url=manifest.final_url,
        ),
    )


class _Finished(NamedTuple):
    """How a scrape's task ended: its outcome, the records `records` kept, why (`ScrapeResult.reason`), and a listing's
    page fields when it kept no record."""

    outcome: PageOutcome
    records: list[ScrapedRecord] | None = None
    reason: str | None = None
    page: dict[str, RecordField] | None = None


async def _finish(
    conn: AsyncConnection,
    task: ClaimedTask,
    site_id: SiteId,
    result: FetchResult,
    capture_id: CaptureId,
    derived: _Derived,
    margins: DriftMargins | None,
    more: Callable[[], Awaitable[StoredFurther]] | None = None,
) -> _Finished:
    """Settle the task with the page's outcome, after storing its extraction and record when `records` asked, and
    the page's run of an active config in its drift window. `more` stores a listing's further kept states (owner
    #52), once the page's own extraction did not fail: the answer lists every record once, and a further state whose
    extraction failed makes the outcome `partial`. A listing that kept no record says why, in the answer and the task's
    `last_error` (D-1475), and answers its page fields (D-1476)."""
    outcome = BLOCK_OUTCOMES[result.block_class]
    if outcome == "failed":
        error = result.attempts[-1].error or outcome
        await fail_task(conn, task, error, transient=False, capture_id=capture_id)
        return _Finished(outcome)
    if derived.extraction is None or derived.schema is None:
        await complete_task(conn, task, outcome, capture_id=capture_id)
        return _Finished(outcome)
    extraction = derived.extraction
    stored = await store_page_record(
        conn,
        task,
        extraction,
        capture_id=capture_id,
        site_id=site_id,
        schema=derived.schema,
        config=derived.config,
        margins=margins,
    )
    if stored.outcome == "failed":
        await fail_task(conn, task, EXTRACTION_ERROR, transient=False, capture_id=capture_id)
        return _Finished("failed")
    further = StoredFurther() if more is None else await more()
    # A detail page's one record, or a listing's one per row (none when it listed nothing, SPEC-05 §4.10).
    kept = {record.id: (record, extraction) for record in stored.records} | {r.id: (r, e) for r, e in further.records}
    outcome = records_outcome(tuple(record for record, _ in kept.values()))
    if further.failed:
        outcome = "partial"
    reason, page = _unlisted(derived.schema, extraction) if not kept else (None, None)
    await complete_task(conn, task, outcome, reason=reason, capture_id=capture_id)
    return _Finished(outcome, [_scraped(record, of) for record, of in kept.values()], reason, page)


def _unlisted(schema: SchemaDef, extraction: ExtractionResult) -> tuple[str | None, dict[str, RecordField] | None]:
    """A listing without a kept record: why it has no rows, if it has none, and its page fields."""
    if schema.page_kind != "listing" or extraction.entity is None:
        return None, None
    return extraction.reason, page_fields(schema, extraction.entity)


def _scraped(kept: StoredRecord, extraction: ExtractionResult) -> ScrapedRecord:
    return ScrapedRecord.of(kept.id, kept.draft, mode=extraction.mode, confidence=extraction.record_confidence)


def _content(
    page: ParsedPage, manifest: CaptureManifest, request: ScrapeRequest, files: frozenset[str], *, sample: bool
) -> tuple[Formats, str | None]:
    """The requested content formats of the page and, when `sample`, its cleaned text."""
    formats = page_formats(page, manifest, request.formats, request.format_options, files)
    return formats, page.cleaned_text.text if sample else None


async def _usage(conn: AsyncConnection, job_id: JobId) -> Usage:
    used: dict[str, int] = (await conn.execute(select(Job.usage).where(Job.id == job_id))).scalar_one()
    return Usage.model_validate({name: used[name] for name in Usage.model_fields if name in used})
