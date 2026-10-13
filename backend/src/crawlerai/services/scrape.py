"""The scrape service (SPEC-07 §4.4, §4.7): one URL fetched while the caller waits, and returned in the content formats
it asks for. `POST /v1/scrape` calls it; the MCP `scrape` tool will (SPEC-10).

A scrape is a `job` of kind `scrape` with one `url_task`, run here rather than through the queue, so its usage and
events are kept like any job's. The task is fetched as a worker fetches one: robots.txt, the site's rate, the rungs
(SPEC-02). A fetch that does not reach the page is an outcome, not an error (§4.8). The whole scrape is bounded by
`timeout_s`; past it the job fails and nothing is returned. A target the SSRF guard refuses is never fetched (INV-16).
"""

import asyncio
import math
import os
import socket
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal, Self, TypedDict
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, field_validator, model_validator
from sqlalchemy import Row, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.acquire.persist import store_capture
from crawlerai.acquire.politeness import HostLimiter, interval
from crawlerai.acquire.robots import Robots, site_robots
from crawlerai.acquire.rungs import Rungs, acquire, remember_fetch_method
from crawlerai.acquire.ssrf import SSRF_REJECTED, SafeConnector, SsrfRejected
from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult, check_robots_override
from crawlerai.content.html import cleaned_html
from crawlerai.content.links import links
from crawlerai.content.markdown import markdown
from crawlerai.content.metadata import PageMetadata, metadata
from crawlerai.content.page import ParsedPage
from crawlerai.core.capture import BlockClass, CaptureMethod
from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.db.models import (
    CaptureId,
    FetchMethod,
    Job,
    JobId,
    PageKind,
    Project,
    SchemaId,
    Site,
    SiteId,
    UsageResource,
)
from crawlerai.db.queue import ClaimedTask, complete_task, fail_task, insert_claimed
from crawlerai.db.usage import record_usage
from crawlerai.normalize.url import canonical_url
from crawlerai.services.schemas import NewSchema
from crawlerai.storage.base import ObjectStore

ScrapeFormat = Literal["markdown", "html", "raw_html", "links", "metadata", "records"]
# `url_task.outcome` as a scrape reports it (§4.4).
ScrapeOutcome = Literal["extracted", "partial", "blocked", "shell", "not_found", "failed"]

MAX_TIMEOUT_S: Final = 120  # D-0028
_OUTCOMES: Final[dict[BlockClass, ScrapeOutcome]] = {
    # Without `records` the page is extracted once it is fetched; PR 5 adds `partial` for records.
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


class _Input(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SchemaById(_Input):
    id: SchemaId


class SchemaInline(_Input):
    inline: NewSchema


class SchemaPrompt(_Input):
    prompt: str = Field(min_length=1)


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
    """The body of `POST /v1/scrape` (§4.4). `records`, with `schema`, `page_kind` and `budget`, is SPEC-07 PR 5;
    `max_age` reuses a recent capture from PR 5, and until then every scrape fetches anew, which any `max_age`
    allows."""

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

    @field_validator("formats")
    @classmethod
    def _formats_available(cls, formats: list[ScrapeFormat]) -> list[ScrapeFormat]:
        if "records" in formats:
            raise ValueError("the records format is not available yet")
        return formats


def _absent(value: object) -> bool:
    return value is None


def _never_null(schema: dict[str, Any]) -> None:
    # A format's member is left out rather than null, so the document gives it no null branch and no default.
    (branch,) = (branch for branch in schema.pop("anyOf") if branch.get("type") != "null")
    schema.update(branch)
    del schema["default"]


def _format() -> Any:
    """A format's member: in the answer only when the format was requested (§4.4)."""
    return Field(default=None, exclude_if=_absent, json_schema_extra=_never_null)


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
    `capture_id`, `final_url`, `fetched_at` and `fetch` are None."""

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


_SiteRow = Row[SiteId, FetchMethod, str | None, str | None, int | None]


@dataclass(frozen=True)
class _Fetched:
    result: FetchResult
    capture_id: CaptureId


class _FetchMembers(TypedDict):
    capture_id: CaptureId | None
    final_url: str | None
    fetched_at: datetime | None
    fetch: FetchSummary | None


_NOT_FETCHED = _FetchMembers(capture_id=None, final_url=None, fetched_at=None, fetch=None)


async def scrape(engine: AsyncEngine, fetching: Fetching, request: ScrapeRequest) -> ScrapeResult:
    """Run `request` as a scrape job. Raises `ScrapeRejected` when the target is refused, before any job is created
    for a target refused outright, and `ScrapeTimedOut` past `request.timeout_s`; the job is failed in both cases."""
    try:
        await fetching.connector.check(request.url)
    except SsrfRejected as e:
        raise ScrapeRejected(str(e)) from e
    task = await _start(engine, request)
    try:
        async with asyncio.timeout(request.timeout_s):
            return await _run(engine, fetching, request, task)
    except TimeoutError as e:
        await _fail(engine, task, "timeout")
        raise ScrapeTimedOut(request.timeout_s) from e
    except ScrapeRejected as e:
        await _fail(engine, task, e.reason)
        raise


async def _start(engine: AsyncEngine, request: ScrapeRequest) -> ClaimedTask:
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
                    status="running",
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


async def _run(engine: AsyncEngine, fetching: Fetching, request: ScrapeRequest, task: ClaimedTask) -> ScrapeResult:
    """The fetch runs outside any transaction, so a slow page holds no connection or row lock; what it found is
    written in one transaction after it."""
    host = urlsplit(request.url).hostname or ""
    async with engine.begin() as conn:
        site = await _site(conn, host)
    policy = _policy(request, site.proxy_pool)
    fetches: list[FetchResult] = []
    page = await _fetch(engine, fetching, request.url, host, policy, site, fetches)
    members = _NOT_FETCHED
    async with engine.begin() as conn:
        if isinstance(page, FetchResult):
            await remember_fetch_method(conn, site.id, page)
            fetched = _Fetched(page, await store_capture(conn, fetching.store, page, site.id))
            outcome = await _finish(conn, task, fetched)
            members = _fetch_members(fetched)
        else:
            outcome = "blocked"
            await complete_task(conn, task, outcome, reason=page)
        await _record_usage(conn, task.job_id, fetches, policy.proxy_pool)
        usage = await _usage(conn, task.job_id)
    # Formats are computed only from a page that was reached (§4.8: no partial formats on failure).
    formats = _Formats()
    if isinstance(page, FetchResult) and outcome == "extracted":
        formats = await asyncio.to_thread(_formats, page, request.formats)
    return ScrapeResult(job_id=task.job_id, url=request.url, outcome=outcome, usage=usage, **members, **formats)


def _fetch_members(fetched: _Fetched) -> _FetchMembers:
    manifest = fetched.result.bundle.manifest
    return _FetchMembers(
        capture_id=fetched.capture_id,
        final_url=manifest.final_url,
        fetched_at=manifest.fetched_at,
        fetch=FetchSummary(
            method=manifest.method,
            status_code=manifest.status_code or None,
            block_class=manifest.block_class,
            attempts=fetched.result.attempts,
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


async def _finish(conn: AsyncConnection, task: ClaimedTask, fetched: _Fetched) -> ScrapeOutcome:
    outcome = _OUTCOMES[fetched.result.block_class]
    if outcome == "failed":
        error = fetched.result.attempts[-1].error or outcome
        await fail_task(conn, task, error, transient=False, capture_id=fetched.capture_id)
    else:
        await complete_task(conn, task, outcome, capture_id=fetched.capture_id)
    return outcome


def _formats(result: FetchResult, requested: list[ScrapeFormat]) -> _Formats:
    """The requested content formats of the page, from one parse of its body (INV-26)."""
    page = ParsedPage.of(result.bundle)
    final_url = result.bundle.manifest.final_url
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
