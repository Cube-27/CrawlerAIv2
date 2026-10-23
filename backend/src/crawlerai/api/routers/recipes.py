"""The custom recipe builder's helpers, which persist nothing: `POST /v1/recipes/calls`, the calls of two to five
engineer captures merged by endpoint (`services.recipe_calls`); `POST /v1/recipes/propose`, a recipe's draft from them
(`services.recipe_propose`); `POST /v1/recipes/test`, a recipe tried on URLs of its patterns beside the normal
extraction (`services.recipe_trial`)."""

from fastapi import APIRouter, Depends, Request

from crawlerai.api.auth import require_api_key
from crawlerai.api.dto import PROBLEM_RESPONSE
from crawlerai.api.problems import conflict, invalid, not_found, records_unavailable
from crawlerai.api.routers.captures import call_list
from crawlerai.api.routers.scrape import scrape_answer
from crawlerai.api.runtime import database, runtime
from crawlerai.config_ir.custom_recipe import InvalidRecipe
from crawlerai.schemas.registry import SchemaNotFound
from crawlerai.services.captures import CaptureNotFound
from crawlerai.services.configs import ConfigConflict, ConfigNotFound
from crawlerai.services.recipe_calls import CallList, NoSamples, SampleIds
from crawlerai.services.recipe_propose import Proposal, ProposeRequest, propose_recipe
from crawlerai.services.recipe_trial import RecipeTestRequest, RecipeTestResult, try_recipe
from crawlerai.services.scrape_request import Input

router = APIRouter(
    prefix="/v1/recipes",
    tags=["recipes"],
    dependencies=[Depends(require_api_key)],
    responses={401: PROBLEM_RESPONSE, 422: PROBLEM_RESPONSE, 429: PROBLEM_RESPONSE},
)


class CallsRequest(Input):
    """The sample captures whose calls are merged: two to five, read for one schema, all distinct."""

    capture_ids: SampleIds


@router.post("/calls", responses={404: PROBLEM_RESPONSE, 409: PROBLEM_RESPONSE})
async def calls(body: CallsRequest, request: Request) -> CallList:
    """The samples' calls by endpoint, each field's paths counted on how many samples they read it. 404: no such
    capture, or its bundle expired; 409: a capture was read for no schema, or they were read for different ones."""
    return await call_list(request, body.capture_ids)


@router.post("/propose", responses={404: PROBLEM_RESPONSE, 409: PROBLEM_RESPONSE})
async def propose(body: ProposeRequest, request: Request) -> Proposal:
    """A custom recipe's draft from the samples' calls of the `main` endpoint (named by its key or one of its calls),
    for the schema: the bound request, its headers, pagination, field map and URL patterns, with the fields left
    unfilled, the request values left unbound and the headers left out. Deterministic, and nothing is sent or stored.
    404: no such capture or schema, or a bundle expired; 422: the samples' calls of the main endpoint make no recipe."""
    try:
        return await propose_recipe(database(request), runtime(request).fetching.store, body)
    except (CaptureNotFound, SchemaNotFound) as e:
        raise not_found(str(e)) from e
    except NoSamples as e:
        raise conflict(str(e)) from e
    except InvalidRecipe as e:
        raise invalid(str(e), e.errors) from e


@router.post(
    "/test",
    responses={
        404: PROBLEM_RESPONSE,
        409: PROBLEM_RESPONSE,
        502: PROBLEM_RESPONSE,
        503: PROBLEM_RESPONSE,
        504: PROBLEM_RESPONSE,
    },
)
async def test(body: RecipeTestRequest, request: Request) -> RecipeTestResult:
    """Each URL fetched and extracted with the recipe (a draft, or a stored custom recipe's id), and as if no recipe's
    pattern matched it, both with their fetch trails. No capture, record, config or site memory is stored; the
    fetches count as a `scrape` job's usage. 404: no such config or schema; 409: the config is not a custom recipe;
    422: the draft does not fit its schema, or a URL matches no pattern of the recipe."""
    run = runtime(request)
    if run.engine_data is None:
        raise records_unavailable("the engine's data files are not installed")
    try:
        return await scrape_answer(try_recipe(run.database, run.fetching, run.engine_data, body))
    except (ConfigNotFound, SchemaNotFound) as e:
        raise not_found(str(e)) from e
    except ConfigConflict as e:
        raise conflict(str(e)) from e
    except InvalidRecipe as e:
        raise invalid(str(e), e.errors) from e
