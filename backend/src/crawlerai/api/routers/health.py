"""`GET /healthz` (rest-api spec): the API answers and its database does, and what the LLM setup check found.
Unauthenticated (§18)."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.api.database import database
from crawlerai.api.dto import PROBLEM_RESPONSE, Health
from crawlerai.api.problems import ProblemError

# A health probe needs an answer in bounded time; a database slower than this to answer `SELECT 1` is down for it.
PING_TIMEOUT_S = 5

router = APIRouter(tags=["health"])


@router.get("/healthz", responses={503: PROBLEM_RESPONSE})
async def healthz(engine: Annotated[AsyncEngine, Depends(database)], request: Request) -> Health:
    try:
        async with asyncio.timeout(PING_TIMEOUT_S), engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except (OSError, SQLAlchemyError) as e:  # `asyncio.timeout` raises `TimeoutError`, an `OSError`
        # The error is left out: a connection error may name the database's address.
        raise ProblemError(503, "unavailable", "Unavailable", "the database did not answer") from e
    return Health(llm=request.app.state.llm_setup.status)
