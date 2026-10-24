"""`POST /v1/search`: the search service over HTTP. With `scrape`, the results are scraped by a batch job:
its status is `GET /v1/jobs/{id}` and what it made `GET /v1/jobs/{id}/results`."""

from typing import Annotated

from fastapi import APIRouter, Depends

from snowcrawl.api.auth import caller, require_api_key
from snowcrawl.api.dto import PROBLEM_RESPONSE
from snowcrawl.api.problems import ProblemError
from snowcrawl.api.submissions import submission_problems
from snowcrawl.search.providers import SearchFailed
from snowcrawl.services import search as search_service
from snowcrawl.services.runtime import Caller
from snowcrawl.services.search import SearchRequest, SearchResult, SearchUnavailable

router = APIRouter(
    prefix="/v1/search",
    tags=["search"],
    dependencies=[Depends(require_api_key)],
    responses={401: PROBLEM_RESPONSE, 422: PROBLEM_RESPONSE, 429: PROBLEM_RESPONSE},
)


@router.post("", responses={409: PROBLEM_RESPONSE, 502: PROBLEM_RESPONSE, 503: PROBLEM_RESPONSE})
async def search(body: SearchRequest, caller: Annotated[Caller, Depends(caller)]) -> SearchResult:
    """The web results of `query` from the configured provider: `url`, `title` and `snippet`, in its order, at most
    `limit`. With `scrape`, a batch job scrapes the results (`job_id`); a result the API may not fetch is counted in
    `skipped`. 503 `search_unavailable` when no provider is configured, 502 when the provider does not answer."""
    runtime = caller.runtime
    try:
        with submission_problems():
            return await search_service.search(
                runtime.database,
                runtime.fetching.connector,
                runtime.search,
                body,
                data=runtime.engine_data,
                llm=runtime.llm,
                api_key_id=caller.api_key_id,
                egresses=runtime.fetching.egresses,
            )
    except SearchUnavailable as e:
        raise ProblemError(503, "search_unavailable", "Search unavailable", str(e)) from e
    except SearchFailed as e:
        raise ProblemError(502, "search_failed", "Search failed", str(e)) from e
