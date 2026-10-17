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
    `budget.llm_calls`, and `draft_call_cap` the uncharged field-name drafts of each API key; null bounds none.
    `require_config_approval` makes a learned config wait for approval before it serves."""
    async with database(request).connect() as conn:
        return await project_settings(conn)


@router.patch("")
async def patch_project_settings(settings: ProjectSettings, request: Request) -> ProjectSettings:
    """Set the project's settings. A new `llm_call_cap` applies to running jobs too, from their next LLM call, and a new
    `draft_call_cap` from a key's next draft; `require_config_approval` from the next learning run's end."""
    async with database(request).begin() as conn:
        return await update_project_settings(conn, settings)
