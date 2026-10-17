"""The search service (D-1442): the web results of a query from the operator's provider (`crawlerai.search`), found
while the caller waits, and, with `scrape`, scraped through a batch job (SPEC-10 §4.3) the answer names.

Without a configured provider the service raises `SearchUnavailable`. Result URLs are the provider's, not the caller's:
one the SSRF guard refuses (INV-16) stays in `results` but is not scraped, and the answer counts such URLs in `skipped`.
`scrape` takes a batch's members; its job is the batch job of the scrapable results, in the answer's order, `job_id`
none when no result could be scraped.
"""

from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.ssrf import SafeConnector, SsrfRejected
from crawlerai.core.errors import Refusal
from crawlerai.db.models import ApiKeyId, JobId, PageKind
from crawlerai.llm.client import NO_LLM, LLMClient
from crawlerai.resolve.pipeline import EngineData
from crawlerai.search.providers import SearchProvider
from crawlerai.services import batch
from crawlerai.services.batch import MAX_URLS, BatchScrapeRequest
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

MAX_LIMIT: Final = 50
MAX_QUERY_CHARS: Final = 500


class SearchUnavailable(Refusal):
    """No search provider is configured (`CRAWLERAI_SEARCH_SEARXNG_URL` or `CRAWLERAI_SEARCH_URL_TEMPLATE`)."""


class SearchScrape(Input):
    """How the results are scraped: a batch's `formats` (markdown when none), `schema`, `page_kind`, `fetch`,
    `locale`, `budget` and `webhook_url`, for every result (`BatchScrapeRequest`)."""

    formats: list[PageFormat] = Field(default=["markdown"], min_length=1)
    schema_: SchemaById | SchemaInline | SchemaFields | None = Field(default=None, alias="schema")
    page_kind: PageKind | None = None
    fetch: FetchOptions = FetchOptions()
    locale: str | None = None
    budget: Budget | None = None
    webhook_url: str | None = None

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


class SearchRequest(Input):
    """The body of `POST /v1/search`: `query`, at most `limit` results, and optionally how to `scrape` them."""

    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    limit: int = Field(default=10, ge=1, le=MAX_LIMIT)
    scrape: SearchScrape | None = None

    @field_validator("query")
    @classmethod
    def _has_text(cls, query: str) -> str:
        if not query.strip():
            raise ValueError("the query is empty")
        return query


class SearchHit(BaseModel):
    model_config = ConfigDict(frozen=True)

    position: int = Field(description="1-based, in the provider's order")
    url: str
    title: str
    snippet: str


class SearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: str
    results: list[SearchHit]
    job_id: JobId | None = Field(default=None, description="The batch job scraping the results, with `scrape`")
    skipped: int = Field(default=0, description="Results the API may not fetch, left out of the scrape")


async def search(
    engine: AsyncEngine,
    connector: SafeConnector,
    provider: SearchProvider | None,
    request: SearchRequest,
    *,
    data: EngineData | None,
    llm: LLMClient = NO_LLM,
    api_key_id: ApiKeyId | None = None,
) -> SearchResult:
    """The results of `request`, scraped when it says so. Raises `SearchUnavailable` without a provider,
    `SearchFailed` when it does not answer, and a batch's submission errors for `scrape`."""
    if provider is None:
        raise SearchUnavailable(
            "no search provider is configured: set CRAWLERAI_SEARCH_SEARXNG_URL or CRAWLERAI_SEARCH_URL_TEMPLATE"
        )
    hits = await provider.search(request.query, request.limit)
    results = [
        SearchHit(position=n, url=hit.url, title=hit.title, snippet=hit.snippet) for n, hit in enumerate(hits, 1)
    ]
    if request.scrape is None or not results:
        return SearchResult(query=request.query, results=results)
    scrapable = [hit.url for hit in results if await _allowed(connector, hit.url)][:MAX_URLS]
    if not scrapable:
        return SearchResult(query=request.query, results=results, skipped=len(results))
    body = BatchScrapeRequest.model_validate(
        {**request.scrape.model_dump(mode="json", by_alias=True, exclude_none=True), "urls": scrapable}
    )
    submitted = await batch.submit_batch(engine, connector, body, data=data, llm=llm, api_key_id=api_key_id)
    return SearchResult(
        query=request.query, results=results, job_id=submitted.job_id, skipped=len(results) - len(scrapable)
    )


async def _allowed(connector: SafeConnector, url: str) -> bool:
    try:
        await connector.check(url)
    except SsrfRejected:
        return False
    return True
