"""The crawl service (SPEC-10 §4.5, ARCHITECTURE §13.1, §13.2): a site's pages, found from a start URL and its
sitemaps and followed through their links, as one job of kind `crawl`. Workers run its tasks
(`crawlerai.worker.handlers.crawl`), which grow the frontier (`crawlerai.crawl.frontier`), and
`GET /v1/jobs/{id}/results` returns what they made.

Submitting checks the start URL and `webhook_url` with the SSRF guard (INV-16) and resolves the schema, then stores
the job and its first task, the start URL at depth 0, in one transaction. A records crawl pins what its pages run
with as a batch does (INV-28, `JobPins`), the active config of the start URL's site included.

A task whose URL matches a page-kind rule is extracted with that page kind; one no rule matches is crawled for its
links only (`links_only`, §13.2), unless the crawl has no rules, when every page has the formats asked. Crawl URLs
are crawl-discovered: a page whose required fields don't all publish ends `no_match`, without a record (§10, §23).
"""

from typing import Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.crawl.canonical import canonicalize
from crawlerai.crawl.frontier import Frontier
from crawlerai.crawl.rules import PageKindRule, Patterns, Scope
from crawlerai.db.models import ApiKeyId, JobId, UrlTask
from crawlerai.llm.client import NO_LLM, LLMClient
from crawlerai.resolve.pipeline import EngineData
from crawlerai.services.batch import insert_job, records_schema
from crawlerai.services.fetching import check_targets
from crawlerai.services.map import MAX_LIMIT  # a crawl enqueues at most what a map of the site returns
from crawlerai.services.scrape import Budget
from crawlerai.services.scrape_steps import (
    FetchOptions,
    Input,
    PageFormat,
    SchemaById,
    SchemaFields,
    SchemaInline,
    absolute_http_url,
    check_records,
)


class CrawlRequest(Input):
    """The body of `POST /v1/crawl` (§4.5). The formats, `schema`, `fetch` and `locale` are a batch's (§4.3), for every
    page the crawl extracts: `records` is asked alone, a `schema.prompt` is not taken, and `schema.fields` is drafted
    while the caller waits. `budget.llm_calls` bounds the job's LLM calls, and without a `budget` the project's cap does
    (D-1286). `include` and `exclude` globs scope the URLs followed, as `map`'s do; `page_kind_rules` decide which
    pages are extracted. `webhook_url` is called when the job ends (§4.2)."""

    url: str
    include: Patterns = Field(default_factory=list)
    exclude: Patterns = Field(default_factory=list)
    max_depth: int = Field(default=3, ge=0)
    limit: int = Field(default=500, ge=1, le=MAX_LIMIT)
    formats: list[PageFormat] = Field(min_length=1)
    schema_: SchemaById | SchemaInline | SchemaFields | None = Field(default=None, alias="schema")
    page_kind_rules: list[PageKindRule] = Field(default_factory=list)
    fetch: FetchOptions = FetchOptions()
    locale: str | None = None
    budget: Budget | None = None
    webhook_url: str | None = None

    @field_validator("url")
    @classmethod
    def _absolute_start_url(cls, url: str) -> str:
        return absolute_http_url(url)

    @field_validator("webhook_url")
    @classmethod
    def _absolute_webhook_url(cls, url: str | None) -> str | None:
        return None if url is None else absolute_http_url(url)

    @model_validator(mode="after")
    def _records_have_rules_of_the_schemas_kind(self) -> Self:
        if "records" not in self.formats:
            return self
        if len(set(self.formats)) > 1:
            raise ValueError("records are asked alone: a crawl's results are records or page outputs")
        kinds = {rule.page_kind for rule in self.page_kind_rules}
        if not kinds:
            raise ValueError("the records format needs page_kind_rules: a page no rule matches is not extracted")
        if len(kinds) > 1:
            raise ValueError("the records format takes rules of one page kind, the schema's")
        check_records(self.formats, self.schema_, kinds.pop())
        return self

    @property
    def start(self) -> str:
        """The start URL in canonical form (the validator refuses one without)."""
        return canonicalize(self.url) or self.url

    def frontier(self, located: str | None = None) -> Frontier:
        """The crawl's frontier, on the host of `located`, where the start page is after the site's own redirects to a
        host of the same site (RFC 9110 §15.4; D-0991), else on the start URL's. A `located` that is not the start URL
        is a page already fetched, which the frontier never adds again."""
        scope = Scope(urlsplit(located or self.start).hostname or "", tuple(self.include), tuple(self.exclude))
        fetched = located if located != self.start else None
        return Frontier(scope, tuple(self.page_kind_rules), self.max_depth, self.limit, fetched)


class CrawlSubmitted(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: JobId


async def submit_crawl(
    engine: AsyncEngine,
    connector: SafeConnector,
    request: CrawlRequest,
    *,
    data: EngineData | None,
    llm: LLMClient = NO_LLM,
    api_key_id: ApiKeyId | None = None,
) -> CrawlSubmitted:
    """Store `request` as a queued job with the start URL's task; `api_key_id`, the key that submitted it, signs its
    webhook (§4.2). Raises, storing nothing: `TargetsRejected` for a refused target, `RecordsUnavailable` for `records`
    without `data`, and `named_schema`'s errors for a schema `records` cannot use."""
    await check_targets(connector, [("url", request.url)], webhook_url=request.webhook_url)
    # A records crawl's rules have one page kind, its schema's (the request's validator).
    page_kind = request.page_kind_rules[0].page_kind if request.page_kind_rules else None
    schema = await records_schema(engine, request.formats, request.schema_, page_kind, data, llm)
    frontier = request.frontier()
    async with engine.begin() as conn:
        job_id = await insert_job(
            conn,
            "crawl",
            request,
            schema=schema,
            data=data,
            urls=[request.start],
            webhook_url=request.webhook_url,
            api_key_id=api_key_id,
        )
        # The start URL is fetched whatever the scope: `include` and `exclude` choose the URLs it leads to.
        await conn.execute(insert(UrlTask).values(frontier.task_row(job_id, request.start, 0, None)))
    return CrawlSubmitted(job_id=job_id)
