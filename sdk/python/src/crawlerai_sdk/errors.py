"""What the SDK raises: the API's RFC 9457 problem as an exception, and the timeout of a wait."""

from __future__ import annotations

from typing import Any


class CrawlerAIError(Exception):
    """Base of every error the SDK raises."""


class APIError(CrawlerAIError):
    """The API answered with a problem document (a 4xx or 5xx). `status` is the HTTP status, `type` the problem's
    code (`validation`, `ssrf_rejected`, `search_unavailable`, ...), `errors` the members a 422 names."""

    def __init__(self, status: int, problem: dict[str, Any]) -> None:
        self.status = status
        self.problem = problem
        self.type: str = str(problem.get("type", "error"))
        self.title: str = str(problem.get("title", ""))
        self.detail: str = str(problem.get("detail", ""))
        self.errors: list[dict[str, Any]] = list(problem.get("errors") or [])
        super().__init__(f"{status} {self.type}: {self.detail or self.title}")


class JobTimeout(CrawlerAIError):
    """`wait_for_job` gave up before the job ended."""

    def __init__(self, job_id: str, seconds: float) -> None:
        self.job_id = job_id
        super().__init__(f"job {job_id} did not end within {seconds:g} s")
