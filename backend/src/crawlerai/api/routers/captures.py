"""`POST /v1/captures/{capture_id}/replay` (SPEC-07 §4.6): a stored capture through the current engine, for
debugging; nothing is stored."""

from fastapi import APIRouter, Depends, Request, Response

from crawlerai.api.auth import require_api_key
from crawlerai.api.database import database
from crawlerai.api.dto import PROBLEM_RESPONSE, ReplayRequest, ReplayResult
from crawlerai.api.problems import conflict, not_found, records_unavailable
from crawlerai.db.models import CaptureId
from crawlerai.resolve.pipeline import EngineData
from crawlerai.services import captures
from crawlerai.services.captures import CaptureNotFound, NotReplayable
from crawlerai.services.fetching import Fetching
from crawlerai.storage.artifacts import ARTIFACT_TYPES

router = APIRouter(
    prefix="/v1/captures",
    tags=["captures"],
    dependencies=[Depends(require_api_key)],
    responses={401: PROBLEM_RESPONSE, 422: PROBLEM_RESPONSE, 429: PROBLEM_RESPONSE},
)


@router.post("/{capture_id}/replay", responses={404: PROBLEM_RESPONSE, 409: PROBLEM_RESPONSE, 503: PROBLEM_RESPONSE})
async def replay_capture(capture_id: CaptureId, body: ReplayRequest, request: Request) -> ReplayResult:
    """The records the current engine makes from the capture, against the schemas of the records stored from
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


@router.get(
    "/{capture_id}/artifacts/{name}",
    response_class=Response,
    responses={
        200: {
            "description": "The file: a PNG for `screenshot.png`, a PDF for `page.pdf`.",
            "content": {
                media_type: {"schema": {"type": "string", "format": "binary"}} for media_type in ARTIFACT_TYPES.values()
            },
        },
        404: PROBLEM_RESPONSE,
    },
)
async def get_artifact(capture_id: CaptureId, name: str, request: Request) -> Response:
    """The screenshot (`screenshot.png`) or PDF (`page.pdf`) the browser made of the capture's page, as the scrape,
    batch or crawl that asked for it named it in its answer. 404: no such capture, its files expired with it, or it has
    no such file."""
    fetching: Fetching = request.app.state.fetching
    try:
        data = await captures.artifact(database(request), fetching.store, capture_id, name)
    except CaptureNotFound as e:
        raise not_found(str(e)) from e
    # A file of a captured page is served as itself and never sniffed into something else; it is private to the key.
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"}
    return Response(data, media_type=ARTIFACT_TYPES[name], headers=headers)
