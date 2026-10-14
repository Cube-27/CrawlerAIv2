"""`POST /v1/extract` (SPEC-10 §4.6): the extract service over HTTP. The schema, a prompt's draft included, comes back
with the job; the job runs in the workers, its status is `GET /v1/jobs/{id}` and its records
`GET /v1/jobs/{id}/results`."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from crawlerai.api.auth import require_api_key
from crawlerai.api.dto import PROBLEM_RESPONSE
from crawlerai.api.problems import ProblemError, invalid, llm_problem, target_refused
from crawlerai.api.submissions import submission_problems
from crawlerai.db.models import ApiKeyId
from crawlerai.llm.client import LLMClient, LLMFailure
from crawlerai.resolve.pipeline import EngineData
from crawlerai.services import extract
from crawlerai.services.extract import (
    DraftTimedOut,
    ExtractRequest,
    ExtractSubmitted,
    NoSamplePage,
    NothingToExtract,
)
from crawlerai.services.fetching import Fetching, TargetRejected

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
async def extract_records(
    body: ExtractRequest, request: Request, key: Annotated[ApiKeyId, Depends(require_api_key)]
) -> ExtractSubmitted:
    """Queue a job that extracts a record of `page_kind` from each of `urls`; a URL with a `*` is a glob, expanded
    through a map of its host. A `schema.prompt` is drafted from the first pages before the job is queued, and the
    draft is returned as `schema`. A target the API may not fetch, in `urls`, a glob's map or `webhook_url`, is a 422
    and nothing is queued."""
    fetching: Fetching = request.app.state.fetching
    llm: LLMClient = request.app.state.llm
    data: EngineData | None = request.app.state.engine_data
    with submission_problems():
        try:
            return await extract.submit_extract(
                request.app.state.database, fetching, body, llm=llm, data=data, api_key_id=key
            )
        except TargetRejected as e:
            raise target_refused(e.reason) from e
        except (NothingToExtract, NoSamplePage) as e:
            raise invalid(str(e), [("urls", str(e))]) from e
        except DraftTimedOut as e:
            raise ProblemError(504, "timeout", "Timed out", str(e)) from e
        except LLMFailure as e:
            raise llm_problem(e) from e
