"""`POST /v1/scrape` (SPEC-07 §4.4): the scrape service over HTTP. A page that could not be fetched is an outcome in
a 200 answer; a refused target, a schema `records` cannot use, and a timeout are problems (§4.8)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from crawlerai.api.auth import require_api_key
from crawlerai.api.database import database
from crawlerai.api.dto import PROBLEM_RESPONSE
from crawlerai.api.problems import ProblemError, conflict, invalid, llm_problem, records_unavailable, target_refused
from crawlerai.config_ir.drift import DriftMargins
from crawlerai.db.models import ApiKeyId
from crawlerai.llm.client import LLMFailure
from crawlerai.llm.draft_cap import KeyCapped
from crawlerai.resolve.pipeline import EngineData
from crawlerai.services import scrape as scrape_service
from crawlerai.services.fetch_options import UnknownProxyPool
from crawlerai.services.fetching import Fetching, TargetRejected
from crawlerai.services.schemas import InvalidSchema, SchemaConflict
from crawlerai.services.scrape import (
    RecordsUnavailable,
    ScrapeRequest,
    ScrapeResult,
    ScrapeTimedOut,
)
from crawlerai.services.scrape_steps import SchemaUnusable
from crawlerai.services.stored_captures import NOT_CACHED, NotCached

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
async def scrape(
    body: ScrapeRequest, request: Request, key: Annotated[ApiKeyId, Depends(require_api_key)]
) -> ScrapeResult:
    """Fetch `url`, or read a capture of it fetched within `max_age` seconds, and return the requested formats; only
    those are members of the answer. A `schema.prompt` is drafted into a schema, returned as `schema`. `records`
    holds the page's record against the schema; an inline schema is stored as a `user` schema, or matched to the
    stored schema of its name, and one that differs from it is a 409."""
    engine = database(request)
    fetching: Fetching = request.app.state.fetching
    llm = KeyCapped(request.app.state.llm, engine, key)
    data: EngineData | None = request.app.state.engine_data
    margins: DriftMargins | None = request.app.state.drift_margins
    try:
        return await scrape_service.scrape(engine, fetching, body, llm=llm, data=data, margins=margins)
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
