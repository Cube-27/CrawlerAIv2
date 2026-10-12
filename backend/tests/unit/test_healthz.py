import asyncio

import httpx

from crawlerai.api.app import create_app


async def _get(path: str) -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://api.test") as client:
        return await client.get(path)


def test_healthz_returns_200_with_ok_status() -> None:
    response = asyncio.run(_get("/healthz"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
