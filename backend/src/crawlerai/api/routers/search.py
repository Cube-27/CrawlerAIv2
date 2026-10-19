"""`POST /v1/search` (D-1442): the search service over HTTP. With `scrape`, the results are scraped by a batch job:
its status is `GET /v1/jobs/{id}` and what it made `GET /v1/jobs/{id}/results`."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from crawlerai.api.auth import require_api_key
from crawlerai.api.database import database
from crawlerai.api.dto import PROBLEM_RESPONSE
from crawlerai.api.problems import ProblemError
from crawlerai.api.submissions import submission_problems
from crawlerai.db.models import ApiKeyId
from crawlerai.llm.draft_cap import KeyCapped
from crawlerai.resolve.pipeline import EngineData
from crawlerai.search.providers import SearchFailed, SearchProvider
from crawlerai.services import search as search_service
from crawlerai.services.fetching import Fetching
from crawlerai.services.search import SearchRequest, SearchResult, SearchUnavailable

router = APIRouter(
    prefix="/v1/search",
    tags=["search"],
    dependencies=[Depends(require_api_key)],
    responses={401: PROBLEM_RESPONSE, 422: PROBLEM_RESPONSE, 429: PROBLEM_RESPONSE},
)


@router.post("", responses={409: PROBLEM_RESPONSE, 502: PROBLEM_RESPONSE, 503: PROBLEM_RESPONSE})
async def search(
    body: SearchRequest, request: Request, key: Annotated[ApiKeyId, Depends(require_api_key)]
) -> SearchResult:
    """The web results of `query` from the configured provider: `url`, `title` and `snippet`, in its order, at most
    `limit`. With `scrape`, a batch job scrapes the results (`job_id`); a result the API may not fetch is counted in
    `skipped`. 503 `search_unavailable` when no provider is configured, 502 when the provider does not answer."""
    fetching: Fetching = request.app.state.fetching
    provider: SearchProvider | None = request.app.state.search
    data: EngineData | None = request.app.state.engine_data
    llm = KeyCapped(request.app.state.llm, database(request), key)
    try:
        with submission_problems():
            return await search_service.search(
                database(request),
                fetching.connector,
                provider,
                body,
                data=data,
                llm=llm,
                api_key_id=key,
                egresses=fetching.egresses,
            )
    except SearchUnavailable as e:
        raise ProblemError(503, "search_unavailable", "Search unavailable", str(e)) from e
    except SearchFailed as e:
        raise ProblemError(502, "search_failed", "Search failed", str(e)) from e
