"""The batch scrape service (SPEC-10 §4.3, ARCHITECTURE §13.1): many URLs scraped asynchronously, as one job of kind
`batch_scrape` with a `url_task` per URL. Workers run the tasks with the steps a scrape takes
(`crawlerai.worker.handlers.scrape`), and `GET /v1/jobs/{id}/results` returns what they made.

Submitting checks every target with the SSRF guard (INV-16) and resolves the schema, then stores the job and its tasks
in one transaction. The job pins what its pages run with (INV-28): for `records`, the schema's document as it is
at submit, the precedence orders and calibration of this process's engine data, and the active config each URL's site
has for the schema and page kind (`job.pinned`, `JobPins`). A URL given twice
(the same once canonicalized) is one task. URLs are caller-supplied: a page whose required fields don't all publish
keeps its record, `complete=false`, with outcome `partial` (ARCHITECTURE §10).
"""

from collections.abc import Collection, Iterable
from typing import Any, Final, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.content.chunks import ChunkOptions
from crawlerai.content.fit import FitOptions
from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.db.models import (
    ApiKeyId,
    ExtractionConfig,
    ExtractionConfigId,
    Job,
    JobId,
    JobKind,
    PageKind,
    Site,
    UrlTask,
)
from crawlerai.llm.client import NO_LLM, LLMClient
from crawlerai.normalize.url_key import canonicalize
from crawlerai.resolve.pipeline import EngineData, PinnedData
from crawlerai.schemas.types import SchemaDef
from crawlerai.services.fetch_options import KEEP_SECRETS, check_proxy_pool
from crawlerai.services.fetching import check_targets
from crawlerai.services.scrape import Budget, RecordsUnavailable
from crawlerai.services.scrape_steps import (
    DEFAULT_PROJECT,
    FetchOptions,
    Input,
    PageFormat,
    SchemaById,
    SchemaFields,
    SchemaInline,
    absolute_http_url,
    check_formats,
    check_records,
    named_schema,
)

MAX_URLS: Final = 1000  # SPEC-10 §4.3


class BatchScrapeRequest(Input):
    """The body of `POST /v1/batch/scrape` (§4.3). The formats, `schema`, `page_kind`, `fetch` and `locale` are a
    scrape's (SPEC-07 §4.4), for every URL. A batch's results are either records or page outputs, so `records` is
    asked alone; a `schema.prompt` is not taken (its draft needs a fetched page, which a batch does not wait for),
    and `schema.fields` is drafted while the caller waits (SPEC-14 §4.10). Role C fills a page's gaps as in a scrape;
    `budget.llm_calls` bounds the job's calls, and without a `budget` the project's cap does, as for every job
    kind (D-1006, D-1121). `webhook_url` is called when the job ends (§4.2)."""

    urls: list[str] = Field(min_length=1, max_length=MAX_URLS)
    formats: list[PageFormat] = Field(min_length=1)
    schema_: SchemaById | SchemaInline | SchemaFields | None = Field(default=None, alias="schema")
    page_kind: PageKind | None = None
    fetch: FetchOptions = FetchOptions()
    locale: str | None = None
    budget: Budget | None = None
    webhook_url: str | None = None
    fit: FitOptions | None = None  # `markdown_fit`'s query and block limit
    chunking: ChunkOptions | None = None  # `chunks`' strategy, size and overlap

    @field_validator("urls")
    @classmethod
    def _absolute_http_urls(cls, urls: list[str]) -> list[str]:
        for index, url in enumerate(urls):
            if canonicalize(url) is None:
                raise ValueError(f"urls[{index}] is not an absolute http or https URL")
        return urls

    @field_validator("webhook_url")
    @classmethod
    def _absolute_webhook_url(cls, url: str | None) -> str | None:
        return None if url is None else absolute_http_url(url)

    @model_validator(mode="after")
    def _records_alone_with_a_schema(self) -> Self:
        check_records(self.formats, self.schema_, self.page_kind)
        check_formats(self.formats, self.fetch, self.fit, self.chunking)
        if "records" in self.formats and len(set(self.formats)) > 1:
            raise ValueError("records are asked alone: a batch's results are records or page outputs")
        return self


class JobPins(BaseModel):
    """What a records job pins when it is submitted (INV-28): the job's schema as it is then, so an edit made while
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
    proxy_pools: Collection[str] | None = None,
) -> BatchSubmitted:
    """Store `request` as a queued job with its tasks; `api_key_id`, the key that submitted it, signs its webhook
    (SPEC-10 §4.2); `proxy_pools`, the configured pools, which `fetch.proxy_pool` must name one of (D-1434). Raises,
    storing nothing: `UnknownProxyPool` for another pool, `TargetsRejected` for a refused target,
    `RecordsUnavailable` for `records` without `data`, and `named_schema`'s errors for a schema `records` cannot use
    (or field names `llm` could not draft)."""
    if proxy_pools is not None:
        check_proxy_pool(request.fetch, proxy_pools)
    targets = [(f"urls[{index}]", url) for index, url in enumerate(request.urls)]
    await check_targets(connector, targets, webhook_url=request.webhook_url)
    # A format batch that names a schema is a format job.
    schema = await records_schema(engine, request.formats, request.schema_, request.page_kind, data, llm)
    async with engine.begin() as conn:
        job_id = await insert_job(
            conn,
            "batch_scrape",
            request,
            schema=schema,
            data=data,
            urls=request.urls,
            webhook_url=request.webhook_url,
            api_key_id=api_key_id,
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
) -> SchemaDef | None:
    """The schema a job's `records` are extracted with; None without `records`, the only format that reads a schema
    (SPEC-07 §4.4). Raises `RecordsUnavailable` without `data`, and `named_schema`'s errors."""
    if "records" not in formats:
        return None
    if data is None:
        raise RecordsUnavailable("this process has not loaded the engine's data files")
    return await named_schema(engine, schema, page_kind, llm)


async def insert_job(
    conn: AsyncConnection,
    kind: JobKind,
    request: Input,
    *,
    schema: SchemaDef | None,
    data: EngineData | None,
    urls: list[str],
    webhook_url: str | None,
    api_key_id: ApiKeyId | None,
) -> JobId:
    """Insert `request` as a queued job of `kind`. A records job (`schema`) pins its engine data and the configs
    active for the hosts of `urls` (INV-28, `JobPins`)."""
    pinned = None if schema is None or data is None else await job_pins(conn, data, urls, schema)
    statement = (
        insert(Job)
        .values(
            project_id=DEFAULT_PROJECT,
            kind=kind,
            # The caller's secrets stay in the stored request, which the job's workers read (D-1432).
            request=request.model_dump(mode="json", by_alias=True, context={KEEP_SECRETS: True}),
            schema_id=None if schema is None else schema.id,
            webhook_url=webhook_url,
            api_key_id=api_key_id,
            engine_version=ENGINE_VERSION,
            pinned=pinned,
        )
        .returning(Job.id)
    )
    job_id: JobId = (await conn.execute(statement)).scalar_one()
    return job_id


async def job_pins(conn: AsyncConnection, data: EngineData, urls: list[str], schema: SchemaDef) -> dict[str, Any]:
    """What a records job of `schema` over `urls` pins (INV-28, `JobPins`), as `job.pinned` stores it."""
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
