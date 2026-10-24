"""The crawl service: a site's pages, found from a start URL and its
sitemaps and followed through their links, as one job of kind `crawl`. Workers run its tasks
(`snowcrawl.worker.handlers.crawl`), which grow the frontier (`snowcrawl.crawl.frontier`), and
`GET /v1/jobs/{id}/results` returns what they made.

Submitting checks the start URL and `webhook_url` with the SSRF guard and resolves the schema, then stores
the job and its first task, the start URL at depth 0, in one transaction. A records crawl pins what its pages run
with as a batch does (`JobPins`), the active config of the start URL's site included.

A task whose URL matches a page-kind rule is extracted with that page kind; one no rule matches is crawled for its
links only (`links_only`), unless the crawl has no rules, when every page has the formats asked. Crawl URLs
are crawl-discovered: a page whose required fields don't all publish ends `no_match`, without a record.
"""

from typing import Any, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from snowcrawl.acquire.ssrf import SafeConnector
from snowcrawl.content.chunks import ChunkOptions
from snowcrawl.content.fit import FitOptions
from snowcrawl.core.egress import Egresses
from snowcrawl.crawl.frontier import Frontier
from snowcrawl.crawl.rules import PageKindRule, Patterns, Scope
from snowcrawl.crawl.scoring import Strategy, query_terms
from snowcrawl.db.models import ApiKeyId, JobId, UrlTask
from snowcrawl.llm.client import NO_LLM, LLMClient
from snowcrawl.normalize.url_key import canonicalize
from snowcrawl.resolve.pipeline import EngineData
from snowcrawl.resolve.types import Probability
from snowcrawl.services.batch import OWN_TRANSACTION, Placement, insert_job, records_schema
from snowcrawl.services.fetch_options import FetchOptions, check_proxy_pool
from snowcrawl.services.fetching import check_targets
from snowcrawl.services.location import job_egress
from snowcrawl.services.map import MAX_LIMIT  # a crawl enqueues at most what a map of the site returns
from snowcrawl.services.scrape import Budget
from snowcrawl.services.scrape_request import (
    MIN_CONFIDENCE_DESCRIPTION,
    RENDER_AS_GIVEN,
    RENDER_DESCRIPTION,
    PageFormat,
    RenderOptions,
    SchemaById,
    SchemaFields,
    SchemaInline,
    absolute_http_url,
    check_formats,
    check_records,
    render_as_given,
)
from snowcrawl.services.webhook_options import WebhookOptions


class CrawlRequest(WebhookOptions):
    """The body of `POST /v1/crawl`. The formats, `schema`, `fetch` and `locale` are a batch's, for every
        page the crawl extracts: `records` is asked alone, a `schema.prompt` is not taken, and `schema.fields` is
        drafted
        while the caller waits. `budget.llm_calls` bounds the job's LLM calls, and without a `budget` the project's cap
        does.
    `include` and `exclude` globs scope the URLs followed, as `map`'s do; `page_kind_rules` decide which
        pages are extracted. The webhook options are `WebhookOptions`.

        `strategy` orders the frontier: `bfs` (breadth first), `dfs` (deepest first) or `best_first`, which leases the
        links that best match `query` and `keywords` first (`crawl.scoring`). `allow_subdomains`
        keeps the start host's subdomains without an `include`, and `allow_external` any host."""

    url: str
    include: Patterns = Field(default_factory=list)
    exclude: Patterns = Field(default_factory=list)
    max_depth: int = Field(default=3, ge=0)
    limit: int = Field(default=500, ge=1, le=MAX_LIMIT, description="At most this many pages are fetched.")
    strategy: Strategy = "bfs"
    query: str | None = Field(default=None, max_length=500)
    keywords: list[str] = Field(default_factory=list, max_length=20)
    allow_subdomains: bool = False
    allow_external: bool = False
    formats: list[PageFormat] = Field(min_length=1)
    schema_: SchemaById | SchemaInline | SchemaFields | None = Field(default=None, alias="schema")
    page_kind_rules: list[PageKindRule] = Field(default_factory=list)
    fetch: FetchOptions = FetchOptions()
    locale: str | None = None
    budget: Budget | None = None
    fit: FitOptions | None = None  # `markdown_fit`'s query and block limit
    chunking: ChunkOptions | None = None  # `chunks`' strategy, size and overlap
    min_confidence: Probability | None = Field(default=None, description=MIN_CONFIDENCE_DESCRIPTION)
    render: RenderOptions = Field(default=RenderOptions(), description=RENDER_DESCRIPTION)

    model_config = RENDER_AS_GIVEN
    _render_as_given = model_serializer(mode="wrap")(render_as_given)

    @model_validator(mode="before")
    @classmethod
    def _max_pages_is_limit(cls, data: Any) -> Any:
        """`max_pages` is accepted as `limit`; a before-validator,
        so the OpenAPI schema and the clients generated from it name `limit` only, and the schema does not advertise the
        alias."""
        if isinstance(data, dict) and "max_pages" in data:
            if "limit" in data:
                raise ValueError("give limit or its alias max_pages, not both")
            return {key if key != "max_pages" else "limit": value for key, value in data.items()}
        return data

    @model_validator(mode="after")
    def _query_orders_best_first(self) -> Self:
        if self.strategy != "best_first" and (self.query or self.keywords):
            raise ValueError("query and keywords order a best_first crawl: set strategy to best_first")
        if self.strategy == "best_first" and self.query is not None and not query_terms(self.query, self.keywords):
            raise ValueError("the query has no words")
        return self

    @field_validator("url")
    @classmethod
    def _absolute_start_url(cls, url: str) -> str:
        return absolute_http_url(url)

    @model_validator(mode="after")
    def _records_have_rules_of_the_schemas_kind(self) -> Self:
        check_formats(self.formats, self.fetch, self.fit, self.chunking)
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
        host of the same site (RFC 9110 §15.4), else on the start URL's."""
        host = urlsplit(located or self.start).hostname or ""
        scope = Scope(host, tuple(self.include), tuple(self.exclude), self.allow_subdomains, self.allow_external)
        wanted = query_terms(self.query, self.keywords)
        start = urlsplit(self.start)
        home = (
            f"{start.scheme}://{start.netloc}{start.path.rsplit('/', 1)[0]}/" if self.strategy == "best_first" else ""
        )
        return Frontier(scope, tuple(self.page_kind_rules), self.max_depth, self.limit, self.strategy, wanted, home)


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
    egresses: Egresses | None = None,
    placement: Placement = OWN_TRANSACTION,
) -> CrawlSubmitted:
    """Store `request` as a queued job with the start URL's task, where `placement` says; `api_key_id`, the key that
        submitted it, signs its webhook; `egresses`, the configured pools, one of which `fetch.proxy_pool` must name,
    and the countries they go out from. The job's egress is its pool's (`job_egress`). Raises, storing
        nothing: `UnknownProxyPool` for another pool, `TargetsRejected` for a refused target, `RecordsUnavailable` for
        `records` without `data`, and `named_schema`'s errors for a schema `records` cannot use."""
    if egresses is not None:
        check_proxy_pool(request.fetch, egresses.pools)
    await check_targets(connector, [("url", request.url)], webhook_url=request.webhook_url)
    # A records crawl's rules have one page kind, its schema's (the request's validator).
    page_kind = request.page_kind_rules[0].page_kind if request.page_kind_rules else None
    schema = await records_schema(engine, request.formats, request.schema_, page_kind, data, llm, request.render)
    frontier = request.frontier()
    egress = job_egress(egresses, request.fetch)
    async with placement.transaction(engine) as conn:
        job_id = await insert_job(
            conn,
            "crawl",
            request,
            schema=schema,
            data=data,
            urls=[request.start],
            api_key_id=api_key_id,
            schedule_id=placement.schedule_id,
            egress=egress,
        )
        # The start URL is fetched whatever the scope: `include` and `exclude` choose the URLs it leads to.
        await conn.execute(insert(UrlTask).values(frontier.task_row(job_id, request.start, 0, None)))
    return CrawlSubmitted(job_id=job_id)
