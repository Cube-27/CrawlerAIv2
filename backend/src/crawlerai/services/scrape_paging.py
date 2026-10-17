"""A scrape's browser actions (owner #52): the request member, its checks, and the paged fetch of a listing with the
gate its actions go through.

A listing scrape that asks for browser actions is fetched by the listing rung (`acquire.browser_tab.fetch_listing`)
with the paging driver (`crawl.paging.collect`), after robots.txt and the site's rate admit it, as `polite_fetch`
admits a page. Each action waits for the site's rate too, and a next page is admitted only on the same host, when
robots.txt allows it. The actions get at most half the scrape's `timeout_s`, and at most `MAX_ACTIONS_S`, so the kept
states' extraction still fits in the scrape (D-0028: `timeout_s` ≤ 120).
"""

import time
from functools import partial
from typing import Final
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.robots import Robots
from crawlerai.acquire.types import AttemptRecord, BrowserActions, FetchPolicy, PagedFetch
from crawlerai.crawl.paging import collect
from crawlerai.db.models import PageKind
from crawlerai.services.fetching import Fetching, TargetRejected, admitted, refusal, site_rules
from crawlerai.services.scrape_steps import FetchOptions, SiteRow

# D-1222: the actions' time cap; the probe's slowest passing listing took under 50 s.
MAX_ACTIONS_S: Final = 60.0
_TIMEOUT_SHARE: Final = 0.5


def check_browser_actions(
    actions: BrowserActions | None, page_kind: PageKind | None, max_age: int, fetch: FetchOptions
) -> None:
    """Browser actions are for a listing fetched now, in the browser (owner #52). Raises `ValueError`, for a request
    model's validator."""
    if actions is None:
        return
    if page_kind != "listing":
        raise ValueError("browser_actions needs page_kind listing")
    if max_age:
        raise ValueError("browser_actions fetches the page, so max_age must be 0")
    if fetch.method_hint == "http":
        raise ValueError("browser_actions runs in the browser, so method_hint cannot be http")


async def paged_fetch(
    engine: AsyncEngine,
    fetching: Fetching,
    url: str,
    host: str,
    policy: FetchPolicy,
    site: SiteRow,
    attempts: list[AttemptRecord],
    actions: BrowserActions,
    timeout_s: float,
) -> PagedFetch | str:
    """The listing at `url` with `actions`, or why robots.txt kept it from being fetched (SPEC-02 §4.6). The attempts,
    robots.txt's too, are added to `attempts`. Raises `TargetRejected` when the guard refused a request of the fetch
    (INV-16)."""
    deadline = time.monotonic() + min(MAX_ACTIONS_S, _TIMEOUT_SHARE * timeout_s)
    robots: Robots | None = None
    if policy.respect_robots:
        robots = await site_rules(engine, fetching.rungs.http, site, url, policy, attempts)
        # RFC 9309 §2.3.1.4: an unreachable robots.txt allows nothing.
        if robots is None:
            return "robots_unreachable"
        if not robots.allows(url):
            return "robots"
    rung = fetching.rungs.listing
    if rung is None:
        raise RuntimeError("this process has no listing rung")
    await admitted(fetching.limiter, host, site.crawl_delay_ms, robots)

    async def gate(next_url: str | None) -> bool:
        if next_url is not None and not _allowed(next_url, host, robots):
            return False
        return await admitted(fetching.limiter, host, site.crawl_delay_ms, robots)

    drive = partial(collect, request=actions, gate=gate, deadline=deadline)
    paged = await rung(url, policy, drive)
    for page in paged.pages:
        attempts.extend(page.attempts)
        if (refused := refusal(page)) is not None:
            raise TargetRejected(refused)
    return paged


def _allowed(url: str, host: str, robots: Robots | None) -> bool:
    """A next page on the listing's own host that robots.txt allows: the rate and rules admitted are that host's."""
    return urlsplit(url).hostname == host and (robots is None or robots.allows(url))
