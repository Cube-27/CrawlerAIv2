"""How a fetch through a pool's endpoint counts toward its health: a cap, a decoding
error or an SSRF refusal counts neither way, whatever status the answer had."""

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from snowcrawl.acquire.outcome import Content, Exchange, fetch_result, report_proxy
from snowcrawl.acquire.types import BlockClass, FetchPolicy, FetchResult
from snowcrawl.core.proxy import ProxyEndpoint, ProxyPool

ENDPOINT = ProxyEndpoint.parse("http://proxy.example.com:3128")


@dataclass(frozen=True)
class _RecordingPool(ProxyPool):
    reports: list[bool | None] = field(default_factory=list, compare=False)

    def report(self, endpoint: ProxyEndpoint, healthy: bool | None) -> None:
        self.reports.append(healthy)


def _result(status: int, block_class: BlockClass, error: str | None) -> FetchResult:
    return fetch_result(
        url="https://www.example.test/",
        method="http",
        policy=FetchPolicy(),
        engine_version="test",
        fetched_at=datetime.now(UTC),
        started=time.monotonic(),
        exchange=Exchange(url="https://www.example.test/", status=status, request_headers=(), response_headers=()),
        content=Content(body=b"<html></html>"),
        block_class=block_class,
        error=error,
    )


@pytest.mark.parametrize("error", ["body_cap", "decode_error", "ssrf_rejected: private address"])
def test_a_failure_the_endpoint_has_no_part_in_is_not_reported_even_with_a_status(error: str) -> None:
    pool = _RecordingPool((ENDPOINT,))

    report_proxy(pool, ENDPOINT, _result(200, "error", error))

    assert pool.reports == []
