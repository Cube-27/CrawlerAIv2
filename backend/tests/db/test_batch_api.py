"""`POST /v1/batch/scrape` over HTTP (SPEC-10 §4.3): what a client sends and gets back. What a batch does is the
service's and the worker's (`test_batch_scrape.py`).

The app runs as `submit_client` (conftest) sets it up: nothing leaves the process. Hosts are RFC 2606 names.
"""

from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.db.models import ApiKey, Job, UrlTask
from tests.db.conftest import PRIVATE_HOST

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


async def test_a_batch_records_the_key_that_submitted_it(submit_client: httpx.AsyncClient, engine: AsyncEngine) -> None:
    response = await _post(
        submit_client, urls=[URL], formats=["markdown"], webhook_url="https://hooks.example.test/done"
    )

    job_id = response.json()["job_id"]
    async with engine.connect() as conn:
        label = select(ApiKey.label).join(Job, Job.api_key_id == ApiKey.id).where(Job.id == job_id)
        assert (await conn.execute(label)).scalar_one() == "submit-api-test"  # its secret signs the webhook


async def test_a_private_target_is_refused_with_the_member_that_names_it(
    submit_client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    response = await _post(submit_client, urls=[URL, f"https://{PRIVATE_HOST}/admin"], formats=["markdown"])

    assert response.status_code == 422, response.text
    body = response.json()
    assert (body["type"], [error["field"] for error in body["errors"]]) == ("ssrf_rejected", ["urls[1]"])
    assert PRIVATE_HOST not in response.text
    async with engine.connect() as conn:
        assert (await conn.execute(select(Job.id).where(Job.kind == "batch_scrape"))).all() == []


async def test_batch_problems(submit_client: httpx.AsyncClient) -> None:
    schema = {"id": "01a13754-8791-738c-86ed-bc3b329d7fb1"}
    responses = {
        "prompt": await _post(
            submit_client, urls=[URL], formats=["records"], schema={"prompt": "kettles"}, page_kind="detail"
        ),
        "records with markdown": await _post(
            submit_client, urls=[URL], formats=["records", "markdown"], schema=schema, page_kind="detail"
        ),
        "no engine data": await _post(
            submit_client, urls=[URL], formats=["records"], schema=schema, page_kind="detail"
        ),
    }

    statuses = {name: (r.status_code, r.json()["type"]) for name, r in responses.items()}
    assert statuses == {
        "prompt": (422, "validation"),
        "records with markdown": (422, "validation"),
        "no engine data": (503, "records_unavailable"),
    }
