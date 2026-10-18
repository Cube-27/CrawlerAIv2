"""The SDK against a mock transport: what it sends, what it returns, and how it fails. Hosts are RFC 2606 names."""

import json
import time
from collections.abc import Callable

import httpx
import pytest

from crawlerai_sdk import APIError, CrawlerAI, JobTimeout, models
from crawlerai_sdk.webhooks import InvalidSignature, parse_webhook, sign, verify_signature

JOB_ID = "0192a000-0000-7000-8000-0000000000aa"


def summary(status: str) -> dict[str, object]:
    return {
        "id": JOB_ID,
        "kind": "crawl",
        "status": status,
        "cancel_requested": False,
        "counts": {"queued": 0, "claimed": 0, "done": 1, "failed": 0, "cancelled": 0},
        "outcomes": dict.fromkeys(models.OutcomeCounts.model_fields, 0),
        "created_at": "2026-10-17T10:00:00Z",
        "engine_version": "x",
        "usage": {},
    }


def client(handler: Callable[[httpx.Request], httpx.Response]) -> CrawlerAI:
    return CrawlerAI("key-1", "https://api.example.test/", transport=httpx.MockTransport(handler))


def test_a_request_is_validated_and_sent_with_only_the_members_given() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(202, json={"job_id": JOB_ID})

    submitted = client(handler).crawl(
        url="https://docs.example.test/", formats=["markdown"], strategy="best_first", query="rate limits", max_depth=2
    )

    request = seen[0]
    assert (request.method, str(request.url), request.headers["authorization"]) == (
        "POST",
        "https://api.example.test/v1/crawl",
        "Bearer key-1",
    )
    assert json.loads(request.content) == {
        "url": "https://docs.example.test/",
        "formats": ["markdown"],
        "strategy": "best_first",
        "query": "rate limits",
        "max_depth": 2,
    }
    assert str(submitted.job_id) == JOB_ID


def test_a_problem_is_an_api_error_with_its_type_and_members() -> None:
    problem = {"type": "search_unavailable", "title": "Search unavailable", "detail": "no provider"}
    http = client(lambda request: httpx.Response(503, json=problem))

    with pytest.raises(APIError) as caught:
        http.search(query="kettles")

    assert (caught.value.status, caught.value.type, caught.value.detail) == (503, "search_unavailable", "no provider")


def test_wait_for_job_polls_until_it_ends_and_gives_up_at_the_deadline() -> None:
    statuses = iter(["queued", "running", "completed"])
    ended = client(lambda request: httpx.Response(200, json=summary(next(statuses)))).wait_for_job(
        JOB_ID, poll_interval_s=0
    )
    running = client(lambda request: httpx.Response(200, json=summary("running")))
    started = time.monotonic()

    with pytest.raises(JobTimeout):
        running.wait_for_job(JOB_ID, poll_interval_s=5, timeout_s=0.05)

    assert ended.status.value == "completed"
    assert time.monotonic() - started < 1


def test_job_results_are_paged_through_their_cursor() -> None:
    pages = {
        None: {"items": [{"n": 1}, {"n": 2}], "next_cursor": "c2"},
        "c2": {"items": [{"n": 3}], "next_cursor": None},
    }
    queries: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = dict(request.url.params)
        queries.append(query)
        return httpx.Response(200, json=pages[query.get("cursor")])

    items = list(client(handler).iter_job_results(JOB_ID, page_size=2))

    assert [item["n"] for item in items] == [1, 2, 3]
    assert len(queries) == 2


STREAM = (
    ": keep-alive\n\n"
    'id: 4\nevent: progress\ndata: {"done": 1}\n\n'
    'id: 5\nevent: completed\ndata: {"status":\ndata: "completed"}\n\n'
)


def test_a_webhook_is_verified_with_the_secret_and_the_exact_body() -> None:
    body = json.dumps(summary("completed")).encode()
    signature = sign("s3cret", body)

    assert signature.startswith("sha256=")
    assert verify_signature("s3cret", body, signature)
    assert not verify_signature("other", body, signature)
    assert not verify_signature("s3cret", body + b" ", signature)
    assert not verify_signature("s3cret", body, None)
    assert parse_webhook("s3cret", body, signature).status.value == "completed"
    with pytest.raises(InvalidSignature):
        parse_webhook("other", body, signature)
