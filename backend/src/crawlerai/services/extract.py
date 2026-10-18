"""The extract service (SPEC-10 §4.6, ARCHITECTURE §13.1): records of one page kind from URLs and URL globs, as one
job of kind `extract` with a `url_task` per page. Workers run the tasks as they run a records batch's
(`crawlerai.worker.handlers.scrape`), and `GET /v1/jobs/{id}/results` returns the records.

A URL with a `*` is a glob (`is_glob`), expanded through `map` on its host (§4.4): the URLs the host's
sitemaps and start page give that the glob matches. The tasks are the given URLs, then each glob's URLs, once each in
canonical form, cut at `limit`. Every URL is caller-supplied, those a glob gave too (ARCHITECTURE §10): a page whose
required fields don't all publish keeps its record, `complete=false`, with outcome `partial`.

The schema is named by id or given inline, or drafted from a `prompt` by role S (SPEC-06 §4.5) while the caller
waits: from the cleaned text of the first pages, up to three, of those reached among the first three task URLs. The
draft is returned with the job. Field names are drafted from the names alone, before anything is stored (SPEC-14
§4.10). Each task is extracted in its site's progressive mode (ARCHITECTURE §8.3): the job
pins the engine data and the configs active when it was submitted (INV-28), and its pages count toward the site's
learning trigger (SPEC-08 §4.4).

Submitting checks every URL, each glob's origin and `webhook_url` with the SSRF guard first (INV-16), and the fetches
of a map or a draft go through it too. Nothing is stored for a refused target, an unusable schema, or no URL to
extract (beyond the `map` jobs of the globs). A prompt's job is stored before its draft, which charges the job's
`budget`, and is `failed` when the draft cannot be made: no sample page reached, a refused redirect, an LLM failure,
a draft of another page kind, or the timeout.
"""

import asyncio
import itertools
from collections import Counter
from typing import Final, Self, cast
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.content.page import ParsedPage
from crawlerai.core.errors import Refusal
from crawlerai.crawl.rules import MAX_PATTERNS, UrlGlob, is_glob, url_glob
from crawlerai.db.jobs import transition_job
from crawlerai.db.models import ApiKeyId, Job, JobId, PageKind, ScheduleId, SiteId
from crawlerai.llm.client import LLMClient
from crawlerai.llm.roles.s_labels import with_labels
from crawlerai.llm.roles.s_schema import MAX_SAMPLES, draft_schema
from crawlerai.normalize.url_key import canonicalize
from crawlerai.resolve.pipeline import EngineData
from crawlerai.resolve.types import Probability
from crawlerai.schemas.types import SchemaDef
from crawlerai.services.batch import MAX_URLS, OWN_TRANSACTION, Placement, insert_job, insert_tasks, job_pins
from crawlerai.services.fetch_options import check_proxy_pool
from crawlerai.services.fetching import Fetching, PagePlan, check_targets, fetch_now, site_rungs
from crawlerai.services.map import MapRequest, map_urls
from crawlerai.services.scrape import MAX_TIMEOUT_S, Budget, RecordsUnavailable
from crawlerai.services.scrape_steps import (
    MIN_CONFIDENCE_DESCRIPTION,
    FetchOptions,
    SchemaPrompt,
    SchemaRequest,
    check_records,
    check_usable,
    fetch_policy,
    named_schema,
    record_fetch_usage,
    site_row,
)
from crawlerai.services.stored_captures import recent_capture, reread
from crawlerai.services.webhook_options import WebhookOptions

# The bound on a prompt's draft, its sample fetches included: the longest a scrape may wait (D-0028).
DRAFT_TIMEOUT_S: Final = float(MAX_TIMEOUT_S)


class ExtractRequest(WebhookOptions):
    """The body of `POST /v1/extract` (§4.6). `urls` are URLs and URL globs; `schema` names a schema by id, gives it
    inline, or asks for a draft from a `prompt` or from field names (`fields`, SPEC-14 §4.10), and its page kind must
    be `page_kind`. `limit` bounds the job's tasks; `budget.llm_calls` (else the project's cap) bounds a prompt's
    draft. The `fetch` and `locale` are a scrape's (SPEC-07 §4.4), for every URL. The webhook options are
    `WebhookOptions` (§4.2)."""

    urls: list[str] = Field(min_length=1, max_length=MAX_URLS)
    schema_: SchemaRequest = Field(alias="schema")
    page_kind: PageKind
    limit: int = Field(default=MAX_URLS, ge=1, le=MAX_URLS)
    fetch: FetchOptions = FetchOptions()
    locale: str | None = None
    budget: Budget | None = None
    min_confidence: Probability | None = Field(default=None, description=MIN_CONFIDENCE_DESCRIPTION)

    @field_validator("urls")
    @classmethod
    def _urls_and_globs(cls, urls: list[str]) -> list[str]:
        origins: Counter[str] = Counter()
        for index, url in enumerate(urls):
            if not is_glob(url):
                if canonicalize(url) is None:
                    raise ValueError(f"urls[{index}] is not an absolute http or https URL")
            elif (glob := url_glob(url)) is None:
                raise ValueError(f"urls[{index}] is not a glob on one http or https host")
            else:
                origins[glob.origin] += 1
        if any(count > MAX_PATTERNS for count in origins.values()):
            raise ValueError(f"at most {MAX_PATTERNS} globs per host: a host's globs are its map's include")
        return urls

    @model_validator(mode="after")
    def _schema_of_the_page_kind(self) -> Self:
        check_records(["records"], self.schema_, self.page_kind)
        return self

    def globs(self) -> list[UrlGlob | None]:
        """Per URL of `urls`, its glob on its origin; None for a URL that is not a glob."""
        return [url_glob(url) if is_glob(url) else None for url in self.urls]

    def targets(self) -> list[tuple[str, str]]:
        """What the SSRF guard checks of `urls`, by member: each URL, and each glob's origin."""
        return [
            (f"urls[{index}]", url if glob is None else glob.origin)
            for index, (url, glob) in enumerate(zip(self.urls, self.globs(), strict=True))
        ]


class ExtractSubmitted(BaseModel):
    """The queued job, and the schema its records are extracted with: a prompt's draft, or the schema named."""

    model_config = ConfigDict(frozen=True, validate_by_name=True, serialize_by_alias=True)

    job_id: JobId
    schema_: SchemaDef = Field(alias="schema")


class NothingToExtract(Refusal):
    """The request's globs matched no URL, and it gives no other."""


class NoSamplePage(Refusal):
    """None of the pages a prompt is drafted from was reached (SPEC-06 §4.5: role S drafts from fetched pages)."""


class DraftTimedOut(Refusal):
    def __init__(self, timeout_s: float) -> None:
        super().__init__(f"the draft did not finish within {timeout_s:g} s")


async def submit_extract(
    engine: AsyncEngine,
    fetching: Fetching,
    request: ExtractRequest,
    *,
    llm: LLMClient,
    data: EngineData | None,
    api_key_id: ApiKeyId | None = None,
    draft_timeout_s: float = DRAFT_TIMEOUT_S,
    placement: Placement = OWN_TRANSACTION,
) -> ExtractSubmitted:
    """Store `request` as a queued job with its tasks, where `placement` says (a prompt's job, stored before its
    draft, always in transactions of its own); `api_key_id`, the key that submitted it, signs its webhook (§4.2).
    Raises, storing no extract job: `UnknownProxyPool` for a proxy pool not configured (D-1434), `TargetsRejected` for
    a refused target, `RecordsUnavailable` without `data`, `named_schema`'s errors for a schema that cannot be used (or
    field names `llm` could not draft), `TargetRejected` for a refused fetch of a map, and `NothingToExtract`. Raises,
    failing the job: `NoSamplePage`, `TargetRejected` for a refused redirect, the LLM client's `LLMFailure`,
    `SchemaUnusable` for a draft of another page kind, and `DraftTimedOut`."""
    check_proxy_pool(request.fetch, fetching.proxy_pools)
    await check_targets(fetching.connector, request.targets(), webhook_url=request.webhook_url)
    if data is None:
        raise RecordsUnavailable("this process has not loaded the engine's data files")
    schema = await named_schema(engine, request.schema_, request.page_kind, llm)
    urls = await _task_urls(engine, fetching, request)
    if not urls:
        raise NothingToExtract("the request's globs matched no URL")
    if schema is None:
        # `named_schema` returns the schema of every request but a prompt's.
        prompt = cast(SchemaPrompt, request.schema_).prompt
        return await _drafted(engine, fetching, llm, request, prompt, urls, data, api_key_id, draft_timeout_s)
    async with placement.transaction(engine) as conn:
        job_id = await _insert_job(conn, request, schema, data, urls, api_key_id, placement.schedule_id)
        await insert_tasks(conn, job_id, request.page_kind, _pairs(urls))
    return ExtractSubmitted(job_id=job_id, schema_=schema)


async def _task_urls(engine: AsyncEngine, fetching: Fetching, request: ExtractRequest) -> dict[str, str]:
    """The job's task URLs by canonical form, in order: the given URLs, then each glob's, at most `limit`. The globs
    of one origin are expanded by one map, and the origins' maps run at once (politeness is per host)."""
    globs = request.globs()
    patterns: dict[str, list[str]] = {}
    for glob in filter(None, globs):
        patterns.setdefault(glob.origin, []).append(glob.pattern)
    expanded = await asyncio.gather(
        *(_expand(engine, fetching, origin, include, request.limit) for origin, include in patterns.items())
    )
    urls: dict[str, str] = {}
    # The request's validator refuses a URL that is not a glob and has no canonical form.
    given = ((url, canonicalize(url) or url) for url, glob in zip(request.urls, globs, strict=True) if glob is None)
    for url, canonical in itertools.chain(given, *expanded):
        if len(urls) == request.limit:
            break
        urls.setdefault(canonical, url)
    return urls


async def _expand(
    engine: AsyncEngine, fetching: Fetching, origin: str, include: list[str], limit: int
) -> list[tuple[str, str]]:
    """The URLs that a map of `origin` finds and its globs, `include`, match; a map's URLs are canonical (§4.4), so
    each is its own canonical form."""
    found = await map_urls(engine, fetching, MapRequest(url=origin, include=include, limit=limit))
    return [(url, url) for url in found.urls]


async def _insert_job(
    conn: AsyncConnection,
    request: ExtractRequest,
    schema: SchemaDef | None,
    data: EngineData | None,
    urls: dict[str, str],
    api_key_id: ApiKeyId | None,
    schedule_id: ScheduleId | None = None,
) -> JobId:
    return await insert_job(
        conn,
        "extract",
        request,
        schema=schema,
        data=data,
        urls=list(urls.values()),
        api_key_id=api_key_id,
        schedule_id=schedule_id,
    )


async def _drafted(
    engine: AsyncEngine,
    fetching: Fetching,
    llm: LLMClient,
    request: ExtractRequest,
    prompt: str,
    urls: dict[str, str],
    data: EngineData,
    api_key_id: ApiKeyId | None,
    timeout_s: float,
) -> ExtractSubmitted:
    """The job of a prompt, stored and started before its draft, which charges its usage and budget, then given the
    draft, its pins and its tasks; it fails when no draft is made. A job that ended during the draft (a cancel, or
    `fail_stalled_jobs`) is given no tasks: they would run for a job that has ended."""
    async with engine.begin() as conn:
        job_id = await _insert_job(conn, request, None, None, urls, api_key_id)
        await transition_job(conn, job_id, "running")
    try:
        async with asyncio.timeout(timeout_s):
            samples = await _samples(engine, fetching, request, job_id, list(urls.values())[:MAX_SAMPLES])
            drafted = await draft_schema(engine, llm, prompt=prompt, samples=samples, job_id=job_id)
        check_usable(drafted, request.page_kind)
        drafted = await with_labels(engine, llm, drafted)
    except Exception as e:
        async with engine.begin() as conn:
            await transition_job(conn, job_id, "failed")
        if isinstance(e, TimeoutError):
            raise DraftTimedOut(timeout_s) from e
        raise
    async with engine.begin() as conn:
        # FOR NO KEY UPDATE, as `settle_job` takes: a cancel waits for the tasks, or the tasks see the cancel.
        locked = select(Job.status).where(Job.id == job_id).with_for_update(key_share=True)
        if (await conn.execute(locked)).scalar_one() == "running":
            pinned = await job_pins(conn, data, list(urls.values()), drafted)
            await conn.execute(update(Job).where(Job.id == job_id).values(schema_id=drafted.id, pinned=pinned))
            await insert_tasks(conn, job_id, request.page_kind, _pairs(urls))
    return ExtractSubmitted(job_id=job_id, schema_=drafted)


async def _samples(
    engine: AsyncEngine, fetching: Fetching, request: ExtractRequest, job_id: JobId, urls: list[str]
) -> list[str]:
    """The cleaned text of each of `urls` reached, fetched one after another as a scrape fetches its page; the fetches
    count as the job's usage. With `fetch.cache` `only`, each is the latest stored capture of its URL made with the
    request's steps and context, and nothing is fetched (jobs spec, "Request context and actions per page"); a URL
    without one is no sample. Raises `NoSamplePage` when none was reached."""
    samples: list[str] = []
    for url in urls:
        host = urlsplit(url).hostname or ""
        async with engine.begin() as conn:
            site = await site_row(conn, host, request.page_kind)
        policy = fetch_policy(
            request.fetch,
            request.locale,
            site.proxy_pool,
            page_kind=request.page_kind,
            all_resources=site.load_all_resources,
        )
        page: FetchResult | str | None
        if request.fetch.cache == "only":
            page = await _stored_sample(engine, fetching, site.id, url, policy)
        else:
            page = await _fetched_sample(
                engine, fetching, job_id, url, PagePlan(site_rungs(fetching, host, site), site, policy, [])
            )
        if isinstance(page, FetchResult) and page.block_class == "ok":
            # Parsing and rendering the text are CPU work: a thread keeps the event loop free.
            samples.append(await asyncio.to_thread(_cleaned_text, page))
    if not samples:
        raise NoSamplePage("none of the pages to draft the schema from was reached")
    return samples


async def _fetched_sample(
    engine: AsyncEngine, fetching: Fetching, job_id: JobId, url: str, page: PagePlan
) -> FetchResult | str:
    """The sample page at `url` fetched as a scrape fetches its page (`fetch_now`), its attempts counted as the job's
    usage."""
    try:
        return await fetch_now(engine, fetching, url, page)
    finally:
        async with engine.begin() as conn:
            await record_fetch_usage(conn, job_id, page.attempts, page.policy.proxy_pool)


async def _stored_sample(
    engine: AsyncEngine, fetching: Fetching, site_id: SiteId, url: str, policy: FetchPolicy
) -> FetchResult | None:
    """The latest stored capture of `url` made with `policy`'s steps and context, of any age (`recent_capture`), or None
    without one."""
    async with engine.connect() as conn:
        row = await recent_capture(conn, site_id, canonicalize(url) or url, policy, max_age=None)
    recent = None if row is None else await reread(fetching.store, row)
    return None if recent is None else recent.result


def _pairs(urls: dict[str, str]) -> list[tuple[str, str]]:
    """(URL, canonical URL) pairs of the task URLs, kept by canonical form."""
    return [(url, canonical) for canonical, url in urls.items()]


def _cleaned_text(page: FetchResult) -> str:
    # Role S's sample pages are their cleaned text (SPEC-06 §4.5).
    return ParsedPage.of(page.bundle).cleaned_text.text
