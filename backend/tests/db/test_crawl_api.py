"""`POST /v1/crawl` over HTTP: what a client sends and gets back. What a crawl does is the service's and
the worker's (`test_crawl.py`)."""

from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from snowcrawl.db.models import ApiKey, Job, UrlTask
from tests.db.support import KEY_LABEL, PRIVATE_HOST

pytestmark = pytest.mark.anyio

URL = "https://shop.example.test/"
RULES = [{"pattern": "https://shop.example.test/p/*", "page_kind": "detail"}]


async def _post(client: httpx.AsyncClient, **body: Any) -> httpx.Response:
    return await client.post("/v1/crawl", json=body)


async def test_a_crawl_is_accepted_with_its_start_task_and_key(
    submit_client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    response = await _post(submit_client, url=URL, formats=["markdown"], page_kind_rules=RULES)

    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    async with engine.connect() as conn:
        task = (await conn.execute(select(UrlTask.url, UrlTask.depth).where(UrlTask.job_id == job_id))).one()
        label = select(ApiKey.label).join(Job, Job.api_key_id == ApiKey.id).where(Job.id == job_id)
        assert (await conn.execute(label)).scalar_one() == KEY_LABEL  # its secret signs the webhook
    assert tuple(task) == (URL, 0)
    status = await submit_client.get(f"/v1/jobs/{job_id}")
    assert (status.json()["kind"], status.json()["counts"]["queued"]) == ("crawl", 1)


async def test_a_private_target_is_refused_with_the_member_that_names_it(
    submit_client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    response = await _post(submit_client, url=URL, formats=["markdown"], webhook_url=f"https://{PRIVATE_HOST}/done")

    assert response.status_code == 422, response.text
    body = response.json()
    assert (body["type"], [error["field"] for error in body["errors"]]) == ("ssrf_rejected", ["webhook_url"])
    assert PRIVATE_HOST not in response.text
    async with engine.connect() as conn:
        assert (await conn.execute(select(Job.id).where(Job.kind == "crawl"))).all() == []


async def test_crawl_problems(submit_client: httpx.AsyncClient) -> None:
    schema = {"id": "01a13754-8791-738c-86ed-bc3b329d7fb1"}
    records = {"url": URL, "formats": ["records"]}
    responses = {
        "prompt": await _post(submit_client, **records, schema={"prompt": "kettles"}, page_kind_rules=RULES),
        "no rules": await _post(submit_client, **records, schema=schema),
        "no engine data": await _post(submit_client, **records, schema=schema, page_kind_rules=RULES),
    }

    statuses = {name: (r.status_code, r.json()["type"]) for name, r in responses.items()}
    assert statuses == {
        "prompt": (422, "validation"),
        "no rules": (422, "validation"),
        "no engine data": (503, "records_unavailable"),
    }


async def test_a_crawl_needs_a_key(submit_client: httpx.AsyncClient) -> None:
    del submit_client.headers["authorization"]

    assert (await _post(submit_client, url=URL, formats=["markdown"])).status_code == 401
