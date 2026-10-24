"""`POST /v1/scrape`: the scrape service over HTTP. A page that could not be fetched is an outcome in
a 200 answer; a refused target, a schema `records` cannot use, and a timeout are problems."""

from collections.abc import Awaitable
from typing import Annotated

from fastapi import APIRouter, Depends

from snowcrawl.api.auth import caller, require_api_key
from snowcrawl.api.dto import PROBLEM_RESPONSE
from snowcrawl.api.problems import ProblemError, conflict, invalid, llm_problem, records_unavailable, target_refused
from snowcrawl.llm.client import LLMFailure
from snowcrawl.services import scrape as scrape_service
from snowcrawl.services.fetch_options import UnknownProxyPool
from snowcrawl.services.fetching import TargetRejected
from snowcrawl.services.runtime import Caller
from snowcrawl.services.schemas import InvalidSchema, SchemaConflict
from snowcrawl.services.scrape import (
    RecordsUnavailable,
    ScrapeRequest,
    ScrapeResult,
    ScrapeTimedOut,
)
from snowcrawl.services.scrape_request import SchemaUnusable
from snowcrawl.services.stored_captures import NOT_CACHED, NotCached

router = APIRouter(
    prefix="/v1/scrape",
    tags=["scrape"],
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
async def scrape(body: ScrapeRequest, caller: Annotated[Caller, Depends(caller)]) -> ScrapeResult:
    """Fetch `url`, or read a capture of it fetched within `max_age` seconds, and return the requested formats; only
    those are members of the answer. A `schema.prompt` is drafted into a schema, returned as `schema`. `records`
    holds the page's record against the schema; an inline schema is stored as a `user` schema, or matched to the
    stored schema of its name, and one that differs from it is a 409."""
    runtime = caller.runtime
    return await scrape_answer(
        scrape_service.scrape(
            runtime.database,
            runtime.fetching,
            body,
            llm=runtime.llm,
            data=runtime.engine_data,
            margins=runtime.drift_margins,
        )
    )


async def scrape_answer[T](scraped: Awaitable[T]) -> T:
    """What a scrape (`services.scrape.scrape`) answers, each of its refusals as its problem."""
    try:
        return await scraped
    except TargetRejected as e:
        raise target_refused(e.reason) from e
    except UnknownProxyPool as e:
        raise invalid(str(e), [("fetch.proxy_pool", str(e))]) from e
    except NotCached as e:
        raise ProblemError(404, NOT_CACHED, "Not cached", str(e)) from e
    except SchemaUnusable as e:
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
        raise llm_problem(e) from e
