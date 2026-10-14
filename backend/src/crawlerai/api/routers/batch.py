"""`POST /v1/batch/scrape` (SPEC-10 §4.3): the batch scrape service over HTTP. The job runs in the workers; its status
is `GET /v1/jobs/{id}` and what it made `GET /v1/jobs/{id}/results`."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from crawlerai.api.auth import require_api_key
from crawlerai.api.dto import PROBLEM_RESPONSE
from crawlerai.api.submissions import submission_problems
from crawlerai.db.models import ApiKeyId
from crawlerai.resolve.pipeline import EngineData
from crawlerai.services import batch
from crawlerai.services.batch import BatchScrapeRequest, BatchSubmitted
from crawlerai.services.fetching import Fetching

router = APIRouter(
    prefix="/v1/batch/scrape",
    tags=["batch"],
    dependencies=[Depends(require_api_key)],
    responses={401: PROBLEM_RESPONSE, 422: PROBLEM_RESPONSE, 429: PROBLEM_RESPONSE},
)


@router.post("", status_code=status.HTTP_202_ACCEPTED, responses={409: PROBLEM_RESPONSE, 503: PROBLEM_RESPONSE})
async def batch_scrape(
    body: BatchScrapeRequest, request: Request, key: Annotated[ApiKeyId, Depends(require_api_key)]
) -> BatchSubmitted:
    """Queue a job that scrapes each of `urls` with the same formats, schema and fetch options; a URL given twice is
    scraped once. A target the API may not fetch, in `urls` or `webhook_url`, is a 422 and nothing is queued."""
    fetching: Fetching = request.app.state.fetching
    data: EngineData | None = request.app.state.engine_data
    with submission_problems():
        return await batch.submit_batch(request.app.state.database, fetching.connector, body, data=data, api_key_id=key)
