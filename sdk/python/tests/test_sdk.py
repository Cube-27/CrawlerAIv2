"""The SDK against a mock transport: what it sends, what it returns, and how it fails. Hosts are RFC 2606 names."""

import json
from collections.abc import Callable

import httpx
import pytest

from crawlerai_sdk import APIError, AsyncCrawlerAI, CrawlerAI, JobTimeout, models
from crawlerai_sdk import events as sse
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


def test_a_request_the_model_refuses_is_not_sent() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("nothing is sent")

    with pytest.raises(ValueError, match="query"):
        client(handler).search(limit=3)


def test_a_model_and_its_members_are_not_taken_together() -> None:
    request = models.SearchRequest(query="kettles")

    with pytest.raises(TypeError, match="not both"):
        client(lambda r: httpx.Response(200)).search(request, limit=3)


def test_a_problem_is_an_api_error_with_its_type_and_members() -> None:
    problem = {"type": "search_unavailable", "title": "Search unavailable", "detail": "no provider"}
    http = client(lambda request: httpx.Response(503, json=problem))

    with pytest.raises(APIError) as caught:
        http.search(query="kettles")

    assert (caught.value.status, caught.value.type, caught.value.detail) == (503, "search_unavailable", "no provider")


def test_search_with_scrape_returns_the_results_and_the_job() -> None:
    answer = {
        "query": "kettles",
        "results": [{"position": 1, "url": "https://a.example.test/", "title": "A", "snippet": "s"}],
        "job_id": JOB_ID,
        "skipped": 0,
    }
    bodies: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=answer)

    result = client(handler).search(query="kettles", limit=1, scrape={"formats": ["markdown"]})

    assert bodies == [{"query": "kettles", "limit": 1, "scrape": {"formats": ["markdown"]}}]
    assert [hit.url for hit in result.results] == ["https://a.example.test/"]
    assert str(result.job_id) == JOB_ID


def test_wait_for_job_polls_until_it_ends() -> None:
    statuses = iter(["queued", "running", "completed"])
    http = client(lambda request: httpx.Response(200, json=summary(next(statuses))))

    ended = http.wait_for_job(JOB_ID, poll_interval=0)

    assert ended.status.value == "completed"


def test_wait_for_job_times_out() -> None:
    http = client(lambda request: httpx.Response(200, json=summary("running")))

    with pytest.raises(JobTimeout):
        http.wait_for_job(JOB_ID, poll_interval=0.01, timeout=0.05)


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
    assert queries == [{"format": "json", "limit": "2"}, {"format": "json", "cursor": "c2", "limit": "2"}]


STREAM = (
    ": keep-alive\n\n"
    'id: 4\nevent: progress\ndata: {"done": 1}\n\n'
    'id: 5\nevent: completed\ndata: {"status":\ndata: "completed"}\n\n'
)


def test_events_parse_ids_kinds_and_multiline_data() -> None:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, content=STREAM.encode(), headers={"content-type": "text/event-stream"})

    events = list(client(handler).events(JOB_ID, last_event_id="3"))

    assert sent[0].headers["last-event-id"] == "3"
    assert events == [
        sse.JobEvent("progress", "4", {"done": 1}),
        sse.JobEvent("completed", "5", {"status": "completed"}),
    ]


@pytest.mark.anyio
async def test_the_async_client_runs_the_same_calls() -> None:
    statuses = iter(["running", "completed"])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/v1/jobs/{JOB_ID}/events":
            return httpx.Response(200, content=STREAM.encode())
        if request.method == "POST":
            return httpx.Response(202, json={"job_id": JOB_ID})
        return httpx.Response(200, json=summary(next(statuses)))

    async with AsyncCrawlerAI("k", "https://api.example.test", transport=httpx.MockTransport(handler)) as http:
        submitted = await http.batch_scrape(urls=["https://a.example.test/"], formats=["markdown"])
        ended = await http.wait_for_job(submitted.job_id, poll_interval=0)
        kinds = [event.kind async for event in http.events(submitted.job_id)]

    assert (ended.status.value, kinds) == ("completed", ["progress", "completed"])


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
