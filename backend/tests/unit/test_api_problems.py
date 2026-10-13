"""App-wide problem details (SPEC-07 §4.3): every error the app answers, its own or the framework's, is an RFC 9457
`application/problem+json` body with `type`, `title`, `status`, `detail` and `instance`."""

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from crawlerai.api.app import create_app
from crawlerai.api.routers import eval as eval_router
from crawlerai.api.routers import health


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


def test_an_unknown_path_is_a_not_found_problem() -> None:
    response = _request(create_app(eval_ui=False), "GET", "/v1/nothing-here")

    assert response.status_code == 404
    assert _problem(response) == {
        "type": "not_found",
        "title": "Not found",
        "status": 404,
        "detail": "no resource at /v1/nothing-here",
        "instance": "/v1/nothing-here",
        "errors": [],
    }


def test_a_wrong_method_is_an_about_blank_problem_with_the_status_phrase() -> None:
    # RFC 9457 §4.2.1: `about:blank` means the problem is no more than its HTTP status.
    response = _request(create_app(eval_ui=False), "DELETE", "/healthz")

    assert response.status_code == 405
    problem = _problem(response)
    assert (problem["type"], problem["title"]) == ("about:blank", "Method Not Allowed")


def _labeling_app() -> FastAPI:
    """The app with the labeling endpoints, whose backend no request below reaches."""
    app = create_app(eval_ui=True)
    app.dependency_overrides[eval_router.labeling_backend] = object
    return app


def test_a_request_body_that_fails_validation_lists_each_field_and_reason() -> None:
    app = _labeling_app()
    body = {"split": "dev", "schema": "s", "page_kind": "detail", "category": "custom_store", "urls": []}

    response = _request(app, "POST", "/v1/eval/capture", body)

    assert response.status_code == 422
    problem = _problem(response)
    assert (problem["type"], problem["instance"]) == ("validation", "/v1/eval/capture")
    assert problem["errors"] == [
        {"field": "urls", "reason": "List should have at least 1 item after validation, not 0"}
    ]


def test_a_query_parameter_that_fails_validation_names_its_location() -> None:
    response = _request(_labeling_app(), "GET", "/v1/eval/pages?status=finished")

    problem = _problem(response)
    assert response.status_code == 422
    assert [error["field"] for error in problem["errors"]] == ["query.status"]


def test_an_unexpected_error_is_an_internal_problem_without_its_message() -> None:
    app = create_app(eval_ui=False)

    async def broken() -> AsyncEngine:
        raise RuntimeError("secret-bearing internal message")

    app.dependency_overrides[health.database] = broken

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
    app = create_app(eval_ui=False)
    app.dependency_overrides[health.database] = unreachable_database

    response = _request(app, "GET", "/healthz")

    assert response.status_code == 503
    problem = _problem(response)
    assert (problem["type"], problem["detail"]) == ("unavailable", "the database did not answer")
    assert "password" not in response.text


def test_the_openapi_document_declares_problems_for_validation_errors() -> None:
    document = create_app(eval_ui=True).openapi()

    capture = document["paths"]["/v1/eval/capture"]["post"]["responses"]["422"]
    assert capture["content"]["application/problem+json"]["schema"] == {"$ref": "#/components/schemas/Problem"}
    assert "HTTPValidationError" not in document["components"]["schemas"]
    assert "422" not in document["paths"]["/healthz"]["get"]["responses"]  # it takes no input


def test_the_openapi_document_is_served_under_v1_only() -> None:
    app = create_app(eval_ui=False)

    served = _request(app, "GET", "/v1/openapi.json")
    unversioned = _request(app, "GET", "/openapi.json")

    assert served.status_code == 200
    assert "/healthz" in served.json()["paths"]
    assert unversioned.status_code == 404
    assert _problem(unversioned)["type"] == "not_found"
