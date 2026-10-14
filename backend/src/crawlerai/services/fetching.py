"""What the services that fetch while their caller waits (`scrape`, `map`) share, and the worker's handlers fetch with:
the rungs and guard of this process, the SSRF guard's refusals (INV-16), a site's robots.txt rules, and admission at
its rate (SPEC-02 §4.6).
"""

import asyncio
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.politeness import HostLimiter, interval
from crawlerai.acquire.robots import Robots, site_robots
from crawlerai.acquire.rungs import Rung, Rungs
from crawlerai.acquire.ssrf import SSRF_REJECTED, SafeConnector, SsrfRejected
from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult
from crawlerai.services.scrape_steps import SiteRow
from crawlerai.storage.base import ObjectStore


@dataclass(frozen=True)
class Fetching:
    """What a service fetches with: the rungs, the SSRF guard they connect through, the object store captures go to,
    and the per-host limiter (SPEC-02 §4.6) of this process."""

    rungs: Rungs
    connector: SafeConnector
    store: ObjectStore
    limiter: HostLimiter


class TargetRejected(Exception):
    """The SSRF guard refused the target, or a redirect from it (INV-16). `reason` is the guard's, without the URL."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def check_target(connector: SafeConnector, url: str) -> None:
    """Raise `TargetRejected` when the guard refuses `url`, before anything is fetched."""
    try:
        await connector.check(url)
    except SsrfRejected as e:
        raise TargetRejected(str(e)) from e


def refusal(result: FetchResult) -> str | None:
    """The guard's refusal of a request of the fetch, which a rung records as the attempt's error rather than raising
    (SPEC-02 §4.11); `None` when it refused none."""
    return next((a.error for a in result.attempts if a.error is not None and a.error.startswith(SSRF_REJECTED)), None)


async def site_rules(
    engine: AsyncEngine, http: Rung, site: SiteRow, url: str, policy: FetchPolicy, attempts: list[AttemptRecord]
) -> Robots | None:
    """The robots.txt rules for `url` on `site`, fetched over `http` when its snapshot is stale; `None` when robots.txt
    is unreachable. The attempts of a fetch of robots.txt are added to `attempts`."""

    async def fetch_robots(robots_url: str) -> FetchResult:
        result = await http(robots_url, policy)
        attempts.extend(result.attempts)
        return result

    async with engine.begin() as conn:
        return await site_robots(conn, site.id, site.robots_snapshot, url, fetch_robots)


async def admitted(limiter: HostLimiter, host: str, crawl_delay_ms: int | None, robots: Robots | None) -> None:
    """Wait until the site's rate admits a request (SPEC-02 §4.6). The caller is waiting anyway, so the service waits
    in place, within its timeout, where a worker would postpone the task."""
    gap = interval(crawl_delay_ms, None if robots is None else robots.crawl_delay)
    while wait := limiter.admit(host, gap):
        await asyncio.sleep(wait.total_seconds())
