"""`POST /v1/scrape` (SPEC-07 §4.4): the scrape service over HTTP. A page that could not be fetched is an outcome in
a 200 answer; a refused target and a timeout are problems (§4.8)."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.api.auth import require_api_key
from crawlerai.api.dto import PROBLEM_RESPONSE
from crawlerai.api.problems import ProblemError
from crawlerai.llm.client import BudgetExhausted, LLMClient, OutputInvalid, ProviderUnavailable
from crawlerai.services import scrape as scrape_service
from crawlerai.services.scrape import Fetching, ScrapeRejected, ScrapeRequest, ScrapeResult, ScrapeTimedOut

router = APIRouter(
    prefix="/v1/scrape",
    tags=["scrape"],
    dependencies=[Depends(require_api_key)],
    responses={401: PROBLEM_RESPONSE, 422: PROBLEM_RESPONSE, 429: PROBLEM_RESPONSE},
)


@router.post("", responses={502: PROBLEM_RESPONSE, 503: PROBLEM_RESPONSE, 504: PROBLEM_RESPONSE})
async def scrape(body: ScrapeRequest, request: Request) -> ScrapeResult:
    """Fetch `url` and return the requested formats; only those are members of the answer. A `schema.prompt` is
    drafted into a schema, returned as `schema`."""
    engine: AsyncEngine = request.app.state.database
    fetching: Fetching = request.app.state.fetching
    llm: LLMClient = request.app.state.llm
    try:
        return await scrape_service.scrape(engine, fetching, body, llm=llm)
    except ScrapeRejected as e:
        # 422: the request names a target the API may not fetch (INV-16).
        raise ProblemError(422, "ssrf_rejected", "Target refused", e.reason) from e
    except ScrapeTimedOut as e:
        raise ProblemError(504, "timeout", "Timed out", str(e)) from e
    except BudgetExhausted as e:
        # 422: the request's own `budget.llm_calls` does not cover the work it asks for.
        raise ProblemError(422, "budget_exhausted", "Budget exhausted", "budget.llm_calls is spent") from e
    except ProviderUnavailable as e:
        raise ProblemError(503, "llm_unavailable", "LLM unavailable", str(e)) from e
    except OutputInvalid as e:
        # 502: the model answered, but not with a valid schema, after the one retry.
        raise ProblemError(502, "llm_output_invalid", "LLM output invalid", str(e)) from e
