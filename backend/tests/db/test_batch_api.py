"""`POST /v1/batch/scrape` over HTTP (jobs spec): what a client sends and gets back. What a batch does is the
service's and the worker's (`test_batch_scrape.py`)."""

from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.db.models import UrlTask

pytestmark = pytest.mark.anyio

URL = "https://shop.example.test/kettles/blue"


async def _post(submit_client: httpx.AsyncClient, **body: Any) -> httpx.Response:
    return await submit_client.post("/v1/batch/scrape", json=body)


async def test_a_batch_is_accepted_and_queued(submit_client: httpx.AsyncClient, engine: AsyncEngine) -> None:
    response = await _post(submit_client, urls=[URL, URL.replace("blue", "red")], formats=["markdown"])

    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    async with engine.connect() as conn:
        tasks = (await conn.execute(select(UrlTask.status).where(UrlTask.job_id == job_id))).scalars().all()
    assert tasks == ["queued", "queued"]
    status = await submit_client.get(f"/v1/jobs/{job_id}")
    assert (status.json()["kind"], status.json()["counts"]["queued"]) == ("batch_scrape", 2)
