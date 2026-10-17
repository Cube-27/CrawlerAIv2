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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
from typing import Any, Final, Self, TypedDict
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, field_validator, model_validator
from sqlalchemy import Row, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.acquire.politeness import refuse
from crawlerai.acquire.robots import Robots
from crawlerai.acquire.rungs import RenderCheck, acquire
from crawlerai.acquire.types import ActionsReport, AttemptRecord, BrowserActions, FetchPolicy, FetchResult, PagedFetch
from crawlerai.config_ir.active import active_config, recipe_of
from crawlerai.config_ir.api_recipe.model import ApiRecipe
from crawlerai.config_ir.drift import DriftMargins
from crawlerai.config_ir.role_c import role_c
from crawlerai.content.metadata import PageMetadata
from crawlerai.content.page import ParsedPage
from crawlerai.core.capture import BlockClass, CaptureMethod
from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.core.errors import Refusal
from crawlerai.crawl.canonical import canonicalize
from crawlerai.db.models import Capture, CaptureId, Job, JobId, PageKind, SiteId, UrlTask
from crawlerai.db.queue import ClaimedTask, complete_task, fail_task, insert_claimed
from crawlerai.llm.client import NO_LLM, LLMClient, LLMFailure
from crawlerai.llm.roles.s_schema import draft_schema
from crawlerai.resolve.pipeline import EngineData, extract_page
from crawlerai.resolve.task import ActiveConfig, StoredRecord
from crawlerai.resolve.types import ExtractionResult
from crawlerai.schemas.types import SchemaDef
from crawlerai.services.fetching import (
    Fetching,
    TargetRejected,
    adapter_send,
    admitted,
    check_target,
    engine_rules,
    recipe_rung,
    refusal,
    site_rules,
)
from crawlerai.services.records import ScrapedRecord
from crawlerai.services.scrape_paging import check_browser_actions, paged_fetch
from crawlerai.services.scrape_steps import (
    BLOCK_OUTCOMES,
    DEFAULT_PROJECT,
    EXTRACTION_ERROR,
    FetchOptions,
    Formats,
    Input,
    OfferCheck,
    PageFormat,
    PageOutcome,
    SchemaPrompt,
    SchemaRequest,
    SchemaUnusable,
    SiteRow,
    check_records,
    check_usable,
    fetch_policy,
    format_member,
    named_schema,
    new_capture,
    offer_check,
    page_formats,
    parsed_page,
    record_fetch_usage,
    records_outcome,
    site_row,
    store_page_record,
)
from crawlerai.storage.base import ObjectNotFound, ObjectStore
from crawlerai.storage.capture_bundle import CaptureManifest, decode

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
        return self


class FetchSummary(BaseModel):
    """The fetch of the page: the method, status and class of the kept attempt, and every attempt made."""

    method: CaptureMethod
    status_code: int | None  # None when no response arrived
    block_class: BlockClass
    attempts: tuple[AttemptRecord, ...]


class Usage(BaseModel):
    """What the scrape's job used (ARCHITECTURE §17)."""

    llm_calls: int = 0
    llm_tokens_in: int = 0
    llm_tokens_out: int = 0
    browser_seconds: int = 0
    http_requests: int = 0


class ScrapeResult(BaseModel):
    """The answer to a scrape (§4.4). A page that robots.txt kept from being fetched has no capture, so
    `capture_id`, `final_url`, `fetched_at` and `fetch` are None. `schema` is the draft of a `schema.prompt`."""

    model_config = ConfigDict(validate_by_name=True, serialize_by_alias=True)

    job_id: JobId
    capture_id: CaptureId | None
    url: str
    final_url: str | None
    fetched_at: datetime | None
    outcome: PageOutcome
    fetch: FetchSummary | None
    markdown: str | None = format_member()
    html: str | None = format_member()
    raw_html: str | None = format_member()
    links: list[str] | None = format_member()
    metadata: PageMetadata | None = format_member()
    schema_: SchemaDef | None = format_member(alias="schema")
    records: list[ScrapedRecord] | None = format_member()
    browser_actions: ActionsReport | None = format_member()
    usage: Usage


class ScrapeTimedOut(Refusal):
    def __init__(self, timeout_s: float) -> None:
        super().__init__(f"the scrape did not finish within {timeout_s:g} s")


class RecordsUnavailable(Refusal):
    """`records` was asked of a process without the engine's data files (`EngineData`, D-0492)."""


@dataclass(frozen=True)
class _Recent:
    """A capture `max_age` lets the scrape read again instead of fetching: its id, and the fetch that made it."""

    capture_id: CaptureId
    result: FetchResult


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
        site = await site_row(conn, host)
        config = await _config(conn, site.id, work)
        recipe = recipe_of(config) if config is not None and records_only else None
        row = None
        if request.max_age:
            row = await _recent_capture(conn, site.id, task.canonical_url, request.max_age, api=recipe is not None)
    recent = None if row is None else await _reread(fetching.store, row)
    policy = fetch_policy(request.fetch, request.locale, site.proxy_pool, page_kind=request.page_kind)
    attempts: list[AttemptRecord] = []
    check = _offer_check(work, request, config)
    further: tuple[FetchResult, ...] = ()
    report: ActionsReport | None = None
    page: FetchResult | str
    if recent is not None:
        page = recent.result
    elif request.browser_actions is not None:
        paged = await paged_fetch(
            engine, fetching, request.url, host, policy, site, attempts, request.browser_actions, request.timeout_s
        )
        page, further, report = _pages(paged)
    else:
        page = await polite_fetch(
            engine, fetching, request.url, host, policy, site, attempts, recipe=recipe, needs_render=check
        )
    # Formats, the draft and the extraction come before the write, so a timeout or an LLM failure while they are made
    # still finds the task claimed. They are made only from a page that was reached (§4.8: no partial formats).
    derived = _NOTHING
    if isinstance(page, FetchResult) and page.block_class == "ok":
        derived = await _derive(engine, work, request, task, (page, parsed_page(page.bundle, check)), config)
    extra = await _extract_more(work, task, derived, config, further)
    members, records = _NOT_FETCHED, None
    async with engine.begin() as conn:
        if isinstance(page, FetchResult):
            capture_id = recent.capture_id if recent else await new_capture(conn, fetching.store, site.id, page)
            more = partial(_store_more, conn, fetching.store, task, site.id, derived, extra, work.margins)
            outcome, records = await _finish(conn, task, site.id, page, capture_id, derived, work.margins, more)
            members = _fetch_members(page, capture_id)
        else:
            outcome = "blocked"
            await complete_task(conn, task, outcome, reason=page)
        await record_fetch_usage(conn, task.job_id, attempts, policy.proxy_pool)
        usage = await _usage(conn, task.job_id)
    if outcome == "failed":
        derived = _NOTHING  # §4.8: nothing derived from the page is returned on failure
    return ScrapeResult(
        job_id=task.job_id,
        url=request.url,
        outcome=outcome,
        usage=usage,
        schema_=derived.drafted,
        records=records,
        browser_actions=report,
        **members,
        **derived.formats,
    )


def _pages(paged: PagedFetch | str) -> tuple[FetchResult | str, tuple[FetchResult, ...], ActionsReport | None]:
    """The first page of a paged fetch (the scrape's capture and formats), the other kept states, and the report."""
    if isinstance(paged, str):
        return paged, (), None
    return paged.pages[0], paged.pages[1:], paged.report


# A further kept state of a listing, its extraction, and the site's active config as it ran on it.
_Extracted = tuple[FetchResult, ExtractionResult, ActiveConfig | None]


async def _extract_more(
    work: _Work, task: ClaimedTask, derived: _Derived, config: ActiveConfig | None, pages: tuple[FetchResult, ...]
) -> list[_Extracted]:
    """The extraction of each further kept state that was reached, with the first page's schema, as `_derive`'s."""
    schema, data = derived.schema, work.data
    if derived.extraction is None or schema is None or data is None:
        return []
    extracted: list[_Extracted] = []
    for page in pages:
        if page.block_class != "ok":
            continue
        own = None if config is None else config.for_capture(page.bundle.manifest, data.adapters)
        executor = None if own is None else own.executor
        gap_fill = role_c(work.llm, job_id=task.job_id)
        parsed = ParsedPage.of(page.bundle)
        extraction = await extract_page(page.bundle, schema, executor, gap_fill, data=data, parsed=parsed)
        extracted.append((page, extraction, own))
    return extracted


@dataclass(frozen=True)
class _More:
    """A listing's further kept states as stored: each record with the extraction it came from, and whether any
    state's extraction failed."""

    records: tuple[tuple[StoredRecord, ExtractionResult], ...] = ()
    failed: bool = False


async def _store_more(
    conn: AsyncConnection,
    store: ObjectStore,
    task: ClaimedTask,
    site_id: SiteId,
    derived: _Derived,
    extracted: list[_Extracted],
    margins: DriftMargins | None,
) -> _More:
    """Store each further kept state: its capture, its extraction and its records, under the scrape's task, each
    under the canonical URL of the document it read (a row without its own URL is keyed by its page and position)."""
    if derived.schema is None:
        return _More()
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
            schema=derived.schema,
            config=config,
            margins=margins,
            page_url=canonicalize(page.bundle.manifest.final_url),
        )
        failed = failed or kept.outcome == "failed"
        records.extend((record, extraction) for record in kept.records)
    return _More(tuple(records), failed)


def _offer_check(work: _Work, request: ScrapeRequest, config: ActiveConfig | None) -> OfferCheck | None:
    """The check that renders an HTTP page lacking the offer data `records` reads (owner #49); None without it."""
    return offer_check(work.schema, work.data, config) if "records" in request.formats else None


_CaptureRow = Row[CaptureId, str, int, dict[str, Any]]


async def _recent_capture(
    conn: AsyncConnection, site_id: SiteId, canonical: str, max_age: int, *, api: bool
) -> _CaptureRow | None:
    """The latest capture of `canonical` that reached its page (§4.8) within `max_age` seconds and has not expired;
    one an API recipe fetched only with `api`: a scrape that asks for the record only, with a config whose recipe
    reads it, as it holds JSON, not the page (SPEC-09 §4.8). Captures are found through the tasks that fetched them,
    which hold the canonical URL."""
    query = (
        select(Capture.id, Capture.object_key, Capture.duration_ms, Capture.fetch_policy)
        .join(UrlTask, UrlTask.capture_id == Capture.id)
        .where(
            Capture.site_id == site_id,
            Capture.fetched_at >= func.now() - timedelta(seconds=max_age),
            Capture.block_class == "ok",
            or_(Capture.expires_at.is_(None), Capture.expires_at > func.now()),
            UrlTask.canonical_url == canonical,
        )
        .order_by(Capture.fetched_at.desc())
        .limit(1)
    )
    if not api:
        query = query.where(Capture.method != "api")
    return (await conn.execute(query)).one_or_none()


async def _reread(store: ObjectStore, row: _CaptureRow) -> _Recent | None:
    """The capture's bundle, with the attempts its row keeps (SPEC-02 §4.4); None when its bundle is gone."""
    capture_id, object_key, duration_ms, fetch_policy = row
    try:
        blob = await asyncio.to_thread(store.get, object_key)
    except ObjectNotFound:
        return None
    bundle = await asyncio.to_thread(decode, blob)
    attempts = tuple(AttemptRecord.model_validate(attempt) for attempt in fetch_policy["attempts"])
    return _Recent(capture_id, FetchResult(bundle=bundle, duration_ms=duration_ms, attempts=attempts))


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
) -> _Derived:
    """The requested formats, the draft of a prompt, and the extraction for `records`, from the page's one parse
    (INV-26), with the site's active `config` when there is one."""
    result, page = reached
    prompt = request.schema_.prompt if isinstance(request.schema_, SchemaPrompt) else None
    manifest = result.bundle.manifest
    formats, sample = await asyncio.to_thread(_content, page, manifest, request.formats, sample=prompt is not None)
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


def _fetch_members(result: FetchResult, capture_id: CaptureId) -> _FetchMembers:
    manifest = result.bundle.manifest
    return _FetchMembers(
        capture_id=capture_id,
        final_url=manifest.final_url,
        fetched_at=manifest.fetched_at,
        fetch=FetchSummary(
            method=manifest.method,
            status_code=manifest.status_code or None,
            block_class=manifest.block_class,
            attempts=result.attempts,
        ),
    )


async def polite_fetch(
    engine: AsyncEngine,
    fetching: Fetching,
    url: str,
    host: str,
    policy: FetchPolicy,
    site: SiteRow,
    attempts: list[AttemptRecord],
    *,
    recipe: ApiRecipe | None = None,
    needs_render: RenderCheck | None = None,
) -> FetchResult | str:
    """The page at `url`, on `host`, as fetched while the caller waits, or why robots.txt kept it from being fetched
    (SPEC-02 §4.6); served by `recipe`, the site's active API recipe, when one is given (`recipe_rung`), and rendered
    once more when `needs_render` finds its HTTP page lacking (owner #49). The attempts
    of every fetch made, robots.txt's too, are added to `attempts`. Raises `TargetRejected` when the guard refused a
    request of the fetch (INV-16)."""
    robots: Robots | None = None
    if policy.respect_robots:
        robots = await site_rules(engine, fetching.rungs.http, site, url, policy, attempts)
        # RFC 9309 §2.3.1.4: an unreachable robots.txt allows nothing.
        if robots is None:
            return "robots_unreachable"
    # SPEC-15 §4.6: an adapter that serves the URL requests its API, whose own robots.txt `send` reads; the page's
    # governs only the page rungs it would fall back to, which a disallow then admits none of.
    disallowed = robots is not None and not robots.allows(url)
    if disallowed and not fetching.rungs.adapters.would_serve(url):
        return "robots"
    await admitted(fetching.limiter, host, site.crawl_delay_ms, robots)
    rules = engine_rules(engine, fetching.rungs.http, attempts)
    rung = None if recipe is None else recipe_rung(fetching, recipe, host, rules)
    admit_next = refuse if disallowed else partial(admitted, fetching.limiter, host, site.crawl_delay_ms, robots)
    send = adapter_send(fetching, host, rules)
    result = await acquire(
        url,
        policy,
        site.fetch_method,
        fetching.rungs,
        recipe=rung,
        admit_next=admit_next,
        send=send,
        needs_render=needs_render,
    )
    attempts.extend(result.attempts)
    if (refused := refusal(result)) is not None:
        raise TargetRejected(refused)
    return "robots" if disallowed and result.block_class != "ok" else result


async def _finish(
    conn: AsyncConnection,
    task: ClaimedTask,
    site_id: SiteId,
    result: FetchResult,
    capture_id: CaptureId,
    derived: _Derived,
    margins: DriftMargins | None,
    more: Callable[[], Awaitable[_More]] | None = None,
) -> tuple[PageOutcome, list[ScrapedRecord] | None]:
    """Settle the task with the page's outcome, after storing its extraction and record when `records` asked, and
    the page's run of an active config in its drift window. `more` stores a listing's further kept states (owner
    #52), once the page's own extraction did not fail: the answer lists every record once, and a further state whose
    extraction failed makes the outcome `partial`."""
    outcome = BLOCK_OUTCOMES[result.block_class]
    if outcome == "failed":
        error = result.attempts[-1].error or outcome
        await fail_task(conn, task, error, transient=False, capture_id=capture_id)
        return outcome, None
    if derived.extraction is None or derived.schema is None:
        await complete_task(conn, task, outcome, capture_id=capture_id)
        return outcome, None
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
        return "failed", None
    further = _More() if more is None else await more()
    # A detail page's one record, or a listing's one per row (none when it listed nothing, SPEC-05 §4.10).
    kept = {record.id: (record, extraction) for record in stored.records} | {r.id: (r, e) for r, e in further.records}
    outcome = records_outcome(tuple(record for record, _ in kept.values()))
    if further.failed:
        outcome = "partial"
    await complete_task(conn, task, outcome, capture_id=capture_id)
    return outcome, [_scraped(record, of) for record, of in kept.values()]


def _scraped(kept: StoredRecord, extraction: ExtractionResult) -> ScrapedRecord:
    return ScrapedRecord.of(kept.id, kept.draft, mode=extraction.mode, confidence=extraction.record_confidence)


def _content(
    page: ParsedPage, manifest: CaptureManifest, requested: list[PageFormat], *, sample: bool
) -> tuple[Formats, str | None]:
    """The requested content formats of the page and, when `sample`, its cleaned text."""
    return page_formats(page, manifest, requested), page.cleaned_text.text if sample else None


async def _usage(conn: AsyncConnection, job_id: JobId) -> Usage:
    used: dict[str, int] = (await conn.execute(select(Job.usage).where(Job.id == job_id))).scalar_one()
    return Usage.model_validate({name: used[name] for name in Usage.model_fields if name in used})
