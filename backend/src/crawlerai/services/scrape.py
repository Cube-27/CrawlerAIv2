"""The scrape service (SPEC-07 §4.4, §4.7): one URL fetched while the caller waits, and returned in the content formats
it asks for. `POST /v1/scrape` calls it; the MCP `scrape` tool will (SPEC-10).

A scrape is a `job` of kind `scrape` with one `url_task`, run here rather than through the queue, so its usage and
events are kept like any job's. The task is fetched as a worker fetches one: robots.txt, the site's rate, the rungs
(SPEC-02). A fetch that does not reach the page is an outcome, not an error (§4.8). The whole scrape is bounded by
`timeout_s`; past it the job fails and nothing is returned. A target the SSRF guard refuses is never fetched (INV-16).

A `schema.prompt` is drafted into a schema by role S (SPEC-06 §4.5) from the cleaned text of the fetched page, and the
draft is returned; the same prompt returns the stored draft without a call. A page that was not reached is not drafted
from. A draft the LLM could not give (no provider, no budget, an invalid reply) fails the job, like a timeout.

`records` extracts the page with `extract_page` (SPEC-05) against the schema named by id, given inline, or drafted,
and stores the extraction and the record (`resolve.task`). A scrape URL is caller-supplied, so a page whose required
fields don't all publish keeps its record, `complete=false`, with outcome `partial` (ARCHITECTURE §10). A site with an
active config for the schema version extracts in `config` mode (SPEC-08 §4.8), and the page joins the config's drift
window (§4.9). The formats,
the draft and the records all read one parse of the page (INV-26). With `max_age`, a capture of the same canonical URL
that reached its page within that many seconds is read again instead of fetching.
"""

import asyncio
import math
import os
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Literal, Self, TypedDict
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, field_validator, model_validator
from sqlalchemy import Row, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.acquire.persist import store_capture
from crawlerai.acquire.politeness import HostLimiter, interval
from crawlerai.acquire.robots import Robots, site_robots
from crawlerai.acquire.rungs import Rungs, acquire, remember_fetch_method
from crawlerai.acquire.ssrf import SSRF_REJECTED, SafeConnector, SsrfRejected
from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult, check_robots_override
from crawlerai.config_ir.active import active_config, record_page
from crawlerai.config_ir.drift import DriftMargins
from crawlerai.content.html import cleaned_html
from crawlerai.content.links import links
from crawlerai.content.markdown import markdown
from crawlerai.content.metadata import PageMetadata, metadata
from crawlerai.content.page import ParsedPage
from crawlerai.core.capture import BlockClass, CaptureMethod
from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.db.models import (
    Capture,
    CaptureId,
    FetchMethod,
    Job,
    JobId,
    PageKind,
    ProgressiveState,
    Project,
    SchemaId,
    Site,
    SiteId,
    UrlTask,
    UsageResource,
)
from crawlerai.db.queue import ClaimedTask, complete_task, fail_task, insert_claimed
from crawlerai.db.usage import record_usage
from crawlerai.llm.client import LLMClient, LLMFailure, Unconfigured
from crawlerai.llm.roles.s_schema import draft_schema, normalize_prompt
from crawlerai.normalize.url import canonical_url
from crawlerai.resolve.pipeline import EngineData, extract_page
from crawlerai.resolve.task import ActiveConfig, store_extraction
from crawlerai.resolve.types import ExtractionResult
from crawlerai.schemas.registry import SchemaNotFound, get_by_id
from crawlerai.schemas.types import SchemaDef
from crawlerai.services import schemas
from crawlerai.services.records import ScrapedRecord
from crawlerai.services.schemas import NewSchema
from crawlerai.storage.base import ObjectNotFound, ObjectStore
from crawlerai.storage.capture_bundle import decode

ScrapeFormat = Literal["markdown", "html", "raw_html", "links", "metadata", "records"]
# `url_task.outcome` as a scrape reports it (§4.4).
ScrapeOutcome = Literal["extracted", "partial", "blocked", "shell", "not_found", "failed"]

MAX_TIMEOUT_S: Final = 120  # D-0028
_OUTCOMES: Final[dict[BlockClass, ScrapeOutcome]] = {
    # Without `records` the page is extracted once it is fetched; with them, its record decides (`partial`).
    "ok": "extracted",
    "blocked": "blocked",
    "shell": "shell",
    "not_found": "not_found",
    "error": "failed",
}
# The usage a fetch attempt counts (SPEC-02 §4.7, §4.8): a request per HTTP or API attempt, the seconds of a browser's.
_REQUEST_METHODS: Final[frozenset[CaptureMethod]] = frozenset({"http", "api"})
# The process that runs a scrape's task, named as a worker names itself (`crawlerai.worker.loop`).
_CLAIMANT: Final = f"api:{socket.gethostname()}:{os.getpid()}"
# Jobs and sites belong to the project migrations create (single tenant, ARCHITECTURE §1).
_DEFAULT_PROJECT: Final = select(Project.id).where(Project.name == "default").scalar_subquery()
_NO_LLM: Final = Unconfigured("no LLM provider is configured")


class _Input(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SchemaById(_Input):
    id: SchemaId


class SchemaInline(_Input):
    inline: NewSchema


class SchemaPrompt(_Input):
    prompt: str

    @field_validator("prompt")
    @classmethod
    def _not_blank(cls, prompt: str) -> str:
        # Role S reads the prompt whitespace-normalized (SPEC-06 §4.5), so one of only whitespace is empty.
        if not normalize_prompt(prompt):
            raise ValueError("the prompt is empty")
        return prompt


class FetchOptions(_Input):
    method_hint: Literal["auto", "http", "browser"] = "auto"
    respect_robots: bool = True
    robots_override_reason: str | None = None
    proxy_pool: str | None = None

    @model_validator(mode="after")
    def _override_has_a_reason(self) -> Self:
        check_robots_override(self.respect_robots, self.robots_override_reason)
        return self


class Budget(_Input):
    llm_calls: NonNegativeInt = 10


class ScrapeRequest(_Input):
    """The body of `POST /v1/scrape` (§4.4). `records` needs a schema and a `page_kind`, and the schema's page kind
    must be that one; listing records wait for SPEC-05 PR 12. A `schema.prompt` is drafted and returned, and
    `budget.llm_calls` bounds its draft. `max_age` reuses a capture fetched within that many seconds."""

    url: str
    formats: list[ScrapeFormat] = Field(min_length=1)
    schema_: SchemaById | SchemaInline | SchemaPrompt | None = Field(default=None, alias="schema")
    page_kind: PageKind | None = None
    max_age: NonNegativeInt = 0  # seconds
    fetch: FetchOptions = FetchOptions()
    locale: str | None = None
    timeout_s: float = Field(default=60, gt=0, le=MAX_TIMEOUT_S)
    budget: Budget = Budget()

    @field_validator("url")
    @classmethod
    def _absolute_http_url(cls, url: str) -> str:
        if canonical_url(url, None) is None:
            raise ValueError("not an absolute http or https URL")
        return url

    @model_validator(mode="after")
    def _records_have_a_schema(self) -> Self:
        if "records" not in self.formats:
            return self
        if self.schema_ is None:
            raise ValueError("the records format needs a schema")
        if self.page_kind is None:
            raise ValueError("the records format needs a page_kind")
        if self.page_kind == "listing":
            raise ValueError("records of listing pages are not available yet")
        if isinstance(self.schema_, SchemaInline) and self.schema_.inline.page_kind != self.page_kind:
            raise ValueError(f"the inline schema is for {self.schema_.inline.page_kind} pages, not {self.page_kind}")
        return self


def _absent(value: object) -> bool:
    return value is None


def _never_null(schema: dict[str, Any]) -> None:
    # A format's member is left out rather than null, so the document gives it no null branch and no default.
    (branch,) = (branch for branch in schema.pop("anyOf") if branch.get("type") != "null")
    schema.update(branch)
    del schema["default"]


def _format(alias: str | None = None) -> Any:
    """A member that is in the answer only when it was asked for: a format, or the draft of a prompt (§4.4)."""
    return Field(default=None, alias=alias, exclude_if=_absent, json_schema_extra=_never_null)


class _Formats(TypedDict, total=False):
    markdown: str
    html: str
    raw_html: str
    links: list[str]
    metadata: PageMetadata


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
    outcome: ScrapeOutcome
    fetch: FetchSummary | None
    markdown: str | None = _format()
    html: str | None = _format()
    raw_html: str | None = _format()
    links: list[str] | None = _format()
    metadata: PageMetadata | None = _format()
    schema_: SchemaDef | None = _format(alias="schema")
    records: list[ScrapedRecord] | None = _format()
    usage: Usage


@dataclass(frozen=True)
class Fetching:
    """What a scrape fetches with: the rungs, the SSRF guard they connect through, the object store captures go to,
    and the per-host limiter (SPEC-02 §4.6) of this process."""

    rungs: Rungs
    connector: SafeConnector
    store: ObjectStore
    limiter: HostLimiter


class ScrapeRejected(Exception):
    """The SSRF guard refused the target, or a redirect from it (INV-16). `reason` is the guard's, without the URL."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ScrapeTimedOut(Exception):
    def __init__(self, timeout_s: float) -> None:
        super().__init__(f"the scrape did not finish within {timeout_s:g} s")


class ScrapeInvalid(Exception):
    """The request's `schema` is one `records` cannot use: no such id, a retired version, or another page kind."""


class RecordsUnavailable(Exception):
    """`records` was asked of a process without the engine's data files (`EngineData`, D-0492)."""


_SiteRow = Row[SiteId, FetchMethod, str | None, str | None, int | None]


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

    formats: _Formats
    drafted: SchemaDef | None = None
    schema: SchemaDef | None = None
    extraction: ExtractionResult | None = None
    config: ActiveConfig | None = None


_NOTHING: Final = _Derived(_Formats())


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
    llm: LLMClient = _NO_LLM,
    data: EngineData | None = None,
    margins: DriftMargins | None = None,
) -> ScrapeResult:
    """Run `request` as a scrape job; `records` reads `data`, and an active config's drift `margins`. Raises, before
    any job is created: `ScrapeRejected` for a target refused outright, `RecordsUnavailable` for `records` without
    `data`, `ScrapeInvalid` for a schema id `records` cannot use, and the schemas service's `SchemaConflict` or
    `InvalidSchema` for an inline schema. Raises, failing the job: `ScrapeRejected` for a refused redirect,
    `ScrapeTimedOut` past `request.timeout_s`, the LLM client's `LLMFailure` when a prompt could not be drafted, and
    `ScrapeInvalid` for a draft of another page kind."""
    try:
        await fetching.connector.check(request.url)
    except SsrfRejected as e:
        raise ScrapeRejected(str(e)) from e
    work = _Work(llm, data, margins, await _named_schema(engine, request, data))
    task = await _start(engine, request, work.schema)
    try:
        async with asyncio.timeout(request.timeout_s):
            return await _run(engine, fetching, work, request, task)
    except TimeoutError as e:
        await _fail(engine, task, "timeout")
        raise ScrapeTimedOut(request.timeout_s) from e
    except ScrapeRejected as e:
        await _fail(engine, task, e.reason)
        raise
    except ScrapeInvalid:
        await _fail(engine, task, "invalid_schema")
        raise
    except LLMFailure as e:
        await _fail(engine, task, e.code)
        raise


async def _named_schema(engine: AsyncEngine, request: ScrapeRequest, data: EngineData | None) -> SchemaDef | None:
    """The schema `records` extracts with when the request names it by id or inline; None without `records`, and
    for a prompt, whose draft needs the page."""
    if "records" not in request.formats:
        return None
    if data is None:
        raise RecordsUnavailable("this process has not loaded the engine's data files")
    match request.schema_:
        case SchemaById(id=schema_id):
            async with engine.connect() as conn:
                try:
                    schema = await get_by_id(conn, schema_id)
                except SchemaNotFound as e:
                    raise ScrapeInvalid(str(e)) from e
            _check_usable(schema, request.page_kind)
            return schema
        case SchemaInline(inline=inline):
            async with engine.begin() as conn:
                return await schemas.inline(conn, inline)
    return None


def _check_usable(schema: SchemaDef, page_kind: PageKind | None) -> None:
    if schema.status == "retired":
        raise ScrapeInvalid(f"schema {schema.name} version {schema.version} is retired")
    if schema.page_kind != page_kind:
        raise ScrapeInvalid(f"schema {schema.name} is for {schema.page_kind} pages, not {page_kind}")


async def _start(engine: AsyncEngine, request: ScrapeRequest, schema: SchemaDef | None) -> ClaimedTask:
    """The running job, with its task claimed by this process. Committed on its own, so that a scrape that fails
    or times out can still record that on them."""
    async with engine.begin() as conn:
        job_id = (
            await conn.execute(
                pg_insert(Job)
                .values(
                    project_id=_DEFAULT_PROJECT,
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
        canonical = canonical_url(request.url, None) or request.url
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
    async with engine.begin() as conn:
        site = await _site(conn, host)
        row = await _recent_capture(conn, site.id, task.canonical_url, request.max_age) if request.max_age else None
        config = await _config(conn, site.id, work)
    recent = None if row is None else await _reread(fetching.store, row)
    policy = _policy(request, site.proxy_pool)
    fetches: list[FetchResult] = []
    page = recent.result if recent else await _fetch(engine, fetching, request.url, host, policy, site, fetches)
    # Formats, the draft and the extraction come before the write, so a timeout or an LLM failure while they are made
    # still finds the task claimed. They are made only from a page that was reached (§4.8: no partial formats).
    derived = _NOTHING
    if isinstance(page, FetchResult) and page.block_class == "ok":
        derived = await _derive(engine, work, request, task, page, config)
    members, records = _NOT_FETCHED, None
    async with engine.begin() as conn:
        if isinstance(page, FetchResult):
            capture_id = recent.capture_id if recent else await _new_capture(conn, fetching.store, site.id, page)
            outcome, records = await _finish(conn, task, site.id, page, capture_id, derived, work.margins)
            members = _fetch_members(page, capture_id)
        else:
            outcome = "blocked"
            await complete_task(conn, task, outcome, reason=page)
        await _record_usage(conn, task.job_id, fetches, policy.proxy_pool)
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
        **members,
        **derived.formats,
    )


_CaptureRow = Row[CaptureId, str, int, dict[str, Any]]


async def _recent_capture(conn: AsyncConnection, site_id: SiteId, canonical: str, max_age: int) -> _CaptureRow | None:
    """The latest capture of `canonical` that reached its page (§4.8) within `max_age` seconds and has not expired.
    Captures are found through the tasks that fetched them, which hold the canonical URL."""
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


async def _new_capture(conn: AsyncConnection, store: ObjectStore, site_id: SiteId, page: FetchResult) -> CaptureId:
    await remember_fetch_method(conn, site_id, page)
    return await store_capture(conn, store, page, site_id)


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
    result: FetchResult,
    config: ActiveConfig | None,
) -> _Derived:
    """The requested formats, the draft of a prompt, and the extraction for `records`, from one parse of the page
    (INV-26), with the site's active `config` when there is one."""
    page = ParsedPage.of(result.bundle)
    prompt = request.schema_.prompt if isinstance(request.schema_, SchemaPrompt) else None
    final_url = result.bundle.manifest.final_url
    formats, sample = await asyncio.to_thread(_content, page, final_url, request.formats, sample=prompt is not None)
    drafted = None
    if prompt is not None and sample is not None:
        # Role S's one sample page is the page's cleaned text (SPEC-06 §4.5).
        drafted = await draft_schema(engine, work.llm, prompt=prompt, samples=[sample], job_id=task.job_id)
    schema = work.schema if drafted is None else drafted
    if "records" not in request.formats or schema is None or work.data is None:
        return _Derived(formats, drafted)
    if drafted is not None:
        _check_usable(drafted, request.page_kind)
        config = None
    # Role C is bound here when SPEC-06 PR 4 adds it.
    executor = None if config is None else config.executor
    extraction = await extract_page(result.bundle, schema, executor, None, data=work.data, parsed=page)
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


async def _site(conn: AsyncConnection, host: str) -> _SiteRow:
    """The site of `host`, created in the default project the first time it is scraped."""
    await conn.execute(
        pg_insert(Site)
        .values(project_id=_DEFAULT_PROJECT, host=host)
        .on_conflict_do_nothing(index_elements=[Site.host])
    )
    columns = (Site.id, Site.fetch_method, Site.proxy_pool, Site.robots_snapshot, Site.crawl_delay_ms)
    return (await conn.execute(select(*columns).where(Site.host == host))).one()


def _policy(request: ScrapeRequest, site_pool: str | None) -> FetchPolicy:
    options = request.fetch
    return FetchPolicy(
        method_hint=options.method_hint,
        proxy_pool=options.proxy_pool or site_pool,
        respect_robots=options.respect_robots,
        robots_override_reason=options.robots_override_reason,
        locale_hint=request.locale,
    )


async def _fetch(
    engine: AsyncEngine,
    fetching: Fetching,
    url: str,
    host: str,
    policy: FetchPolicy,
    site: _SiteRow,
    fetches: list[FetchResult],
) -> FetchResult | str:
    """The page as fetched, or why robots.txt kept it from being fetched (SPEC-02 §4.6). Every fetch made,
    robots.txt's too, is added to `fetches`."""

    async def fetch_robots(robots_url: str) -> FetchResult:
        result = await fetching.rungs.http(robots_url, policy)
        fetches.append(result)
        return result

    robots: Robots | None = None
    if policy.respect_robots:
        async with engine.begin() as conn:
            robots = await site_robots(conn, site.id, site.robots_snapshot, url, fetch_robots)
        # RFC 9309 §2.3.1.4: an unreachable robots.txt allows nothing.
        if robots is None:
            return "robots_unreachable"
        if not robots.allows(url):
            return "robots"
    await _admitted(fetching.limiter, host, site.crawl_delay_ms, robots)
    result = await acquire(url, policy, site.fetch_method, fetching.rungs)
    fetches.append(result)
    for attempt in result.attempts:
        if (attempt.error or "").startswith(SSRF_REJECTED):
            raise ScrapeRejected(attempt.error or "")
    return result


async def _admitted(limiter: HostLimiter, host: str, crawl_delay_ms: int | None, robots: Robots | None) -> None:
    """Wait until the site's rate admits a request (SPEC-02 §4.6). The caller is waiting anyway, so the scrape waits
    in place, within its timeout, where a worker would postpone the task."""
    gap = interval(crawl_delay_ms, None if robots is None else robots.crawl_delay)
    while wait := limiter.admit(host, gap):
        await asyncio.sleep(wait.total_seconds())


async def _finish(
    conn: AsyncConnection,
    task: ClaimedTask,
    site_id: SiteId,
    result: FetchResult,
    capture_id: CaptureId,
    derived: _Derived,
    margins: DriftMargins | None,
) -> tuple[ScrapeOutcome, list[ScrapedRecord] | None]:
    """Settle the task with the page's outcome, after storing its extraction and record when `records` asked, and
    the page's run of an active config in its drift window."""
    outcome = _OUTCOMES[result.block_class]
    if outcome == "failed":
        error = result.attempts[-1].error or outcome
        await fail_task(conn, task, error, transient=False, capture_id=capture_id)
        return outcome, None
    if derived.extraction is None or derived.schema is None:
        await complete_task(conn, task, outcome, capture_id=capture_id)
        return outcome, None
    stored = await store_extraction(
        conn,
        task,
        derived.extraction,
        capture_id=capture_id,
        site_id=site_id,
        schema=derived.schema,
        caller_supplied=True,
        config_version=None if derived.config is None else derived.config.version,
    )
    if derived.config is not None:
        await record_page(conn, derived.config, derived.extraction, margins=margins, job_id=task.job_id)
    if not stored.records:
        # A scrape URL is caller-supplied, so a page it reached has a record unless resolution failed (SPEC-05 §4.14).
        await fail_task(conn, task, "extraction_error", transient=False, capture_id=capture_id)
        return "failed", None
    # Records of a detail page only: the request refuses listing records (`_records_have_a_schema`).
    stored_record = stored.records[0]
    outcome = "extracted" if stored_record.draft.complete else "partial"
    await complete_task(conn, task, outcome, capture_id=capture_id)
    await _count_page(conn, site_id, derived.schema)
    record = ScrapedRecord.of(
        stored_record.id,
        stored_record.draft,
        mode=derived.extraction.mode,
        confidence=derived.extraction.record_confidence,
    )
    return outcome, [record]


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


def _content(
    page: ParsedPage, final_url: str, requested: list[ScrapeFormat], *, sample: bool
) -> tuple[_Formats, str | None]:
    """The requested content formats of the page and, when `sample`, its cleaned text."""
    return _formats(page, final_url, requested), page.cleaned_text.text if sample else None


def _formats(page: ParsedPage, final_url: str, requested: list[ScrapeFormat]) -> _Formats:
    formats: _Formats = {}
    if "markdown" in requested:
        formats["markdown"] = markdown(page)
    if "html" in requested:
        formats["html"] = cleaned_html(page)
    if "raw_html" in requested:
        formats["raw_html"] = page.html
    if "links" in requested:
        formats["links"] = list(links(page, final_url))
    if "metadata" in requested:
        formats["metadata"] = metadata(page, final_url)
    return formats


async def _record_usage(
    conn: AsyncConnection, job_id: JobId, fetches: list[FetchResult], proxy_pool: str | None
) -> None:
    for result in fetches:
        for attempt in result.attempts:
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


async def _usage(conn: AsyncConnection, job_id: JobId) -> Usage:
    used: dict[str, int] = (await conn.execute(select(Job.usage).where(Job.id == job_id))).scalar_one()
    return Usage.model_validate({name: used[name] for name in Usage.model_fields if name in used})
