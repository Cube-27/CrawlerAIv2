"""A scrape's browser actions (owner #52): the request member, its checks, and the paged fetch of a listing with the
gate its actions go through.

A listing scrape that asks for browser actions is fetched by the listing rung (`acquire.browser_tab.fetch_listing`)
with the paging driver (`crawl.paging.collect`), through the polite fetch (`services.polite`), as a page is. Each
action waits for the site's rate too, and a next page is admitted only on the same host, when robots.txt allows it.
The caller's `fetch.actions` and `wait_for` run first on the settled page (D-1513), and the site's API recipe is not
used then: the steps need the browser. The actions get at most half the scrape's `timeout_s`, and at most
`MAX_ACTIONS_S`, so the kept states' extraction still fits in the scrape (D-0028: `timeout_s` ≤ 120).

A site whose active config has a listing recipe (one with pagination, Appendix A #59) is served by it instead, over
HTTP with no browser: one response per page its pagination names, until the request's `records` target, each page
a further kept state; when the recipe does not serve the first page, the browser actions run (SPEC-09 §4.10).
"""

import time
from typing import Final
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.politeness import Admit
from crawlerai.acquire.types import AttemptRecord, BrowserActions, FetchPolicy, FetchResult, PagedFetch
from crawlerai.config_ir.api_recipe.model import ApiRecipe
from crawlerai.config_ir.api_recipe.replay import Render
from crawlerai.db.models import PageKind
from crawlerai.services.fetching import Fetching, TargetRejected, grown, recipe_rung, refusal
from crawlerai.services.polite import IN_PLACE, HostRules, ReadRules, Refused, polite_fetch, rules_of
from crawlerai.services.scrape_steps import FetchOptions, site_row
from crawlerai.storage.capture_bundle import CaptureBundle

# D-1222: the actions' time cap; the probe's slowest passing listing took under 50 s.
MAX_ACTIONS_S: Final = 60.0
_TIMEOUT_SHARE: Final = 0.5


def actions_deadline(timeout_s: float) -> float:
    """When a scrape's browser actions stop: at its actions' share of `timeout_s`, and at most `MAX_ACTIONS_S`, from
    now (on `time.monotonic`)."""
    return time.monotonic() + min(MAX_ACTIONS_S, _TIMEOUT_SHARE * timeout_s)


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
    policy: FetchPolicy,
    attempts: list[AttemptRecord],
    actions: BrowserActions,
    timeout_s: float,
    recipe: ApiRecipe | None = None,
) -> PagedFetch | str:
    """The listing at `url` with `actions` through the polite fetch (`polite_fetch`), or why nothing was sent; served by
    `recipe`, the site's active API recipe, when it has pagination and serves the first page. The attempts,
    robots.txt's too, are added to `attempts`. Raises `TargetRejected` when the guard refused a request of the fetch
    (INV-16)."""
    deadline = actions_deadline(timeout_s)
    rules = rules_of(engine, fetching.rungs.http, attempts)
    paged: list[PagedFetch] = []

    async def fetch(target: str, admit_next: Admit, known: HostRules) -> FetchResult:
        until = (actions.records, deadline)
        served = await _recipe_pages(fetching, target, policy, attempts, recipe, until, (rules, admit_next))
        if served is None:
            served = await grown(fetching, target, policy, actions, deadline, admit_next, known)
            record_states(served.pages, attempts)
        paged.append(served)
        return served.pages[0]

    result = await polite_fetch(url, policy, rules, fetching.limiter, IN_PLACE, fetch)
    if isinstance(result, Refused):
        return result.reason
    if not paged:  # the polite fetch sends nothing it does not answer, and postpones nothing in place
        raise RuntimeError("the listing was fetched without its pages")
    return paged[0]


def record_states(pages: tuple[FetchResult, ...], attempts: list[AttemptRecord]) -> None:
    """Add the attempts of `pages` to `attempts`. Raises `TargetRejected` when the guard refused a request of one."""
    for page in pages:
        attempts.extend(page.attempts)
        if (refused := refusal(page)) is not None:
            raise TargetRejected(refused)


async def _recipe_pages(
    fetching: Fetching,
    url: str,
    policy: FetchPolicy,
    attempts: list[AttemptRecord],
    recipe: ApiRecipe | None,
    until: tuple[int, float],
    polite: tuple[ReadRules, Admit],
) -> PagedFetch | None:
    """The listing's pages as `recipe` serves them (`RecipeRung.pages`) when it has pagination, until the records
    target or the deadline of `until`, with their attempts added to `attempts`; None when it served no first page,
    after waiting for the turn of the request that follows (`polite`'s `Admit`). Each page request waits for its host's
    rate on its own (`recipe_rung`, by `polite`'s rules): the caller's admitted turn goes to the first."""
    rules, admit_next = polite
    if recipe is None or recipe.pagination is None or policy.steps:
        # The caller's page steps (a cookie banner, a filter) change the page and need the browser (D-1513).
        return None
    rung = recipe_rung(fetching, recipe, urlsplit(url).hostname or "", rules)
    if rung is None:
        return None
    records, deadline = until
    pages = tuple([page async for page in rung.pages(url, policy, records=records, deadline=deadline)])
    record_states(pages, attempts)
    if not pages or pages[0].block_class != "ok":
        await admit_next()
        return None
    return PagedFetch(pages=tuple(pages), report=None)


# A learning render's browser actions stop past this many rows: two or three pages show how the listing asks for its
# next one (`api_recipe.pagination`), which is all learning reads of them.
RENDER_RECORDS: Final = 60


def learning_render(engine: AsyncEngine, fetching: Fetching) -> Render | None:
    """A learning run's browser renders (`api_recipe.learn`) through the polite fetch: the page with network capture, a
    listing with browser actions toward `RENDER_RECORDS` rows; the document states kept, none for a page that was not
    sent or not reached. A `learn` job names no fetch policy, so renders go with the default one, but for the site's:
    one that loads every resource (`site.load_all_resources`) is rendered with none blocked. None without the listing
    rung."""
    if fetching.rungs.listing is None:
        return None

    async def render(url: str, page_kind: PageKind) -> tuple[CaptureBundle, ...]:
        async with engine.begin() as conn:
            site = await site_row(conn, urlsplit(url).hostname or "", page_kind)
        policy = FetchPolicy(method_hint="browser", page_kind=page_kind, block_resources=not site.load_all_resources)
        kept: list[FetchResult] = []

        async def fetch(target: str, admit_next: Admit, known: HostRules) -> FetchResult:
            if page_kind != "listing":
                kept.append(await fetching.rungs.browser(target, policy))
            else:
                actions = BrowserActions(records=RENDER_RECORDS)
                deadline = time.monotonic() + MAX_ACTIONS_S
                kept.extend((await grown(fetching, target, policy, actions, deadline, admit_next, known)).pages)
            return kept[0]

        rules = rules_of(engine, fetching.rungs.http, [])
        await polite_fetch(url, policy, rules, fetching.limiter, IN_PLACE, fetch)
        return tuple(page.bundle for page in kept if page.block_class == "ok")

    return render
