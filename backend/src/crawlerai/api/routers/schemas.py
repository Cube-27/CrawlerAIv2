"""`/v1/schemas` (SPEC-07 §4.6): create, read, list, edit (a new version) and delete (retire). The rules are the
schemas service's; this router translates HTTP to it and its errors to problems."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.api.auth import require_api_key
from crawlerai.api.dto import PROBLEM_RESPONSE, SchemaList
from crawlerai.api.problems import conflict, invalid, not_found
from crawlerai.db.models import SchemaId, SchemaStatus
from crawlerai.schemas.registry import SchemaNotFound
from crawlerai.schemas.types import Name, SchemaDef
from crawlerai.services import schemas
from crawlerai.services.schemas import InvalidSchema, NewSchema, SchemaConflict, SchemaContent

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
    engine: AsyncEngine = request.app.state.database
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
