"""`/v1/schemas` (SPEC-07 §4.6): create, read, list, edit (a new version) and delete (retire), and a draft from field
names (SPEC-14 §4.10). The rules are the schemas service's; this router translates HTTP to it and its errors to
problems."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.api.auth import require_api_key
from crawlerai.api.database import database
from crawlerai.api.dto import PROBLEM_RESPONSE, SchemaList
from crawlerai.api.problems import conflict, invalid, not_found
from crawlerai.api.submissions import submission_problems
from crawlerai.db.models import PageKind, SchemaId, SchemaStatus
from crawlerai.llm.client import LLMClient
from crawlerai.llm.roles.s_schema import draft_fields
from crawlerai.schemas.registry import SchemaNotFound
from crawlerai.schemas.types import Name, SchemaContent, SchemaDef
from crawlerai.services import schemas
from crawlerai.services.schemas import InvalidSchema, NewSchema, SchemaConflict
from crawlerai.services.scrape_steps import SchemaFields, check_usable

router = APIRouter(
    prefix="/v1/schemas",
    tags=["schemas"],
    dependencies=[Depends(require_api_key)],
    responses={401: PROBLEM_RESPONSE, 422: PROBLEM_RESPONSE, 429: PROBLEM_RESPONSE},
)
_BY_ID: dict[int | str, dict[str, Any]] = {404: PROBLEM_RESPONSE}
_CHANGES: dict[int | str, dict[str, Any]] = {404: PROBLEM_RESPONSE, 409: PROBLEM_RESPONSE}


@asynccontextmanager
async def _transaction(request: Request) -> AsyncIterator[AsyncConnection]:
    """One transaction for the request, with the service's errors answered as problems."""
    engine = database(request)
    try:
        async with engine.begin() as conn:
            yield conn
    except SchemaNotFound as e:
        raise not_found(str(e)) from e
    except SchemaConflict as e:
        raise conflict(str(e)) from e
    except InvalidSchema as e:
        raise invalid(str(e), e.errors) from e


@router.post("", status_code=201, responses={409: PROBLEM_RESPONSE})
async def create_schema(body: NewSchema, request: Request, response: Response) -> SchemaDef:
    """A `user` schema at version 1."""
    async with _transaction(request) as conn:
        created = await schemas.create(conn, body)
    response.headers["Location"] = f"{router.prefix}/{created.id}"
    return created


class FieldsDraft(SchemaFields):
    """Field names and the page kind of the pages they are read from."""

    page_kind: PageKind


@router.post("/draft", responses={502: PROBLEM_RESPONSE, 503: PROBLEM_RESPONSE})
async def draft_schema(body: FieldsDraft, request: Request) -> SchemaDef:
    """The schema role S drafts from `fields` for `page_kind` pages, with exactly those top-level fields, as a run's
    `schema.fields` uses it: the stored draft when these names were drafted for this page kind before, else a new
    one, stored. A client shows it for editing before the run (SPEC-14 §4.10). A draft the LLM could not give is a
    problem typed with the LLM failure (502, 503); a retired draft is a 422."""
    llm: LLMClient = request.app.state.llm
    with submission_problems():
        drafted = await draft_fields(database(request), llm, fields=body.fields, page_kind=body.page_kind)
        check_usable(drafted, body.page_kind)
    return drafted


@router.get("")
async def list_schemas(
    request: Request,
    name: Annotated[Name | None, Query()] = None,
    status: Annotated[SchemaStatus | None, Query()] = None,
) -> SchemaList:
    """Every version of every schema; only those of `name` and in `status` when given."""
    async with _transaction(request) as conn:
        return SchemaList(items=await schemas.list_all(conn, name=name, status=status))


@router.get("/{schema_id}", responses=_BY_ID)
async def get_schema(schema_id: SchemaId, request: Request) -> SchemaDef:
    async with _transaction(request) as conn:
        return await schemas.get(conn, schema_id)


@router.put("/{schema_id}", responses=_CHANGES)
async def update_schema(schema_id: SchemaId, body: SchemaContent, request: Request) -> SchemaDef:
    """Adds the next version with `body` as its whole document and returns it. `schema_id` must be the latest
    version, active and not a preset; otherwise 409."""
    async with _transaction(request) as conn:
        return await schemas.update(conn, schema_id, body)


@router.delete("/{schema_id}", status_code=204, responses=_CHANGES)
async def retire_schema(schema_id: SchemaId, request: Request) -> None:
    """Retires this version. The row stays, since records and configs reference it; a preset is refused (409)."""
    async with _transaction(request) as conn:
        await schemas.retire(conn, schema_id)
