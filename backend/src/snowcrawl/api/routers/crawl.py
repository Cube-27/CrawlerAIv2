"""`POST /v1/crawl`: the crawl service over HTTP. The job runs in the workers; its status is
`GET /v1/jobs/{id}` and what it made `GET /v1/jobs/{id}/results`."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from snowcrawl.api.auth import caller, require_api_key
from snowcrawl.api.dto import PROBLEM_RESPONSE
from snowcrawl.api.submissions import submission_problems
from snowcrawl.services import crawl
from snowcrawl.services.crawl import CrawlRequest, CrawlSubmitted
from snowcrawl.services.runtime import Caller

router = APIRouter(
    prefix="/v1/crawl",
    tags=["crawl"],
    dependencies=[Depends(require_api_key)],
    responses={401: PROBLEM_RESPONSE, 422: PROBLEM_RESPONSE, 429: PROBLEM_RESPONSE},
)


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    responses={409: PROBLEM_RESPONSE, 502: PROBLEM_RESPONSE, 503: PROBLEM_RESPONSE},
)
async def crawl_site(body: CrawlRequest, caller: Annotated[Caller, Depends(caller)]) -> CrawlSubmitted:
    """Queue a job that crawls from `url`: its sitemaps and the links of each page, within `include` and `exclude`,
    `max_depth` and `limit`, on its host (and the subdomains an `include` names). A page a `page_kind_rules` pattern
    matches is extracted; with rules, any other page is fetched for its links only. `strategy` orders the visits: `bfs`
    (default), `dfs`, or `best_first`, which fetches the links that best match `query` and `keywords` first (anchor
    text and URL path against the query, the holding page's relevance, sitemap priority, shallower first);
    `allow_subdomains` and `allow_external` widen the host scope. Pages the `limit` leaves unfetched end `cancelled`.
    A target the API may not fetch, in `url` or `webhook_url`, is a 422 and nothing is queued."""
    runtime = caller.runtime
    with submission_problems():
        return await crawl.submit_crawl(
            runtime.database,
            runtime.fetching.connector,
            body,
            data=runtime.engine_data,
            llm=runtime.llm,
            api_key_id=caller.api_key_id,
            egresses=runtime.fetching.egresses,
        )
