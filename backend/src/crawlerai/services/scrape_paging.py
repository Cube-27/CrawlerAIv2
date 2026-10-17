"""A scrape's browser actions (owner #52): the request member, its checks, and the paged fetch of a listing with the
gate its actions go through.

A listing scrape that asks for browser actions is fetched by the listing rung (`acquire.browser_tab.fetch_listing`)
with the paging driver (`crawl.paging.collect`), after robots.txt and the site's rate admit it, as `polite_fetch`
admits a page. Each action waits for the site's rate too, and a next page is admitted only on the same host, when
robots.txt allows it. The actions get at most half the scrape's `timeout_s`, and at most `MAX_ACTIONS_S`, so the kept
states' extraction still fits in the scrape (D-0028: `timeout_s` ≤ 120).

A site whose active config has a listing recipe (one with pagination, Appendix A #59) is served by it instead, over
HTTP with no browser: one response per page its pagination names, until the request's `records` target, each page
a further kept state; when the recipe does not serve the first page, the browser actions run (SPEC-09 §4.10).
"""

import time
from functools import partial
from typing import Final
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.politeness import Admit
from crawlerai.acquire.robots import Robots
from crawlerai.acquire.types import AttemptRecord, BrowserActions, FetchPolicy, FetchResult, PagedFetch
from crawlerai.config_ir.api_recipe.model import ApiRecipe
from crawlerai.config_ir.api_recipe.replay import Render
from crawlerai.crawl.paging import collect
from crawlerai.db.models import PageKind
from crawlerai.services.fetching import (
    Fetching,
    TargetRejected,
    admitted,
    engine_rules,
    recipe_rung,
    refusal,
    site_rules,
)
from crawlerai.services.scrape_steps import FetchOptions, SiteRow
from crawlerai.storage.capture_bundle import CaptureBundle

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
    if fetch.actions or fetch.wait_for is not None:
        # D-1439: a listing's paging driver acts on the settled page; the caller's steps do not run before it.
        raise ValueError("browser_actions takes no fetch.actions or fetch.wait_for")


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
    recipe: ApiRecipe | None = None,
) -> PagedFetch | str:
    """The listing at `url` with `actions`, or why robots.txt kept it from being fetched (SPEC-02 §4.6); served by
    `recipe`, the site's active API recipe, when it has pagination and serves the first page. The attempts,
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
    await admitted(fetching.limiter, host, site.crawl_delay_ms, robots)
    admit_next = partial(admitted, fetching.limiter, host, site.crawl_delay_ms, robots)
    served = await _recipe_pages(
        engine, fetching, url, host, policy, attempts, recipe, (actions.records, deadline), admit_next
    )
    if served is not None:
        return served
    rung = fetching.rungs.listing
    if rung is None:
        raise RuntimeError("this process has no listing rung")

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


async def _recipe_pages(
    engine: AsyncEngine,
    fetching: Fetching,
    url: str,
    host: str,
    policy: FetchPolicy,
    attempts: list[AttemptRecord],
    recipe: ApiRecipe | None,
    until: tuple[int, float],
    admit_next: Admit,
) -> PagedFetch | None:
    """The listing's pages as `recipe` serves them (`RecipeRung.pages`) when it has pagination, until the records
    target or the deadline of `until`, with their attempts added to `attempts`; None when it served no first page,
    after waiting for the turn of the request that follows. Each page request waits for its host's rate on its own
    (`recipe_rung`): the caller's admitted turn goes to the first."""
    if recipe is None or recipe.pagination is None:
        return None
    rung = recipe_rung(fetching, recipe, host, engine_rules(engine, fetching.rungs.http, attempts))
    if rung is None:
        return None
    records, deadline = until
    pages = [page async for page in rung.pages(url, policy, records=records, deadline=deadline)]
    for page in pages:
        attempts.extend(page.attempts)
        if (refused := refusal(page)) is not None:
            raise TargetRejected(refused)
    if not pages or pages[0].block_class != "ok":
        await admit_next()
        return None
    return PagedFetch(pages=tuple(pages), report=None)


# A learning render's browser actions stop past this many rows: two or three pages show how the listing asks for its
# next one (`api_recipe.pagination`), which is all learning reads of them.
RENDER_RECORDS: Final = 60


def learning_render(engine: AsyncEngine, fetching: Fetching) -> Render | None:
    """A learning run's browser renders (`api_recipe.learn`): the page politely (robots.txt, the site's rate), with
    network capture, a listing with browser actions toward `RENDER_RECORDS` rows; the document states kept, none for a
    page robots.txt disallows or that was not reached. A `learn` job names no fetch policy, so renders go with the
    default one. None without the listing rung."""
    listing = fetching.rungs.listing
    if listing is None:
        return None

    async def render(url: str, page_kind: PageKind) -> tuple[CaptureBundle, ...]:
        policy = FetchPolicy(method_hint="browser", page_kind=page_kind)
        rules = await engine_rules(engine, fetching.rungs.http, [])(url, policy)
        if isinstance(rules, str):  # robots.txt disallows the page, or could not be read
            return ()
        host = urlsplit(url).hostname or ""
        crawl_delay_ms, robots = rules
        await admitted(fetching.limiter, host, crawl_delay_ms, robots)
        if page_kind != "listing":
            pages: tuple[FetchResult, ...] = (await fetching.rungs.browser(url, policy),)
        else:

            async def gate(next_url: str | None) -> bool:
                if next_url is not None and not _allowed(next_url, host, robots):
                    return False
                return await admitted(fetching.limiter, host, crawl_delay_ms, robots)

            actions = BrowserActions(records=RENDER_RECORDS)
            drive = partial(collect, request=actions, gate=gate, deadline=time.monotonic() + MAX_ACTIONS_S)
            pages = (await listing(url, policy, drive)).pages
        return tuple(page.bundle for page in pages if page.block_class == "ok")

    return render


def _allowed(url: str, host: str, robots: Robots | None) -> bool:
    """A next page on the listing's own host that robots.txt allows: the rate and rules admitted are that host's."""
    return urlsplit(url).hostname == host and (robots is None or robots.allows(url))
