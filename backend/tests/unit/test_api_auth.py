"""Bearer authentication and the rate limit in front of it (SPEC-07 §4.2), through a route that requires a key. The
database behind the key lookup is a stub here; `tests/db/test_api_keys.py` runs the lookup against Postgres."""

import asyncio
from typing import Annotated, Any

import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI

from crawlerai.api.app import create_app
from crawlerai.api.auth import require_api_key
from crawlerai.db.models import ApiKeyId

UNTRUSTED_PEER = "192.0.2.1"


class UnreachableDatabase:
    """Stands in for the engine: counts the lookups that reach it, and fails each one."""

    def __init__(self) -> None:
        self.lookups = 0

    def begin(self) -> Any:
        self.lookups += 1
        raise ConnectionRefusedError


def _app(monkeypatch: pytest.MonkeyPatch, *, burst: int, trusted: str = "[]") -> FastAPI:
    monkeypatch.setenv("CRAWLERAI_API_RATE_PER_S", "0.1")  # one token per 10 s: no refill within a test
    monkeypatch.setenv("CRAWLERAI_API_RATE_BURST", str(burst))
    monkeypatch.setenv("CRAWLERAI_TRUSTED_PROXIES", trusted)
    app = create_app(eval_ui=False)
    router = APIRouter()

    @router.get("/v1/whoami")
    async def whoami(key: Annotated[ApiKeyId, Depends(require_api_key)]) -> dict[str, str]:
        return {"key": str(key)}

    app.include_router(router)
    app.state.database = UnreachableDatabase()
    return app


def _get(app: FastAPI, *requests: dict[str, str], peer: str = UNTRUSTED_PEER) -> list[httpx.Response]:
    async def send() -> list[httpx.Response]:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False, client=(peer, 50000))
        async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as client:
            return [await client.get("/v1/whoami", headers=headers) for headers in requests]

    return asyncio.run(send())


def _problem_type(response: httpx.Response) -> str:
    assert response.headers["content-type"] == "application/problem+json"
    problem_type: str = response.json()["type"]
    return problem_type


@pytest.mark.parametrize(
    "headers",
    [{}, {"authorization": "Basic Y2s6eA=="}, {"authorization": "Bearer"}],
    ids=["none", "basic", "bearer-without-token"],
)
def test_a_request_without_a_bearer_key_is_unauthorized_without_a_lookup(
    monkeypatch: pytest.MonkeyPatch, headers: dict[str, str]
) -> None:
    app = _app(monkeypatch, burst=5)

    [response] = _get(app, headers)

    assert response.status_code == 401
    assert _problem_type(response) == "unauthorized"
    assert response.headers["www-authenticate"] == "Bearer"  # RFC 6750 §3
    assert app.state.database.lookups == 0


def test_an_untrusted_peer_cannot_take_a_fresh_bucket_by_forwarding_another_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app(monkeypatch, burst=1, trusted='["10.0.0.0/8"]')

    responses = _get(
        app,
        {"x-forwarded-for": "203.0.113.5"},
        {"x-forwarded-for": "203.0.113.6"},
        {"forwarded": "for=203.0.113.7"},
    )

    assert [response.status_code for response in responses] == [401, 429, 429]


def test_every_api_operation_but_healthz_refuses_a_request_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # SPEC-07 §4.2, SPEC-03 §4.10: every route takes the API key, which also rate-limits it; `/healthz` alone is public
    # (ARCHITECTURE §18). A router added without the key dependency fails here. The burst covers every operation from
    # one client, so the rate limit answers none of them.
    monkeypatch.setenv("CRAWLERAI_API_RATE_BURST", "1000")
    app = create_app(eval_ui=True)
    operations = [
        (method.upper(), path.replace("{", "").replace("}", ""))
        for path, item in app.openapi()["paths"].items()
        for method in item
        if path != "/healthz"  # public, and it reads the database, which this app has none of
    ]

    async def statuses() -> dict[tuple[str, str], int]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as client:
            return {(method, path): (await client.request(method, path)).status_code for method, path in operations}

    answered = asyncio.run(statuses())

    assert len(answered) > 20
    assert {operation: status for operation, status in answered.items() if status != 401} == {}
