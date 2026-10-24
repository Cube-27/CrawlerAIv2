"""`POST /v1/batch/scrape`: the batch scrape service over HTTP. The job runs in the workers; its status
is `GET /v1/jobs/{id}` and what it made `GET /v1/jobs/{id}/results`."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from snowcrawl.api.auth import caller, require_api_key
from snowcrawl.api.dto import PROBLEM_RESPONSE
from snowcrawl.api.submissions import submission_problems
from snowcrawl.services import batch
from snowcrawl.services.batch import BatchScrapeRequest, BatchSubmitted
from snowcrawl.services.runtime import Caller

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
async def batch_scrape(body: BatchScrapeRequest, caller: Annotated[Caller, Depends(caller)]) -> BatchSubmitted:
    """Queue a job that scrapes each of `urls` with the same formats, schema and fetch options; a URL given twice is
    scraped once. A target the API may not fetch, a URL by its form or `webhook_url`, is a 422 and nothing is queued;
    a URL refused only once its host is resolved (`dns`, a private address) fails its own task."""
    runtime = caller.runtime
    with submission_problems():
        return await batch.submit_batch(
            runtime.database,
            runtime.fetching.connector,
            body,
            data=runtime.engine_data,
            llm=runtime.llm,
            api_key_id=caller.api_key_id,
            egresses=runtime.fetching.egresses,
        )
