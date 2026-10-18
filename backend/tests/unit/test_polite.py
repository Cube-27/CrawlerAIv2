"""The one polite fetch (SPEC-02 §4.6, `services.polite`): robots.txt, a turn at the host's rate (waited for in place
up to the caller's bound, or postponed by a worker), the observation, and the host paused by the one back-off rule
after a slow-down. Hosts are synthetic (`.test`, RFC 2606); nothing goes to the network."""

import asyncio
import time
from datetime import UTC, datetime, timedelta

import pytest

from crawlerai.acquire.outcome import Content, Exchange, fetch_result
from crawlerai.acquire.politeness import BACKOFF_MAX, Admit, HostLimiter
from crawlerai.acquire.robots import Robots
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.core.retry import FIRST_BACKOFF
from crawlerai.services.polite import (
    IN_PLACE,
    QUEUED,
    ROBOTS,
    ROBOTS_UNREACHABLE,
    SLOW_DOWN,
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


class Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


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


@pytest.mark.parametrize(
    ("headers", "pause"),
    [
        ((("Retry-After", "20"),), timedelta(seconds=20)),
        ((), FIRST_BACKOFF),
        ((("Retry-After", "86400"),), BACKOFF_MAX),
        # No pause asked: the next turn is the spacing, doubled by the slow-down answer (`HostLimiter._slowed`).
        ((("Retry-After", "0"),), timedelta(seconds=2)),
    ],
)
def test_a_slow_down_pauses_the_host_by_the_one_back_off(headers: HeaderList, pause: timedelta) -> None:
    # SPEC-02 §4.6: the Retry-After, else the first backoff, and the longest backoff for a longer ask.
    limiter = HostLimiter(Clock())

    result = _fetch(Site(429, headers), limiter)

    assert isinstance(result, FetchResult)
    assert result.block_class == "blocked"
    assert limiter.admit(HOST, timedelta(seconds=1)) == pause


def test_a_caller_that_waits_does_not_take_a_turn_further_off_than_its_bound() -> None:
    clock = Clock()
    limiter = HostLimiter(clock)
    limiter.pause(HOST, IN_PLACE.bound + timedelta(seconds=1))
    site = Site()

    assert _fetch(site, limiter) == Refused(SLOW_DOWN)
    assert site.sent == []


def test_a_worker_postpones_the_first_request_until_the_hosts_turn() -> None:
    clock = Clock()
    limiter = HostLimiter(clock)
    site = Site()

    first = _fetch(site, limiter, waiting=QUEUED)
    clock.now += 0.25
    second = _fetch(site, limiter, waiting=QUEUED)

    assert isinstance(first, FetchResult)
    assert second == Later(timedelta(seconds=0.75))
    assert site.sent == [URL]


def test_an_ok_page_leaves_the_host_unpaused() -> None:
    clock = Clock()
    limiter = HostLimiter(clock)

    _fetch(Site(), limiter)
    clock.now += 1

    assert limiter.admit(HOST, timedelta(seconds=1)) == timedelta(0)
