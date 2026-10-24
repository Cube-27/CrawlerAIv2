"""`POST /v1/extract`: the extract service over HTTP. The schema, a prompt's draft included, comes back
with the job; the job runs in the workers, its status is `GET /v1/jobs/{id}` and its records
`GET /v1/jobs/{id}/results`."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from snowcrawl.api.auth import caller, require_api_key
from snowcrawl.api.dto import PROBLEM_RESPONSE
from snowcrawl.api.problems import ProblemError, invalid, target_refused
from snowcrawl.api.submissions import submission_problems
from snowcrawl.services import extract
from snowcrawl.services.extract import (
    DraftTimedOut,
    ExtractRequest,
    ExtractSubmitted,
    NoSamplePage,
    NothingToExtract,
)
from snowcrawl.services.fetching import TargetRejected
from snowcrawl.services.runtime import Caller

router = APIRouter(
    prefix="/v1/extract",
    tags=["extract"],
    dependencies=[Depends(require_api_key)],
    responses={401: PROBLEM_RESPONSE, 422: PROBLEM_RESPONSE, 429: PROBLEM_RESPONSE},
)


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    responses={409: PROBLEM_RESPONSE, 502: PROBLEM_RESPONSE, 503: PROBLEM_RESPONSE, 504: PROBLEM_RESPONSE},
)
async def extract_records(body: ExtractRequest, caller: Annotated[Caller, Depends(caller)]) -> ExtractSubmitted:
    """Queue a job that extracts a record of `page_kind` from each of `urls`; a URL with a `*` is a glob, expanded
    through a map of its host. A `schema.prompt` is drafted from the first pages before the job is queued, and the
    draft is returned as `schema`. A target the API may not fetch, a URL by its form, a glob's origin or map or
    `webhook_url`, is a 422 and nothing is queued; a URL refused only once its host is resolved (`dns`, a private
    address) fails its own task."""
    runtime = caller.runtime
    with submission_problems():
        try:
            return await extract.submit_extract(
                runtime.database,
                runtime.fetching,
                body,
                llm=runtime.llm,
                data=runtime.engine_data,
                api_key_id=caller.api_key_id,
            )
        except TargetRejected as e:
            raise target_refused(e.reason) from e
        except (NothingToExtract, NoSamplePage) as e:
            raise invalid(str(e), [("urls", str(e))]) from e
        except DraftTimedOut as e:
            raise ProblemError(504, "timeout", "Timed out", str(e)) from e
