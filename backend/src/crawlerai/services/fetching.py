"""What the services that fetch while their caller waits (`scrape`, `map`) share, and the worker's handlers fetch with:
the rungs and guard of this process, the SSRF guard's refusals (INV-16), a site's robots.txt rules, and admission at
its rate (SPEC-02 §4.6).
"""

import asyncio
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.politeness import HostLimiter, interval
from crawlerai.acquire.robots import Fetch, Robots, site_robots
from crawlerai.acquire.rungs import Rung, Rungs
from crawlerai.acquire.ssrf import SSRF_REJECTED, SafeConnector, SsrfRejected
from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult
from crawlerai.crawl.sitemaps import MAX_SITEMAP_BYTES
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


class TargetsRejected(Exception):
    """The SSRF guard refused a target a request names (INV-16): `member` names it (`urls[3]`, `webhook_url`), `reason`
    is the guard's, without the URL."""

    def __init__(self, member: str, reason: str) -> None:
        super().__init__(f"{member}: {reason}")
        self.member = member
        self.reason = reason


async def check_targets(
    connector: SafeConnector, targets: list[tuple[str, str]], *, webhook_url: str | None = None
) -> None:
    """Check each of `targets`, (member, URL) pairs, and the request's `webhook_url` with the guard, before anything
    is fetched or stored. Raises `TargetsRejected` for the first refused one in order."""
    if webhook_url is not None:
        targets = [*targets, ("webhook_url", webhook_url)]
    checked = await asyncio.gather(*(connector.check(url) for _, url in targets), return_exceptions=True)
    for (member, _), result in zip(targets, checked, strict=True):
        if isinstance(result, SsrfRejected):
            raise TargetsRejected(member, str(result))
        if isinstance(result, BaseException):
            raise result


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

    async with engine.begin() as conn:
        return await site_robots(conn, site.id, site.robots_snapshot, url, recording(http, policy, attempts))


def recording(rung: Rung, policy: FetchPolicy, attempts: list[AttemptRecord]) -> Fetch:
    """A fetch through `rung` with `policy` that adds the attempts of each fetch to `attempts`."""

    async def fetch(url: str) -> FetchResult:
        result = await rung(url, policy)
        attempts.extend(result.attempts)
        return result

    return fetch


async def admitted(limiter: HostLimiter, host: str, crawl_delay_ms: int | None, robots: Robots | None) -> None:
    """Wait until the site's rate admits a request (SPEC-02 §4.6). The caller is waiting anyway, so the service waits
    in place, within its timeout, where a worker would postpone the task."""
    gap = interval(crawl_delay_ms, None if robots is None else robots.crawl_delay)
    while wait := limiter.admit(host, gap):
        await asyncio.sleep(wait.total_seconds())


@dataclass(frozen=True)
class PoliteHttp:
    """Fetches from one site while the caller waits: politely (robots.txt when `robots` is given, the site's rate),
    over HTTP with `policy`, recording the attempts of every fetch in `attempts`."""

    fetching: Fetching
    host: str
    crawl_delay_ms: int | None
    robots: Robots | None
    policy: FetchPolicy
    attempts: list[AttemptRecord]

    async def fetch(self, url: str, policy: FetchPolicy) -> FetchResult | None:
        """`url` as fetched, or `None` when robots.txt disallows it. Raises `TargetRejected` when the guard refused a
        request of the fetch."""
        if self.robots is not None and not self.robots.allows(url):
            return None
        await admitted(self.fetching.limiter, self.host, self.crawl_delay_ms, self.robots)
        result = await self.fetching.rungs.http(url, policy)
        self.attempts.extend(result.attempts)
        if (refused := refusal(result)) is not None:
            raise TargetRejected(refused)
        return result

    async def sitemap_body(self, url: str) -> bytes | None:
        """The body of the sitemap at `url`, or `None` when there is none to read: disallowed, not a 2xx, or failed.
        Raises `TargetRejected` as `fetch` does."""
        # sitemaps.org: a sitemap may be up to 50 MB uncompressed, larger than a page may be.
        policy = self.policy.model_copy(
            update={"max_body_bytes": MAX_SITEMAP_BYTES, "max_decompressed_bytes": MAX_SITEMAP_BYTES}
        )
        result = await self.fetch(url, policy)
        if result is None or result.attempts[-1].error is not None:
            return None
        return result.bundle.body if 200 <= result.bundle.manifest.status_code < 300 else None
