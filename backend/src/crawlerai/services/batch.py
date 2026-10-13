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

import asyncio
from typing import Final, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.acquire.ssrf import SafeConnector, SsrfRejected
from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.db.models import ExtractionConfig, ExtractionConfigId, Job, JobId, PageKind, Site, UrlTask
from crawlerai.normalize.url import canonical_url
from crawlerai.resolve.pipeline import EngineData, PinnedData
from crawlerai.schemas.types import SchemaDef
from crawlerai.services.scrape import RecordsUnavailable
from crawlerai.services.scrape_steps import (
    DEFAULT_PROJECT,
    FetchOptions,
    Input,
    PageFormat,
    SchemaById,
    SchemaInline,
    check_records,
    named_schema,
)

MAX_URLS: Final = 1000  # SPEC-10 §4.3


def _absolute_http_url(url: str) -> str:
    if canonical_url(url, None) is None:
        raise ValueError("not an absolute http or https URL")
    return url


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
        return None if url is None else _absolute_http_url(url)

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


class BatchRejected(Exception):
    """The SSRF guard refused a target (INV-16): `member` names it (`urls[3]`, `webhook_url`), `reason` is the
    guard's, without the URL."""

    def __init__(self, member: str, reason: str) -> None:
        super().__init__(f"{member}: {reason}")
        self.member = member
        self.reason = reason


async def submit_batch(
    engine: AsyncEngine, connector: SafeConnector, request: BatchScrapeRequest, *, data: EngineData | None
) -> BatchSubmitted:
    """Store `request` as a queued job with its tasks. Raises, storing nothing: `BatchRejected` for a refused target,
    `RecordsUnavailable` for `records` without `data`, and `named_schema`'s errors for a schema `records` cannot use."""
    await _check_targets(connector, request)
    if "records" in request.formats and data is None:
        raise RecordsUnavailable("this process has not loaded the engine's data files")
    schema = await named_schema(engine, request.schema_, request.page_kind)
    async with engine.begin() as conn:
        pinned = None
        if schema is not None and data is not None:
            pins = JobPins(engine_data=data.pin(), configs=await _active_configs(conn, request.urls, schema))
            pinned = pins.model_dump(mode="json")
        job_id: JobId = (
            await conn.execute(
                insert(Job)
                .values(
                    project_id=DEFAULT_PROJECT,
                    kind="batch_scrape",
                    request=request.model_dump(mode="json", by_alias=True),
                    schema_id=None if schema is None else schema.id,
                    webhook_url=request.webhook_url,
                    engine_version=ENGINE_VERSION,
                    pinned=pinned,
                )
                .returning(Job.id)
            )
        ).scalar_one()
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


async def _active_configs(conn: AsyncConnection, urls: list[str], schema: SchemaDef) -> dict[str, ExtractionConfigId]:
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
    return {host: config_id for host, config_id in rows}


async def _check_targets(connector: SafeConnector, request: BatchScrapeRequest) -> None:
    targets = [(f"urls[{index}]", url) for index, url in enumerate(request.urls)]
    if request.webhook_url is not None:
        targets.append(("webhook_url", request.webhook_url))
    checked = await asyncio.gather(*(connector.check(url) for _, url in targets), return_exceptions=True)
    for (member, _), result in zip(targets, checked, strict=True):
        if isinstance(result, SsrfRejected):
            raise BatchRejected(member, str(result))
        if isinstance(result, BaseException):
            raise result
