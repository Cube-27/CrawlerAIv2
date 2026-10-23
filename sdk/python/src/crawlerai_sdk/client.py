"""The CrawlerAI client, blocking (`CrawlerAI`) and asyncio (`AsyncCrawlerAI`), over httpx.

Every request method takes the request model of the endpoint (`models.SearchRequest`, ...) or its members as keyword
arguments, which are validated by the model before anything is sent and sent as given: a member left out stays out,
so the server's defaults apply. Answers are the endpoint's model. Jobs (`crawl`, `batch_scrape`, `extract`, a search
with `scrape`) answer at once with a job id: `wait_for_job` polls it to its end, `iter_job_results` pages its results
and `events` follows its run live.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Final, Self
from uuid import UUID

import httpx
from pydantic import BaseModel

from crawlerai_sdk import events as sse
from crawlerai_sdk import models
from crawlerai_sdk.errors import APIError, JobTimeout

JobId = str | UUID

DEFAULT_URL: Final = "http://localhost:8000"
ENDED: Final = frozenset({"completed", "failed", "cancelled"})  # the statuses a job does not leave


@dataclass(frozen=True)
class _Call[R]:
    """One request: where it goes, its body and query, and how its JSON answer is read."""

    method: str
    path: str
    read: Callable[[Any], R]
    body: dict[str, Any] | None = None
    params: dict[str, Any] | None = None


def _body[M: BaseModel](
    model: type[M], request: M | Mapping[str, Any] | None, fields: dict[str, Any]
) -> dict[str, Any]:
    """The JSON body of `request`, or of `fields`, validated by `model`; members never given are left out."""
    if request is not None and fields:
        raise TypeError("give the request or its members, not both")
    if isinstance(request, model):
        checked = request
    else:
        checked = model.model_validate(fields if request is None else request)
    body: dict[str, Any] = checked.model_dump(mode="json", by_alias=True, exclude_unset=True)
    return body


def _job(job_id: JobId) -> str:
    return str(job_id)


def _pause(poll_interval_s: float, deadline: float | None) -> float:
    """How long to sleep before the next poll: the interval, cut short at the deadline so the last poll happens at
    it rather than up to an interval after it."""
    if deadline is None:
        return poll_interval_s
    return max(0.0, min(poll_interval_s, deadline - time.monotonic()))


def _results_params(cursor: str | None, limit: int | None, format: str) -> dict[str, Any]:
    params: dict[str, Any] = {"format": format}
    if cursor is not None:
        params["cursor"] = cursor
    if limit is not None:
        params["limit"] = limit
    return params


class _Calls:
    """The endpoints, as calls; the two clients differ only in how they run one."""

    @staticmethod
    def post[M: BaseModel, A: BaseModel](
        path: str, model: type[M], answer: type[A], request: M | Mapping[str, Any] | None, fields: dict[str, Any]
    ) -> _Call[A]:
        return _Call("POST", path, lambda data: answer.model_validate(data), body=_body(model, request, fields))

    @staticmethod
    def job(job_id: JobId) -> _Call[models.JobSummary]:
        return _Call("GET", f"/v1/jobs/{_job(job_id)}", lambda data: models.JobSummary.model_validate(data))

    @staticmethod
    def cancel(job_id: JobId) -> _Call[models.JobSummary]:
        return _Call("DELETE", f"/v1/jobs/{_job(job_id)}", lambda data: models.JobSummary.model_validate(data))

    @staticmethod
    def results(job_id: JobId, cursor: str | None, limit: int | None) -> _Call[dict[str, Any]]:
        """A page of the job's results as JSON: `items` (records, or page outputs for a job without a schema) and the
        `next_cursor` of the next page, null at the end."""
        path = f"/v1/jobs/{_job(job_id)}/results"
        return _Call("GET", path, lambda data: dict(data), params=_results_params(cursor, limit, "json"))


def _raise_for(response: httpx.Response) -> None:
    if response.is_success:
        return
    try:
        problem = response.json()
    except ValueError:
        problem = {}
    raise APIError(response.status_code, problem if isinstance(problem, dict) else {"detail": response.text})


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


class CrawlerAI:
    """The blocking client. Use it as a context manager, or call `close`."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_URL,
        *,
        timeout: float = 300.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        # A scrape waits for its page, so the timeout is long; httpx's own default (5 s) is shorter than many fetches.
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"), headers=_headers(api_key), timeout=timeout, transport=transport
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _run[T](self, call: _Call[T]) -> T:
        response = self._http.request(call.method, call.path, json=call.body, params=call.params)
        _raise_for(response)
        return call.read(response.json())

    def scrape(self, request: models.ScrapeRequestInput | None = None, /, **fields: Any) -> models.ScrapeResult:
        """`POST /v1/scrape`: one page, fetched while you wait."""
        return self._run(_Calls.post("/v1/scrape", models.ScrapeRequestInput, models.ScrapeResult, request, fields))

    def map(self, request: models.MapRequestInput | None = None, /, **fields: Any) -> models.MapResult:
        """`POST /v1/map`: the URLs of a site."""
        return self._run(_Calls.post("/v1/map", models.MapRequestInput, models.MapResult, request, fields))

    def search(self, request: models.SearchRequest | None = None, /, **fields: Any) -> models.SearchResult:
        """`POST /v1/search`: web results; `scrape={...}` scrapes them in a batch job (`job_id` of the answer). Raises
        `APIError` with type `search_unavailable` (503) when the operator has configured no search provider."""
        return self._run(_Calls.post("/v1/search", models.SearchRequest, models.SearchResult, request, fields))

    def crawl(self, request: models.CrawlRequestInput | None = None, /, **fields: Any) -> models.CrawlSubmitted:
        """`POST /v1/crawl`: queue a crawl; `strategy="best_first"` with a `query` fetches the best-matching pages first."""
        return self._run(_Calls.post("/v1/crawl", models.CrawlRequestInput, models.CrawlSubmitted, request, fields))

    def batch_scrape(self, request: models.BatchScrapeRequestInput | None = None, /, **fields: Any) -> models.BatchSubmitted:
        """`POST /v1/batch/scrape`: queue a scrape of many URLs."""
        return self._run(
            _Calls.post("/v1/batch/scrape", models.BatchScrapeRequestInput, models.BatchSubmitted, request, fields)
        )

    def extract(self, request: models.ExtractRequestInput | None = None, /, **fields: Any) -> models.ExtractSubmitted:
        """`POST /v1/extract`: queue the extraction of a record from each URL."""
        return self._run(_Calls.post("/v1/extract", models.ExtractRequestInput, models.ExtractSubmitted, request, fields))

    def job(self, job_id: JobId) -> models.JobSummary:
        """`GET /v1/jobs/{id}`."""
        return self._run(_Calls.job(job_id))

    def cancel_job(self, job_id: JobId) -> models.JobSummary:
        """`DELETE /v1/jobs/{id}`: ask the job to stop."""
        return self._run(_Calls.cancel(job_id))

    def job_results(self, job_id: JobId, *, cursor: str | None = None, limit: int | None = None) -> dict[str, Any]:
        """One page of `GET /v1/jobs/{id}/results`."""
        return self._run(_Calls.results(job_id, cursor, limit))

    def iter_job_results(self, job_id: JobId, *, page_size: int | None = None) -> Iterator[dict[str, Any]]:
        """Every result of the job, page after page."""
        cursor: str | None = None
        while True:
            page = self.job_results(job_id, cursor=cursor, limit=page_size)
            yield from page["items"]
            cursor = page.get("next_cursor")
            if cursor is None:
                return

    def wait_for_job(
        self, job_id: JobId, *, poll_interval_s: float = 1.0, timeout_s: float | None = None
    ) -> models.JobSummary:
        """Poll the job until it is `completed`, `failed` or `cancelled`, and return its summary. Raises `JobTimeout`
        after `timeout_s` seconds (never, when None)."""
        deadline = None if timeout_s is None else time.monotonic() + timeout_s
        while True:
            summary = self.job(job_id)
            if summary.status.value in ENDED:
                return summary
            if deadline is not None and time.monotonic() >= deadline:
                raise JobTimeout(str(job_id), timeout_s or 0.0)
            time.sleep(_pause(poll_interval_s, deadline))

    def events(self, job_id: JobId, *, last_event_id: str | None = None) -> Iterator[sse.JobEvent]:
        """The job's run events live (`GET /v1/jobs/{id}/events`), until its end event; resume with the last id seen."""
        headers = {"Accept": "text/event-stream", **({} if last_event_id is None else {"Last-Event-ID": last_event_id})}
        with self._http.stream("GET", f"/v1/jobs/{_job(job_id)}/events", headers=headers) as response:
            if not response.is_success:
                response.read()
                _raise_for(response)
            yield from sse.parse(response.iter_lines())


class AsyncCrawlerAI:
    """The asyncio client: the methods of `CrawlerAI`, awaited. Use it with `async with`, or await `aclose`."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_URL,
        *,
        timeout: float = 300.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), headers=_headers(api_key), timeout=timeout, transport=transport
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        await self.aclose()

    async def _run[T](self, call: _Call[T]) -> T:
        response = await self._http.request(call.method, call.path, json=call.body, params=call.params)
        _raise_for(response)
        return call.read(response.json())

    async def scrape(self, request: models.ScrapeRequestInput | None = None, /, **fields: Any) -> models.ScrapeResult:
        return await self._run(_Calls.post("/v1/scrape", models.ScrapeRequestInput, models.ScrapeResult, request, fields))

    async def map(self, request: models.MapRequestInput | None = None, /, **fields: Any) -> models.MapResult:
        return await self._run(_Calls.post("/v1/map", models.MapRequestInput, models.MapResult, request, fields))

    async def search(self, request: models.SearchRequest | None = None, /, **fields: Any) -> models.SearchResult:
        return await self._run(_Calls.post("/v1/search", models.SearchRequest, models.SearchResult, request, fields))

    async def crawl(self, request: models.CrawlRequestInput | None = None, /, **fields: Any) -> models.CrawlSubmitted:
        return await self._run(_Calls.post("/v1/crawl", models.CrawlRequestInput, models.CrawlSubmitted, request, fields))

    async def batch_scrape(
        self, request: models.BatchScrapeRequestInput | None = None, /, **fields: Any
    ) -> models.BatchSubmitted:
        return await self._run(
            _Calls.post("/v1/batch/scrape", models.BatchScrapeRequestInput, models.BatchSubmitted, request, fields)
        )

    async def extract(self, request: models.ExtractRequestInput | None = None, /, **fields: Any) -> models.ExtractSubmitted:
        return await self._run(
            _Calls.post("/v1/extract", models.ExtractRequestInput, models.ExtractSubmitted, request, fields)
        )

    async def job(self, job_id: JobId) -> models.JobSummary:
        return await self._run(_Calls.job(job_id))

    async def cancel_job(self, job_id: JobId) -> models.JobSummary:
        return await self._run(_Calls.cancel(job_id))

    async def job_results(
        self, job_id: JobId, *, cursor: str | None = None, limit: int | None = None
    ) -> dict[str, Any]:
        return await self._run(_Calls.results(job_id, cursor, limit))

    async def iter_job_results(self, job_id: JobId, *, page_size: int | None = None) -> AsyncIterator[dict[str, Any]]:
        cursor: str | None = None
        while True:
            page = await self.job_results(job_id, cursor=cursor, limit=page_size)
            for item in page["items"]:
                yield item
            cursor = page.get("next_cursor")
            if cursor is None:
                return

    async def wait_for_job(
        self, job_id: JobId, *, poll_interval_s: float = 1.0, timeout_s: float | None = None
    ) -> models.JobSummary:
        deadline = None if timeout_s is None else time.monotonic() + timeout_s
        while True:
            summary = await self.job(job_id)
            if summary.status.value in ENDED:
                return summary
            if deadline is not None and time.monotonic() >= deadline:
                raise JobTimeout(str(job_id), timeout_s or 0.0)
            await asyncio.sleep(_pause(poll_interval_s, deadline))

    async def events(self, job_id: JobId, *, last_event_id: str | None = None) -> AsyncIterator[sse.JobEvent]:
        headers = {"Accept": "text/event-stream", **({} if last_event_id is None else {"Last-Event-ID": last_event_id})}
        async with self._http.stream("GET", f"/v1/jobs/{_job(job_id)}/events", headers=headers) as response:
            if not response.is_success:
                await response.aread()
                _raise_for(response)
            async for event in sse.aparse(response.aiter_lines()):
                yield event
