"""`GET` and `PATCH /v1/project/settings`: the project's settings (`services.project`)."""

from fastapi import APIRouter, Depends, Request

from crawlerai.api.auth import require_api_key
from crawlerai.api.database import database
from crawlerai.api.dto import PROBLEM_RESPONSE
from crawlerai.services.project import ProjectSettings, project_settings, update_project_settings

router = APIRouter(
    prefix="/v1/project/settings",
    tags=["project"],
    dependencies=[Depends(require_api_key)],
    responses={401: PROBLEM_RESPONSE, 422: PROBLEM_RESPONSE, 429: PROBLEM_RESPONSE},
)


@router.get("")
async def get_project_settings(request: Request) -> ProjectSettings:
    """The project's settings. `llm_call_cap` bounds the LLM calls of every job whose request sets no
    `budget.llm_calls`; null bounds none."""
    async with database(request).connect() as conn:
        return await project_settings(conn)


@router.patch("")
async def patch_project_settings(settings: ProjectSettings, request: Request) -> ProjectSettings:
    """Set the project's settings. A new `llm_call_cap` applies to running jobs too, from their next LLM call."""
    async with database(request).begin() as conn:
        return await update_project_settings(conn, settings)
