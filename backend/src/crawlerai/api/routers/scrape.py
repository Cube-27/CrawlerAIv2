"""`POST /v1/scrape` (SPEC-07 §4.4): the scrape service over HTTP. A page that could not be fetched is an outcome in
a 200 answer; a refused target, a schema `records` cannot use, and a timeout are problems (§4.8)."""

from typing import Final

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.api.auth import require_api_key
from crawlerai.api.dto import PROBLEM_RESPONSE
from crawlerai.api.problems import ProblemError, conflict, invalid, records_unavailable
from crawlerai.llm.client import BudgetExhausted, LLMClient, LLMFailure, OutputInvalid, ProviderUnavailable
from crawlerai.resolve.pipeline import EngineData
from crawlerai.services import scrape as scrape_service
from crawlerai.services.schemas import InvalidSchema, SchemaConflict
from crawlerai.services.scrape import (
    Fetching,
    RecordsUnavailable,
    ScrapeInvalid,
    ScrapeRejected,
    ScrapeRequest,
    ScrapeResult,
    ScrapeTimedOut,
)

# 422: the request's own `budget.llm_calls` does not cover its work. 503: no provider answered. 502: the model
# answered, but not validly, after the one retry.
_LLM_PROBLEMS: Final[dict[str, tuple[int, str]]] = {
    BudgetExhausted.code: (422, "Budget exhausted"),
    ProviderUnavailable.code: (503, "LLM unavailable"),
    OutputInvalid.code: (502, "LLM output invalid"),
}

router = APIRouter(
    prefix="/v1/scrape",
    tags=["scrape"],
    dependencies=[Depends(require_api_key)],
    responses={401: PROBLEM_RESPONSE, 422: PROBLEM_RESPONSE, 429: PROBLEM_RESPONSE},
)


@router.post(
    "",
    responses={409: PROBLEM_RESPONSE, 502: PROBLEM_RESPONSE, 503: PROBLEM_RESPONSE, 504: PROBLEM_RESPONSE},
)
async def scrape(body: ScrapeRequest, request: Request) -> ScrapeResult:
    """Fetch `url`, or read a capture of it fetched within `max_age` seconds, and return the requested formats; only
    those are members of the answer. A `schema.prompt` is drafted into a schema, returned as `schema`. `records`
    holds the page's record against the schema; an inline schema is stored as a `user` schema, or matched to its
    name's latest version, and one that differs from that version is a 409."""
    engine: AsyncEngine = request.app.state.database
    fetching: Fetching = request.app.state.fetching
    llm: LLMClient = request.app.state.llm
    data: EngineData | None = request.app.state.engine_data
    try:
        return await scrape_service.scrape(engine, fetching, body, llm=llm, data=data)
    except ScrapeRejected as e:
        # 422: the request names a target the API may not fetch (INV-16).
        raise ProblemError(422, "ssrf_rejected", "Target refused", e.reason) from e
    except ScrapeInvalid as e:
        raise invalid(str(e), [("schema", str(e))]) from e
    except InvalidSchema as e:
        raise invalid(str(e), [(f"schema.inline.{field}".rstrip("."), reason) for field, reason in e.errors]) from e
    except SchemaConflict as e:
        raise conflict(str(e)) from e
    except RecordsUnavailable as e:
        raise records_unavailable(str(e)) from e
    except ScrapeTimedOut as e:
        raise ProblemError(504, "timeout", "Timed out", str(e)) from e
    except LLMFailure as e:
        status, title = _LLM_PROBLEMS[e.code]
        raise ProblemError(status, e.code, title, str(e)) from e
