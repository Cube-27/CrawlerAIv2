"""`POST /v1/map`: the map service over HTTP. A refused target is a problem; URLs that could not be
read are left out of a 200 answer, and the timeout cuts the answer (`truncated`) rather than failing it."""

from fastapi import APIRouter, Depends, Request

from snowcrawl.api.auth import require_api_key
from snowcrawl.api.dto import PROBLEM_RESPONSE
from snowcrawl.api.problems import target_refused
from snowcrawl.api.runtime import database, runtime
from snowcrawl.services import map as map_service
from snowcrawl.services.fetching import TargetRejected
from snowcrawl.services.map import MapRequest, MapResult

router = APIRouter(
    prefix="/v1/map",
    tags=["map"],
    dependencies=[Depends(require_api_key)],
    responses={401: PROBLEM_RESPONSE, 422: PROBLEM_RESPONSE, 429: PROBLEM_RESPONSE},
)


@router.post("")
async def map_urls(body: MapRequest, request: Request) -> MapResult:
    """The URLs of `url`'s site from its sitemaps and the start page's links, canonical and in scope: the exact host
    of `url`, or the `include` globs, less the `exclude` globs. At most `limit`; `truncated` says more were found, or
    that reading stopped at a cap or the 60 s timeout."""
    engine = database(request)
    fetching = runtime(request).fetching
    try:
        return await map_service.map_urls(engine, fetching, body)
    except TargetRejected as e:
        raise target_refused(e.reason) from e
