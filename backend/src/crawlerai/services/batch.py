"""The batch scrape service: many URLs scraped asynchronously, as one job of kind
`batch_scrape` with a `url_task` per URL. Workers run the tasks with the steps a scrape takes
(`crawlerai.worker.handlers.scrape`), and `GET /v1/jobs/{id}/results` returns what they made.

Submitting checks every target with the SSRF guard, each URL by its form alone (`check_targets`: one refused
only once its host is resolved fails its own task), and resolves the schema, then stores the job and its tasks in one
transaction. The job pins what its pages run with: for `records`, the schema's document as it is
at submit, the precedence orders and calibration of this process's engine data, and the active config each URL's site
has for the schema and page kind (`job.pinned`, `JobPins`). A URL given twice
(the same once canonicalized) is one task. URLs are caller-supplied: a page whose required fields don't all publish
keeps its record, `complete=false`, with outcome `partial`.
"""

from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Final, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.content.chunks import ChunkOptions
from crawlerai.content.fit import FitOptions
from crawlerai.core.egress import UNKNOWN, Egress, Egresses
from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.db.models import (
    ApiKeyId,
    ExtractionConfig,
    ExtractionConfigId,
    Job,
    JobId,
    JobKind,
    PageKind,
    ScheduleId,
    Site,
    UrlTask,
)
from crawlerai.llm.client import NO_LLM, LLMClient
from crawlerai.normalize.url_key import canonicalize
from crawlerai.resolve.pipeline import EngineData, PinnedData
from crawlerai.resolve.types import Probability
from crawlerai.schemas.types import SchemaDef
from crawlerai.services.fetch_options import KEEP_SECRETS, FetchOptions, check_proxy_pool
from crawlerai.services.fetching import check_targets
from crawlerai.services.location import job_egress
from crawlerai.services.page_store import DEFAULT_PROJECT
from crawlerai.services.scrape import Budget, RecordsUnavailable
from crawlerai.services.scrape_request import (
    MIN_CONFIDENCE_DESCRIPTION,
    RENDER_DESCRIPTION,
    PageFormat,
    RenderOptions,
    SchemaById,
    SchemaFields,
    SchemaInline,
    check_formats,
    check_records,
    check_render,
    named_schema,
    stored_request,
)
from crawlerai.services.webhook_options import WebhookOptions

MAX_URLS: Final = 1000


class BatchScrapeRequest(WebhookOptions):
    """The body of `POST /v1/batch/scrape`. The formats, `schema`, `page_kind`, `fetch` and `locale` are a
    scrape's, for every URL. A batch's results are either records or page outputs, so `records` is
    asked alone; a `schema.prompt` is not taken (its draft needs a fetched page, which a batch does not wait for),
    and `schema.fields` is drafted while the caller waits. Role C fills a page's gaps as in a scrape;
    `budget.llm_calls` bounds the job's calls, and without a `budget` the project's cap does, as for every job
    kind. The webhook options are `WebhookOptions`."""

    urls: list[str] = Field(min_length=1, max_length=MAX_URLS)
    formats: list[PageFormat] = Field(min_length=1)
    schema_: SchemaById | SchemaInline | SchemaFields | None = Field(default=None, alias="schema")
    page_kind: PageKind | None = None
    fetch: FetchOptions = FetchOptions()
    locale: str | None = None
    budget: Budget | None = None
    fit: FitOptions | None = None  # `markdown_fit`'s query and block limit
    chunking: ChunkOptions | None = None  # `chunks`' strategy, size and overlap
    min_confidence: Probability | None = Field(default=None, description=MIN_CONFIDENCE_DESCRIPTION)
    render: RenderOptions = Field(default=RenderOptions(), description=RENDER_DESCRIPTION)

    @field_validator("urls")
    @classmethod
    def _absolute_http_urls(cls, urls: list[str]) -> list[str]:
        for index, url in enumerate(urls):
            if canonicalize(url) is None:
                raise ValueError(f"urls[{index}] is not an absolute http or https URL")
        return urls

    @model_validator(mode="after")
    def _records_alone_with_a_schema(self) -> Self:
        check_records(self.formats, self.schema_, self.page_kind)
        check_formats(self.formats, self.fetch, self.fit, self.chunking)
        if "records" in self.formats and len(set(self.formats)) > 1:
            raise ValueError("records are asked alone: a batch's results are records or page outputs")
        return self


@dataclass(frozen=True)
class Placement:
    """Where a submission stores its job: in a transaction of its own, or, for a schedule's run, in `into`, the open
    transaction that also moves the schedule on, so the job is stored exactly when the run is (`services.schedules`).
    `schedule_id` names that schedule on the job."""

    into: AsyncConnection | None = None
    schedule_id: ScheduleId | None = None

    @asynccontextmanager
    async def transaction(self, engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
        if self.into is not None:
            yield self.into
            return
        async with engine.begin() as conn:
            yield conn


# A submission a caller makes: its job stored in a transaction of its own.
OWN_TRANSACTION: Final = Placement()


class JobPins(BaseModel):
    """What a records job pins when it is submitted: the job's schema as it is then, so an edit made while
    the job runs applies to later jobs only; the engine data's precedence orders and calibration; and per host the
    config that was active for the schema and page kind. A host without one has its pages extracted cold (`adhoc`) for
    the whole job, even if a config activates while it runs."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_by_name=True, serialize_by_alias=True)

    schema_: SchemaDef = Field(alias="schema")
    engine_data: PinnedData
    configs: dict[str, ExtractionConfigId]


class BatchSubmitted(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: JobId


async def submit_batch(
    engine: AsyncEngine,
    connector: SafeConnector,
    request: BatchScrapeRequest,
    *,
    data: EngineData | None,
    llm: LLMClient = NO_LLM,
    api_key_id: ApiKeyId | None = None,
    egresses: Egresses | None = None,
    placement: Placement = OWN_TRANSACTION,
) -> BatchSubmitted:
    """Store `request` as a queued job with its tasks, where `placement` says; `api_key_id`, the key that submitted
        it, signs its webhook; `egresses`, the configured pools, one of which `fetch.proxy_pool` must name,
    and the countries they go out from. The job's egress is its pool's (`job_egress`). Raises, storing
        nothing: `UnknownProxyPool` for another pool, `TargetsRejected` for a URL refused by its form or a refused
        `webhook_url` (`check_targets`), `RecordsUnavailable` for `records` without `data`, and `named_schema`'s errors for
        a schema `records` cannot use (or field names `llm` could not draft)."""
    if egresses is not None:
        check_proxy_pool(request.fetch, egresses.pools)
    targets = [(f"urls[{index}]", url) for index, url in enumerate(request.urls)]
    # A schedule's run checks its targets in full: a refused run stores no job (schedules).
    queued = {member for member, _ in targets} if placement.schedule_id is None else set()
    await check_targets(connector, targets, webhook_url=request.webhook_url, queued=queued)
    # A format batch that names a schema is a format job.
    schema = await records_schema(
        engine, request.formats, request.schema_, request.page_kind, data, llm, request.render
    )
    egress = job_egress(egresses, request.fetch)
    async with placement.transaction(engine) as conn:
        job_id = await insert_job(
            conn,
            "batch_scrape",
            request,
            schema=schema,
            data=data,
            urls=request.urls,
            api_key_id=api_key_id,
            schedule_id=placement.schedule_id,
            egress=egress,
        )
        urls = [(url, canonicalize(url) or url) for url in request.urls]
        await insert_tasks(conn, job_id, request.page_kind, urls)
    return BatchSubmitted(job_id=job_id)


async def insert_tasks(
    conn: AsyncConnection, job_id: JobId, page_kind: PageKind | None, urls: Iterable[tuple[str, str]]
) -> None:
    """Queue a task of `page_kind` per (URL, canonical URL) of `urls`; a canonical URL given twice is one task."""
    rows = [
        {"job_id": job_id, "url": url, "canonical_url": canonical, "page_kind": page_kind} for url, canonical in urls
    ]
    await conn.execute(
        pg_insert(UrlTask).values(rows).on_conflict_do_nothing(index_elements=[UrlTask.job_id, UrlTask.canonical_url])
    )


async def records_schema(
    engine: AsyncEngine,
    formats: list[PageFormat],
    schema: SchemaById | SchemaInline | SchemaFields | None,
    page_kind: PageKind | None,
    data: EngineData | None,
    llm: LLMClient,
    render: RenderOptions,
) -> SchemaDef | None:
    """The schema a job's `records` are extracted with; None without `records`, the only format that reads a schema.
    Raises `RecordsUnavailable` without `data`, `named_schema`'s errors, and `check_render`'s for
        `render.fields` the schema does not have."""
    if "records" not in formats:
        return None
    if data is None:
        raise RecordsUnavailable("this process has not loaded the engine's data files")
    named = await named_schema(engine, schema, page_kind, llm)
    check_render(render, named)
    return named


async def insert_job(
    conn: AsyncConnection,
    kind: JobKind,
    request: WebhookOptions,
    *,
    schema: SchemaDef | None,
    data: EngineData | None,
    urls: list[str],
    api_key_id: ApiKeyId | None,
    schedule_id: ScheduleId | None,
    egress: Egress = UNKNOWN,
) -> JobId:
    """Insert `request` as a queued job of `kind`, with its webhook options; `schedule_id` names the schedule that
    submitted it, `egress` the country its fetches go out from (`job_egress`). A records job (`schema`) pins its
    engine data and the configs active for the hosts of `urls` (`JobPins`)."""
    pinned = None if schema is None or data is None else await job_pins(conn, data, urls, schema)
    statement = (
        insert(Job)
        .values(
            project_id=DEFAULT_PROJECT,
            kind=kind,
            # The caller's secrets stay in the stored request, which the job's workers read.
            request=stored_request(request, context={KEEP_SECRETS: True}),
            schema_id=None if schema is None else schema.id,
            webhook_url=request.webhook_url,
            webhook_events=request.webhook_events,
            webhook_batch=None if request.webhook_batch is None else request.webhook_batch.model_dump(),
            api_key_id=api_key_id,
            engine_version=ENGINE_VERSION,
            pinned=pinned,
            schedule_id=schedule_id,
            egress_country=egress.country,
            egress_basis=egress.basis,
        )
        .returning(Job.id)
    )
    job_id: JobId = (await conn.execute(statement)).scalar_one()
    return job_id


async def job_pins(conn: AsyncConnection, data: EngineData, urls: list[str], schema: SchemaDef) -> dict[str, Any]:
    """What a records job of `schema` over `urls` pins (`JobPins`), as `job.pinned` stores it."""
    pins = JobPins(schema_=schema, engine_data=data.pin(), configs=await active_configs(conn, urls, schema))
    return pins.model_dump(mode="json")


async def active_configs(conn: AsyncConnection, urls: list[str], schema: SchemaDef) -> dict[str, ExtractionConfigId]:
    """Per host of `urls`, the config active for `schema` and its page kind, where its site has one."""
    hosts = {urlsplit(url).hostname or "" for url in urls}
    configs = ExtractionConfig
    rows = await conn.execute(
        select(Site.host, configs.id)
        .join(configs, configs.site_id == Site.id)
        .where(
            Site.host.in_(hosts),
            configs.schema_id == schema.id,
            configs.page_kind == schema.page_kind,
            configs.status == "active",
        )
    )
    return dict(rows.tuples().all())
