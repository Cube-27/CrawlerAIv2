"""`POST /v1/batch/scrape` (SPEC-10 §4.3): the batch scrape service over HTTP. The job runs in the workers; its status
is `GET /v1/jobs/{id}` and what it made `GET /v1/jobs/{id}/results`."""

from fastapi import APIRouter, Depends, Request, status

from crawlerai.api.auth import require_api_key
from crawlerai.api.dto import PROBLEM_RESPONSE
from crawlerai.api.problems import ProblemError, conflict, invalid, records_unavailable
from crawlerai.resolve.pipeline import EngineData
from crawlerai.services import batch
from crawlerai.services.batch import BatchRejected, BatchScrapeRequest, BatchSubmitted
from crawlerai.services.schemas import InvalidSchema, SchemaConflict
from crawlerai.services.scrape import Fetching, RecordsUnavailable
from crawlerai.services.scrape_steps import SchemaUnusable

router = APIRouter(
    prefix="/v1/batch/scrape",
    tags=["batch"],
    dependencies=[Depends(require_api_key)],
    responses={401: PROBLEM_RESPONSE, 422: PROBLEM_RESPONSE, 429: PROBLEM_RESPONSE},
)


@router.post("", status_code=status.HTTP_202_ACCEPTED, responses={409: PROBLEM_RESPONSE, 503: PROBLEM_RESPONSE})
async def batch_scrape(body: BatchScrapeRequest, request: Request) -> BatchSubmitted:
    """Queue a job that scrapes each of `urls` with the same formats, schema and fetch options; a URL given twice is
    scraped once. A target the API may not fetch, in `urls` or `webhook_url`, is a 422 and nothing is queued."""
    fetching: Fetching = request.app.state.fetching
    data: EngineData | None = request.app.state.engine_data
    try:
        return await batch.submit_batch(request.app.state.database, fetching.connector, body, data=data)
    except BatchRejected as e:
        # 422: the request names a target the API may not fetch (INV-16).
        raise ProblemError(422, "ssrf_rejected", "Target refused", str(e), [(e.member, e.reason)]) from e
    except SchemaUnusable as e:
        raise invalid(str(e), [("schema", str(e))]) from e
    except InvalidSchema as e:
        raise invalid(str(e), [(f"schema.inline.{field}".rstrip("."), reason) for field, reason in e.errors]) from e
    except SchemaConflict as e:
        raise conflict(str(e)) from e
    except RecordsUnavailable as e:
        raise records_unavailable(str(e)) from e
