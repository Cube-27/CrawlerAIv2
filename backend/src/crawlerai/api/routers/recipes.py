"""The custom recipe builder's helpers, which persist nothing: `POST /v1/recipes/calls`, the calls of two to five
engineer captures merged by endpoint (`services.recipe_calls`)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import Field, field_validator

from crawlerai.api.auth import require_api_key
from crawlerai.api.dto import PROBLEM_RESPONSE
from crawlerai.api.routers.captures import call_list
from crawlerai.db.models import CaptureId
from crawlerai.services.recipe_calls import MAX_SAMPLES, CallList
from crawlerai.services.scrape_request import Input

router = APIRouter(
    prefix="/v1/recipes",
    tags=["recipes"],
    dependencies=[Depends(require_api_key)],
    responses={401: PROBLEM_RESPONSE, 422: PROBLEM_RESPONSE, 429: PROBLEM_RESPONSE},
)


class CallsRequest(Input):
    """The sample captures whose calls are merged: two to five, read for one schema, all distinct."""

    capture_ids: Annotated[list[CaptureId], Field(min_length=2, max_length=MAX_SAMPLES)]

    @field_validator("capture_ids")
    @classmethod
    def _distinct(cls, capture_ids: list[CaptureId]) -> list[CaptureId]:
        if len(set(capture_ids)) != len(capture_ids):
            raise ValueError("a capture is named twice")
        return capture_ids


@router.post("/calls", responses={404: PROBLEM_RESPONSE, 409: PROBLEM_RESPONSE})
async def calls(body: CallsRequest, request: Request) -> CallList:
    """The samples' calls by endpoint, each field's paths counted on how many samples they read it. 404: no such
    capture, or its bundle expired; 409: a capture was read for no schema, or they were read for different ones."""
    return await call_list(request, body.capture_ids)
