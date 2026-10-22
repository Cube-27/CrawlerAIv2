"""`POST /v1/batch/scrape` (jobs spec): the batch scrape service over HTTP. The job runs in the workers; its status
is `GET /v1/jobs/{id}` and what it made `GET /v1/jobs/{id}/results`."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from crawlerai.api.auth import require_api_key
from crawlerai.api.database import database
from crawlerai.api.dto import PROBLEM_RESPONSE
from crawlerai.api.submissions import submission_problems
from crawlerai.db.models import ApiKeyId
from crawlerai.llm.draft_cap import KeyCapped
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


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    responses={409: PROBLEM_RESPONSE, 502: PROBLEM_RESPONSE, 503: PROBLEM_RESPONSE},
)
async def batch_scrape(
    body: BatchScrapeRequest, request: Request, key: Annotated[ApiKeyId, Depends(require_api_key)]
) -> BatchSubmitted:
    """Queue a job that scrapes each of `urls` with the same formats, schema and fetch options; a URL given twice is
    scraped once. A target the API may not fetch, a URL by its form or `webhook_url`, is a 422 and nothing is queued;
    a URL refused only once its host is resolved (`dns`, a private address) fails its own task."""
    fetching: Fetching = request.app.state.fetching
    data: EngineData | None = request.app.state.engine_data
    llm = KeyCapped(request.app.state.llm, database(request), key)
    with submission_problems():
        return await batch.submit_batch(
            database(request),
            fetching.connector,
            body,
            data=data,
            llm=llm,
            api_key_id=key,
            egresses=fetching.egresses,
        )
