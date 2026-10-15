"""`GET /v1/usage/llm` and `GET /v1/usage/llm/jobs` (SPEC-10 §4.2): the LLM cost history, an estimate for
visibility, not billing (ARCHITECTURE §1)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from crawlerai.api.auth import require_api_key
from crawlerai.api.database import database
from crawlerai.api.dto import PROBLEM_RESPONSE
from crawlerai.llm.pricing import default_pricing
from crawlerai.services import llm_costs
from crawlerai.services.llm_costs import CostQuery, CostReport, JobCostPage, JobCostQuery

router = APIRouter(
    prefix="/v1/usage/llm",
    tags=["usage"],
    dependencies=[Depends(require_api_key)],
    responses={401: PROBLEM_RESPONSE, 422: PROBLEM_RESPONSE, 429: PROBLEM_RESPONSE},
)


@router.get("")
async def llm_cost_report(query: Annotated[CostQuery, Query()], request: Request) -> CostReport:
    """The LLM calls of the UTC days `start` to `end` (both included; by default the 30 days through today), with
    their tokens and estimated cost in USD: in total, per day, per provider, model and prompt kind, and for the
    costliest jobs. A cost is null when some of its tokens have no price. Calls made without a job are not
    recorded, so they are not included."""
    engine = database(request)
    async with engine.connect() as conn:
        return await llm_costs.cost_report(conn, query, default_pricing())


@router.get("/jobs")
async def llm_job_costs(query: Annotated[JobCostQuery, Query()], request: Request) -> JobCostPage:
    """The jobs with LLM calls in the range, newest first, each with those calls' tokens and estimated cost. Pass a
    page's `next_cursor` as `cursor` for the page after it."""
    engine = database(request)
    async with engine.connect() as conn:
        return await llm_costs.job_costs(conn, query, default_pricing())
