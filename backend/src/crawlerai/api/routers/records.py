"""`GET /v1/records` (SPEC-07 §4.6): stored records with their full `field_meta`, a page at a time."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.api.auth import require_api_key
from crawlerai.api.dto import PROBLEM_RESPONSE
from crawlerai.services import records
from crawlerai.services.records import RecordFilter, RecordPage

router = APIRouter(
    prefix="/v1/records",
    tags=["records"],
    dependencies=[Depends(require_api_key)],
    responses={401: PROBLEM_RESPONSE, 422: PROBLEM_RESPONSE, 429: PROBLEM_RESPONSE},
)


@router.get("")
async def list_records(query: Annotated[RecordFilter, Query()], request: Request) -> RecordPage:
    """Records newest first, narrowed by job, site (host) and schema version. Pass a page's `next_cursor` as `cursor`
    for the page after it."""
    engine: AsyncEngine = request.app.state.database
    async with engine.connect() as conn:
        return await records.list_records(conn, query)
