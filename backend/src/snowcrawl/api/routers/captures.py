"""The captures: `POST /v1/captures`, an engineer capture of a sample page (`services.captures.capture`), its calls
(`GET .../calls`, one call, and the HAR export), and `POST /v1/captures/{capture_id}/replay`, a stored capture through
the current engine, for debugging, which stores nothing. Internals (calls, paths, headers) are answered here for the
Recipes screen only (`docs/rules.md`)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from snowcrawl.api.auth import caller, require_api_key
from snowcrawl.api.dto import PROBLEM_RESPONSE, ReplayRequest, ReplayResult
from snowcrawl.api.problems import conflict, not_found, records_unavailable
from snowcrawl.api.routers.scrape import scrape_answer
from snowcrawl.api.runtime import database, runtime
from snowcrawl.db.models import CaptureId
from snowcrawl.services import captures, recipe_calls
from snowcrawl.services.captures import CallDetail, CaptureNotFound, CaptureRequest, CaptureResult, NotReplayable
from snowcrawl.services.har import har
from snowcrawl.services.recipe_calls import CallList, NoSamples
from snowcrawl.services.runtime import Caller
from snowcrawl.storage.artifacts import ARTIFACT_TYPES

router = APIRouter(
    prefix="/v1/captures",
    tags=["captures"],
    dependencies=[Depends(require_api_key)],
    responses={401: PROBLEM_RESPONSE, 422: PROBLEM_RESPONSE, 429: PROBLEM_RESPONSE},
)


@router.post(
    "",
    responses={
        404: PROBLEM_RESPONSE,
        409: PROBLEM_RESPONSE,
        502: PROBLEM_RESPONSE,
        503: PROBLEM_RESPONSE,
        504: PROBLEM_RESPONSE,
    },
)
async def capture(body: CaptureRequest, caller: Annotated[Caller, Depends(caller)]) -> CaptureResult:
    """Render `url` in the browser after the page steps, keeping every call the page makes, and store the capture and
    its record of the schema: a sample page to choose a custom recipe's calls from. Answers when the page has been
    fetched and read, as `POST /v1/scrape` does, with its problems."""
    return await scrape_answer(captures.capture(caller, body))


@router.get("/{capture_id}/calls", responses={404: PROBLEM_RESPONSE, 409: PROBLEM_RESPONSE})
async def get_calls(capture_id: CaptureId, request: Request) -> CallList:
    """The capture's calls by endpoint, each with where it carries the fields of the schema it was read for (the values
    of its record, else the paths of each field's type). 404: no such capture, or its bundle expired; 409: it was read
    for no schema."""
    return await call_list(request, [capture_id])


@router.get("/{capture_id}/calls.har", responses={200: {"content": {"application/json": {}}}, 404: PROBLEM_RESPONSE})
async def get_har(capture_id: CaptureId, request: Request) -> JSONResponse:
    """The capture as an HTTP Archive (HAR 1.2): the page's document and every call it kept, without cookies, the
    caller's own header values masked. 404: no such capture, or its bundle expired."""
    try:
        bundle = await captures.bundle_of(database(request), runtime(request).fetching.store, capture_id)
    except CaptureNotFound as e:
        raise not_found(str(e)) from e
    return JSONResponse(har(bundle))


@router.get("/{capture_id}/calls/{index}", responses={404: PROBLEM_RESPONSE})
async def get_call(capture_id: CaptureId, index: int, request: Request) -> CallDetail:
    """One call the capture kept, by its index in the call list: the request and the answer's text. 404: no such
    capture or call, or its bundle expired."""
    try:
        return await captures.call(database(request), runtime(request).fetching.store, capture_id, index)
    except CaptureNotFound as e:
        raise not_found(str(e)) from e


async def call_list(request: Request, capture_ids: list[CaptureId]) -> CallList:
    """The call list of the captures (`services.recipe_calls`), its refusals as problems."""
    try:
        return await recipe_calls.call_list(database(request), runtime(request).fetching.store, capture_ids)
    except CaptureNotFound as e:
        raise not_found(str(e)) from e
    except NoSamples as e:
        raise conflict(str(e)) from e


@router.post("/{capture_id}/replay", responses={404: PROBLEM_RESPONSE, 409: PROBLEM_RESPONSE, 503: PROBLEM_RESPONSE})
async def replay_capture(capture_id: CaptureId, body: ReplayRequest, request: Request) -> ReplayResult:
    """The records the current engine makes from the capture, against the schemas of the records stored from
    it. 404: no such capture, or its bundle expired; 409: no record was made from it."""
    data = runtime(request).engine_data
    if data is None:
        raise records_unavailable("the engine's data files are not installed")
    fetching = runtime(request).fetching
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
    fetching = runtime(request).fetching
    try:
        data = await captures.artifact(database(request), fetching.store, capture_id, name)
    except CaptureNotFound as e:
        raise not_found(str(e)) from e
    # A file of a captured page is served as itself and never sniffed into something else; it is private to the key.
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"}
    return Response(data, media_type=ARTIFACT_TYPES[name], headers=headers)
