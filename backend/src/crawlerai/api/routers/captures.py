"""`POST /v1/captures/{capture_id}/replay` (SPEC-07 §4.6): a stored capture through the current engine, for
debugging; nothing is stored."""

from fastapi import APIRouter, Depends, Request

from crawlerai.api.auth import require_api_key
from crawlerai.api.database import database
from crawlerai.api.dto import PROBLEM_RESPONSE, ReplayRequest, ReplayResult
from crawlerai.api.problems import conflict, not_found, records_unavailable
from crawlerai.db.models import CaptureId
from crawlerai.resolve.pipeline import EngineData
from crawlerai.services import captures
from crawlerai.services.captures import CaptureNotFound, NotReplayable
from crawlerai.services.fetching import Fetching

router = APIRouter(
    prefix="/v1/captures",
    tags=["captures"],
    dependencies=[Depends(require_api_key)],
    responses={401: PROBLEM_RESPONSE, 422: PROBLEM_RESPONSE, 429: PROBLEM_RESPONSE},
)


@router.post("/{capture_id}/replay", responses={404: PROBLEM_RESPONSE, 409: PROBLEM_RESPONSE, 503: PROBLEM_RESPONSE})
async def replay_capture(capture_id: CaptureId, body: ReplayRequest, request: Request) -> ReplayResult:
    """The records the current engine makes from the capture, against the schema versions of the records stored from
    it. 404: no such capture, or its bundle expired; 409: no record was made from it."""
    data: EngineData | None = request.app.state.engine_data
    if data is None:
        raise records_unavailable("the engine's data files are not installed")
    fetching: Fetching = request.app.state.fetching
    try:
        made = await captures.replay(database(request), fetching.store, data, capture_id)
    except CaptureNotFound as e:
        raise not_found(str(e)) from e
    except NotReplayable as e:
        raise conflict(str(e)) from e
    return ReplayResult(records=made)
