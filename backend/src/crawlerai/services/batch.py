"""The batch scrape service (SPEC-10 §4.3, ARCHITECTURE §13.1): many URLs scraped asynchronously, as one job of kind
`batch_scrape` with a `url_task` per URL. Workers run the tasks with the steps a scrape takes
(`crawlerai.worker.handlers.scrape`), and `GET /v1/jobs/{id}/results` returns what they made.

Submitting checks every target with the SSRF guard (INV-16) and resolves the schema, then stores the job and its tasks
in one transaction. The job pins what its pages run with (INV-28): the schema version (`job.schema_id`) and, for
`records`, the precedence orders and calibration of this process's engine data, and the active config each URL's site
has for the schema version and page kind (`job.pinned`, `JobPins`). A URL given twice
(the same once canonicalized) is one task. URLs are caller-supplied: a page whose required fields don't all publish
keeps its record, `complete=false`, with outcome `partial` (ARCHITECTURE §10).
"""

from typing import Final, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.acquire.ssrf import SafeConnector
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
from crawlerai.normalize.url import canonical_url
from crawlerai.resolve.pipeline import EngineData, PinnedData
from crawlerai.schemas.types import SchemaDef
from crawlerai.services.fetching import check_targets
from crawlerai.services.scrape import RecordsUnavailable
from crawlerai.services.scrape_steps import (
    DEFAULT_PROJECT,
    FetchOptions,
    Input,
    PageFormat,
    SchemaById,
    SchemaInline,
    absolute_http_url,
    check_records,
    named_schema,
)

MAX_URLS: Final = 1000  # SPEC-10 §4.3


class BatchScrapeRequest(Input):
    """The body of `POST /v1/batch/scrape` (§4.3). The formats, `schema`, `page_kind`, `fetch` and `locale` are a
    scrape's (SPEC-07 §4.4), for every URL. A batch's results are either records or page outputs, so `records` is
    asked alone; a `schema.prompt` is not taken (its draft needs a fetched page, which a batch does not wait for).
    `webhook_url` is called when the job ends (§4.2)."""

    urls: list[str] = Field(min_length=1, max_length=MAX_URLS)
    formats: list[PageFormat] = Field(min_length=1)
    schema_: SchemaById | SchemaInline | None = Field(default=None, alias="schema")
    page_kind: PageKind | None = None
    fetch: FetchOptions = FetchOptions()
    locale: str | None = None
    webhook_url: str | None = None

    @field_validator("urls")
    @classmethod
    def _absolute_http_urls(cls, urls: list[str]) -> list[str]:
        for index, url in enumerate(urls):
            if canonical_url(url, None) is None:
                raise ValueError(f"urls[{index}] is not an absolute http or https URL")
        return urls

    @field_validator("webhook_url")
    @classmethod
    def _absolute_webhook_url(cls, url: str | None) -> str | None:
        return None if url is None else absolute_http_url(url)

    @model_validator(mode="after")
    def _records_alone_with_a_schema(self) -> Self:
        check_records(self.formats, self.schema_, self.page_kind)
        if "records" in self.formats and len(set(self.formats)) > 1:
            raise ValueError("records are asked alone: a batch's results are records or page outputs")
        return self


class JobPins(BaseModel):
    """What a records job pins when it is submitted (INV-28): the engine data's precedence orders and calibration,
    and per host the config that was active for the job's schema version and page kind. A host without one has its
    pages extracted cold (`adhoc`) for the whole job, even if a config activates while it runs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

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
    api_key_id: ApiKeyId | None = None,
) -> BatchSubmitted:
    """Store `request` as a queued job with its tasks; `api_key_id`, the key that submitted it, signs its webhook
    (SPEC-10 §4.2). Raises, storing nothing: `TargetsRejected` for a refused target,
    `RecordsUnavailable` for `records` without `data`, and `named_schema`'s errors for a schema `records` cannot use."""
    targets = [(f"urls[{index}]", url) for index, url in enumerate(request.urls)]
    await check_targets(connector, targets, webhook_url=request.webhook_url)
    # A format batch that names a schema is a format job.
    schema = await records_schema(engine, request.formats, request.schema_, request.page_kind, data)
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
        rows = [
            {
                "job_id": job_id,
                "url": url,
                "canonical_url": canonical_url(url, None) or url,
                "page_kind": request.page_kind,
            }
            for url in request.urls
        ]
        await conn.execute(
            pg_insert(UrlTask)
            .values(rows)
            .on_conflict_do_nothing(index_elements=[UrlTask.job_id, UrlTask.canonical_url])
        )
    return BatchSubmitted(job_id=job_id)


async def records_schema(
    engine: AsyncEngine,
    formats: list[PageFormat],
    schema: SchemaById | SchemaInline | None,
    page_kind: PageKind | None,
    data: EngineData | None,
) -> SchemaDef | None:
    """The schema a job's `records` are extracted with; None without `records`, the only format that reads a schema
    (SPEC-07 §4.4). Raises `RecordsUnavailable` without `data`, and `named_schema`'s errors."""
    if "records" not in formats:
        return None
    if data is None:
        raise RecordsUnavailable("this process has not loaded the engine's data files")
    return await named_schema(engine, schema, page_kind)


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
    pinned = None
    if schema is not None and data is not None:
        pins = JobPins(engine_data=data.pin(), configs=await active_configs(conn, urls, schema))
        pinned = pins.model_dump(mode="json")
    statement = (
        insert(Job)
        .values(
            project_id=DEFAULT_PROJECT,
            kind=kind,
            request=request.model_dump(mode="json", by_alias=True),
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


async def active_configs(conn: AsyncConnection, urls: list[str], schema: SchemaDef) -> dict[str, ExtractionConfigId]:
    """Per host of `urls`, the config active for `schema`'s version and page kind, where its site has one."""
    hosts = {urlsplit(url).hostname or "" for url in urls}
    configs = ExtractionConfig
    rows = await conn.execute(
        select(Site.host, configs.id)
        .join(configs, configs.site_id == Site.id)
        .where(
            Site.host.in_(hosts),
            configs.schema_id == schema.id,
            configs.schema_version == schema.version,
            configs.page_kind == schema.page_kind,
            configs.status == "active",
        )
    )
    return dict(rows.tuples().all())
