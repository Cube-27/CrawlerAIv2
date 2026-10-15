"""`POST /v1/crawl` (SPEC-10 §4.5): the crawl service over HTTP. The job runs in the workers; its status is
`GET /v1/jobs/{id}` and what it made `GET /v1/jobs/{id}/results`."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from crawlerai.api.auth import require_api_key
from crawlerai.api.database import database
from crawlerai.api.dto import PROBLEM_RESPONSE
from crawlerai.api.submissions import submission_problems
from crawlerai.db.models import ApiKeyId
from crawlerai.resolve.pipeline import EngineData
from crawlerai.services import crawl
from crawlerai.services.crawl import CrawlRequest, CrawlSubmitted
from crawlerai.services.fetching import Fetching

router = APIRouter(
    prefix="/v1/crawl",
    tags=["crawl"],
    dependencies=[Depends(require_api_key)],
    responses={401: PROBLEM_RESPONSE, 422: PROBLEM_RESPONSE, 429: PROBLEM_RESPONSE},
)


@router.post("", status_code=status.HTTP_202_ACCEPTED, responses={409: PROBLEM_RESPONSE, 503: PROBLEM_RESPONSE})
async def crawl_site(
    body: CrawlRequest, request: Request, key: Annotated[ApiKeyId, Depends(require_api_key)]
) -> CrawlSubmitted:
    """Queue a job that crawls from `url`: its sitemaps and the links of each page, within `include` and `exclude`,
    `max_depth` and `limit`, on its host (and the subdomains an `include` names). A page a `page_kind_rules` pattern
    matches is extracted; with rules, any other page is fetched for its links only. A target the API may not fetch, in
    `url` or `webhook_url`, is a 422 and nothing is queued."""
    fetching: Fetching = request.app.state.fetching
    data: EngineData | None = request.app.state.engine_data
    with submission_problems():
        return await crawl.submit_crawl(database(request), fetching.connector, body, data=data, api_key_id=key)
