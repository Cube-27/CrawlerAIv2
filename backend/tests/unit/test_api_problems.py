"""App-wide problem details: every error the app answers, its own or the framework's, is an RFC 9457
`application/problem+json` body with `type`, `title`, `status`, `detail` and `instance`."""

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from crawlerai.api.app import create_app
from crawlerai.api.database import database


async def _send(app: FastAPI, method: str, path: str, body: object = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as client:
        return await client.request(method, path, json=body)


def _request(app: FastAPI, method: str, path: str, body: object = None) -> httpx.Response:
    return asyncio.run(_send(app, method, path, body))


def _problem(response: httpx.Response) -> dict[str, Any]:
    assert response.headers["content-type"] == "application/problem+json"
    body: dict[str, Any] = response.json()
    assert body["status"] == response.status_code
    return body


def test_an_unexpected_error_is_an_internal_problem_without_its_message() -> None:
    app = create_app()

    async def broken() -> AsyncEngine:
        raise RuntimeError("secret-bearing internal message")

    app.dependency_overrides[database] = broken

    response = _request(app, "GET", "/healthz")

    assert response.status_code == 500
    problem = _problem(response)
    assert (problem["type"], problem["title"]) == ("about:blank", "Internal Server Error")
    assert "secret-bearing" not in response.text


@pytest.fixture
def unreachable_database() -> Callable[[], AsyncIterator[AsyncEngine]]:
    async def engine() -> AsyncIterator[AsyncEngine]:
        # Port 1 on the loopback address: nothing listens there, so the connection is refused at once.
        unreachable = create_async_engine("postgresql+asyncpg://user:password@127.0.0.1:1/none")
        yield unreachable
        await unreachable.dispose()

    return engine


def test_healthz_is_a_503_problem_when_the_database_does_not_answer(
    unreachable_database: Callable[[], AsyncIterator[AsyncEngine]],
) -> None:
    app = create_app()
    app.dependency_overrides[database] = unreachable_database

    response = _request(app, "GET", "/healthz")

    assert response.status_code == 503
    problem = _problem(response)
    assert (problem["type"], problem["detail"]) == ("unavailable", "the database did not answer")
    assert "password" not in response.text
