"""The one polite fetch (SPEC-02 §4.6, `services.polite`): robots.txt, a turn at the host's rate (waited for in place
up to the caller's bound, or postponed by a worker), the observation, and the host paused by the one back-off rule
after a slow-down. Hosts are synthetic (`.test`, RFC 2606); nothing goes to the network."""

import asyncio
import time
from datetime import UTC, datetime

from crawlerai.acquire.outcome import Content, Exchange, fetch_result
from crawlerai.acquire.politeness import Admit, HostLimiter
from crawlerai.acquire.robots import Robots
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.services.polite import (
    IN_PLACE,
    ROBOTS,
    ROBOTS_UNREACHABLE,
    HostRules,
    Later,
    ReadRules,
    Refused,
    Waiting,
    polite_fetch,
)
from crawlerai.storage.capture_bundle import HeaderList

HOST = "shop.example.test"
URL = f"https://{HOST}/item/1"
ONE_SECOND = HostRules(1000)


class Site:
    """Answers every request with `status` and `headers`, and records what was sent."""

    def __init__(self, status: int = 200, headers: HeaderList = ()) -> None:
        self.status, self.headers = status, headers
        self.sent: list[str] = []

    async def __call__(self, url: str, _admit: Admit, _known: HostRules) -> FetchResult:
        self.sent.append(url)
        return fetch_result(
            url=url,
            method="http",
            policy=FetchPolicy(),
            engine_version="test",
            fetched_at=datetime.now(UTC),
            started=time.monotonic(),
            exchange=Exchange(url=url, status=self.status, request_headers=(), response_headers=self.headers),
            content=Content(body=b"<html></html>"),
            block_class="ok" if self.status < 400 else "blocked",
            error=None,
        )


def _rules(rules: HostRules | None) -> ReadRules:
    async def read(_url: str, _policy: FetchPolicy) -> HostRules | None:
        return rules

    return read


def _fetch(
    site: Site, limiter: HostLimiter, rules: HostRules | None = ONE_SECOND, waiting: Waiting = IN_PLACE
) -> FetchResult | Refused | Later:
    return asyncio.run(polite_fetch(URL, FetchPolicy(), _rules(rules), limiter, waiting, site))


def test_robots_txt_that_disallows_the_url_or_cannot_be_read_sends_nothing() -> None:
    site = Site()
    disallowing = HostRules(None, Robots("User-agent: *\nDisallow: /item/\n"))

    assert _fetch(site, HostLimiter(), disallowing) == Refused(ROBOTS)
    assert _fetch(site, HostLimiter(), None) == Refused(ROBOTS_UNREACHABLE)
    assert site.sent == []
