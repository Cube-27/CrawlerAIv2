"""What the services that fetch while their caller waits (`scrape`, `map`, `extract`) and the worker's handlers fetch
with: the rungs and guard of this process, the SSRF guard's refusals (INV-16), and the page fetch they send through
the one polite fetch (`services.polite`, SPEC-02 §4.6): the page through `acquire`, its adapter's and active config's
API recipe's requests sent as politely as a page's (SPEC-09 §4.8, SPEC-15 §4.6), as a learning run's recipe replays
are (§4.6, §4.7), and the plain HTTP fetches of a site's sitemaps.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from functools import partial
from urllib.parse import urlsplit

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.politeness import Admit, HostLimiter
from crawlerai.acquire.rungs import RenderCheck, Rung, Rungs, acquire
from crawlerai.acquire.ssrf import SSRF_REJECTED, SafeConnector, SsrfRejected
from crawlerai.acquire.types import AttemptRecord, BrowserActions, FetchPolicy, FetchResult, PagedFetch, Validators
from crawlerai.config_ir.api_recipe.execute import MAX_PAGES, RecipeRung, unserved
from crawlerai.config_ir.api_recipe.model import ApiRecipe
from crawlerai.config_ir.api_recipe.replay import Replay, Replays
from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.core.errors import Refusal
from crawlerai.crawl.paging import collect
from crawlerai.crawl.sitemaps import MAX_SITEMAP_BYTES
from crawlerai.db.models import JobId, Site
from crawlerai.recurring.conditional import Unchanged, fetch_unless_unchanged
from crawlerai.services.polite import (
    IN_PLACE,
    SLOW_DOWN,
    HostRules,
    PageFetch,
    ReadRules,
    Refused,
    Waiting,
    page_first,
    polite_fetch,
    rules_of,
)
from crawlerai.services.scrape_steps import SiteRow, record_fetch_usage
from crawlerai.storage.base import ObjectStore


@dataclass(frozen=True)
class Fetching:
    """What a service fetches with: the rungs, the SSRF guard they connect through, the object store captures go to,
    and the per-host limiter (SPEC-02 §4.6) of this process."""

    rungs: Rungs
    connector: SafeConnector
    store: ObjectStore
    limiter: HostLimiter
    # The names of the configured proxy pools (`CRAWLERAI_PROXY_POOLS`), which a request's `fetch.proxy_pool` is
    # checked against (D-1434).
    proxy_pools: frozenset[str] = frozenset()


class TargetRejected(Refusal):
    """The SSRF guard refused the target, or a redirect from it (INV-16). `reason` is the guard's, without the URL."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class TargetsRejected(Refusal):
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


def site_rungs(fetching: Fetching, host: str, site: SiteRow) -> Rungs:
    """This process's rungs with an adapter registry knowing the declines stored on the site of `host` (D-1384)."""
    return replace(fetching.rungs, adapters=fetching.rungs.adapters.for_host(host, site.adapter_declined))


async def store_declines(conn: AsyncConnection, site: SiteRow, host: str, rungs: Rungs) -> None:
    """Store on the site of `host` the adapter declines `rungs` hold for it (`site_rungs`) when they differ from what
    its row held: a decline made, or one that ran out (D-1384)."""
    declined = rungs.adapters.declined_for(host)
    if declined != site.adapter_declined:
        await conn.execute(update(Site).where(Site.id == site.id).values(adapter_declined=declined))


@dataclass
class _Turn:
    """The host whose turn at its rate the caller was admitted for, until a request takes it."""

    host: str | None

    def take(self, host: str) -> bool:
        taken = host == self.host
        if taken:
            self.host = None
        return taken


def recipe_rung(
    fetching: Fetching, recipe: ApiRecipe, page_host: str, rules: ReadRules, waiting: Waiting = IN_PLACE
) -> RecipeRung | None:
    """`recipe` bound to this process's rungs (SPEC-09 §4.8), for a page on `page_host` whose robots.txt the caller
    has checked and whose turn at the host's rate it has taken. That turn goes to the first request to the host: the
    HTML page the recipe fetches to bind, or else its endpoint. An endpoint is requested only where its host's
    robots.txt (`rules`) allows it, at that host's rate, waiting in place for a turn of its own when it needs one; a
    request robots.txt keeps from being sent leaves the page unserved, and `acquire` fetches it the configured way
    (§4.10). None without the JSON rung."""
    json = fetching.rungs.json
    if json is None:
        return None
    turn = _Turn(page_host)
    http = fetching.rungs.http

    async def page(url: str, policy: FetchPolicy) -> FetchResult:
        turn.host = None  # the page is the first request: its host's turn is the one the caller took
        return await http(url, policy)

    return RecipeRung(recipe, _polite_send(fetching, json, rules, turn, waiting), page, ENGINE_VERSION)


def adapter_send(
    fetching: Fetching, page_host: str, rules: ReadRules, waiting: Waiting = IN_PLACE
) -> JsonFetcher | None:
    """The JSON fetch an adapter requests its API with (SPEC-15 §4.6), for a page on `page_host` whose robots.txt the
    caller has checked and whose turn at the host's rate it has taken: an endpoint is requested only where its host's
    robots.txt (`rules`) allows it, at that host's rate; the first request to the page's host takes the caller's turn,
    as a recipe's does. A request robots.txt keeps from being sent leaves the page to the page rungs. None without the
    JSON rung."""
    json = fetching.rungs.json
    if json is None:
        return None
    return _polite_send(fetching, json, rules, _Turn(page_host), waiting)


def _polite_send(
    fetching: Fetching, json: JsonFetcher, rules: ReadRules, turn: _Turn, waiting: Waiting = IN_PLACE
) -> JsonFetcher:
    """Each request sent through the polite fetch to its endpoint's host (`polite_fetch`), the first request to the
    page's host on the caller's turn (`turn`); one robots.txt keeps from being sent, or whose turn is further off than
    the caller waits, answers `blocked` with the reason and sends nothing."""

    async def send(request: JsonRequest, policy: FetchPolicy) -> FetchResult:
        async def fetch(_url: str, _admit: Admit, _known: HostRules) -> FetchResult:
            return await json(request, policy)

        host = urlsplit(request.url).hostname or ""
        result = await polite_fetch(
            request.url,
            policy,
            rules,
            fetching.limiter,
            replace(waiting, postpone=False),
            fetch,
            turn_taken=turn.take(host),
            endpoint=True,
        )
        if isinstance(result, FetchResult):
            return result
        # A request not sent is the recipe's or adapter's unserved page, as a page robots.txt keeps out is `blocked`.
        reason = result.reason if isinstance(result, Refused) else SLOW_DOWN
        return unserved(request.page_url, policy, ENGINE_VERSION, "blocked", reason)

    return send


def learning_replay(engine: AsyncEngine, fetching: Fetching) -> Replays | None:
    """A learning run's recipe replays (SPEC-09 §4.6, §4.7) over this process's JSON rung, as politely as a served
    recipe's request: only where the endpoint host's robots.txt allows it, at that host's rate (D-0731). A `learn` job
    names no fetch policy, so replays go with the default one, which respects robots.txt, through the site's proxy
    pool, as its pages are fetched; their requests, robots.txt's too, count as the job's usage (D-1381). None without
    the JSON rung."""
    json = fetching.rungs.json
    if json is None:
        return None

    def replays(job_id: JobId, proxy_pool: str | None) -> Replay:
        policy = FetchPolicy(proxy_pool=proxy_pool)

        async def replay(request: JsonRequest) -> FetchResult:
            attempts: list[AttemptRecord] = []
            rules = rules_of(engine, fetching.rungs.http, attempts)
            result = await _polite_send(fetching, json, rules, _Turn(None))(request, policy)
            async with engine.begin() as conn:
                await record_fetch_usage(conn, job_id, [*attempts, *result.attempts], proxy_pool)
            return result

        return replay

    return replays


@dataclass
class RecipePages:
    """A listing's pages as its active config's listing recipe (one with pagination, Appendix A #59) serves them, up
    to `limit` requests; the pages after the first are kept in `further` and their attempts added to `attempts`."""

    limit: int = MAX_PAGES
    attempts: list[AttemptRecord] = field(default_factory=list)
    further: list[FetchResult] = field(default_factory=list)

    async def rung(self, recipe: RecipeRung, url: str, policy: FetchPolicy) -> Rung | None:
        """The recipe rung `acquire` fetches the page through: one that answers with the first page the listing recipe
        served, its further pages kept, so `acquire` keeps or falls back from that one answer as from any recipe's
        (SPEC-09 §4.8); None when it served no page. Each page request waits for its host's rate on its own
        (`recipe_rung`)."""
        pages = [page async for page in recipe.pages(url, policy, records=None, limit=self.limit)]
        if not pages:
            return None
        first, further = pages[0], pages[1:]
        self.attempts.extend(attempt for page in further for attempt in page.attempts)
        self.further[:] = _until_refused(further) if first.block_class == "ok" else []

        async def served(_url: str, _policy: FetchPolicy) -> FetchResult:
            return first

        return served


def _until_refused(pages: Sequence[FetchResult]) -> list[FetchResult]:
    """The pages before the first one the SSRF guard refused a request of (INV-16): a refused page is never stored."""
    kept: list[FetchResult] = []
    for page in pages:
        if refusal(page) is not None:
            break
        kept.append(page)
    return kept


async def grown(
    fetching: Fetching,
    url: str,
    policy: FetchPolicy,
    actions: BrowserActions,
    deadline: float,
    admit_next: Admit,
    known: HostRules,
) -> PagedFetch:
    """The listing at `url` from the listing rung with the paging driver (`crawl.paging.collect`, owner #52): each
    action waits for a turn at the site's rate (`admit_next`), and a next page is followed only on the listing's own
    host, when its robots.txt (`known`) allows it."""
    rung = fetching.rungs.listing
    if rung is None:
        raise RuntimeError("this process has no listing rung")
    host = urlsplit(url).hostname or ""

    async def gate(next_url: str | None) -> bool:
        if next_url is not None and (urlsplit(next_url).hostname != host or not known.allows(next_url)):
            return False
        return await admit_next()

    return await rung(url, policy, partial(collect, request=actions, gate=gate, deadline=deadline))


@dataclass
class Growth:
    """A single-URL listing scrape's browser actions where its page is rendered (master plan 2026-10-18 decision 11,
    amending owner #52): the browser rung of the fetch grows the list toward `actions.records` until `deadline`, and
    keeps the document states it made in `paged`."""

    actions: BrowserActions
    deadline: float
    paged: list[PagedFetch] = field(default_factory=list)

    def rung(self, fetching: Fetching, admit_next: Admit, known: HostRules) -> Rung:
        async def browse(url: str, policy: FetchPolicy) -> FetchResult:
            paged = await grown(fetching, url, policy, self.actions, self.deadline, admit_next, known)
            self.paged.append(paged)
            return paged.pages[0]

        return browse

    def of(self, kept: FetchResult) -> PagedFetch | None:
        """The listing's states, when the fetch kept the first one."""
        first = self.paged[-1].pages[0] if self.paged else None
        same = first is not None and first.bundle.manifest.capture_id == kept.bundle.manifest.capture_id
        return self.paged[-1] if same else None


@dataclass(frozen=True)
class PagePlan:
    """How a page is fetched: the site's rungs (`site_rungs`), its row, the policy, the attempts every request of the
    fetch is added to, the site's active API `recipe` (with `pages` when it serves a listing in pages), the check that
    renders an HTTP page lacking what the caller reads (owner #49, #54), and the validators the page last answered with
    when a record stands for it (SPEC-11 §4.2); `growth`, a single-URL listing scrape's browser actions in `auto`
    (`Growth`)."""

    rungs: Rungs
    site: SiteRow
    policy: FetchPolicy
    attempts: list[AttemptRecord]
    recipe: ApiRecipe | None = None
    pages: RecipePages | None = None
    needs_render: RenderCheck | None = None
    validators: Validators | None = None
    has_record: bool = False
    growth: Growth | None = None


def _uses_recipe(page: PagePlan, url: str) -> bool:
    """Whether `acquire` fetches `url` through the recipe: not a page the policy captures as a file, nor one an adapter
    detects, so a listing recipe's pages are requested for no other."""
    return not page.policy.captures_page and not page.rungs.adapters.would_serve(url)


def page_fetch(fetching: Fetching, page: PagePlan, rules: ReadRules, waiting: Waiting) -> PageFetch:
    """The page through `acquire`, as the polite fetch calls it: the adapter that detects the URL and the active
    config's API recipe ask their endpoints politely (`adapter_send`, `recipe_rung`; endpoints on the page's host by the
    rules the polite fetch read, D-1384, others by `rules`), and every attempt is added to the request's attempts."""

    async def fetch(url: str, admit_next: Admit, known: HostRules) -> FetchResult | Unchanged:
        host = urlsplit(url).hostname or ""
        here = page_first(host, known, rules)
        send = adapter_send(fetching, host, here, waiting)
        rung: Rung | None = None
        recipe = None if page.recipe is None else recipe_rung(fetching, page.recipe, host, here, waiting)
        if recipe is not None:
            rung = (
                recipe
                if page.pages is None or not _uses_recipe(page, url)
                else await page.pages.rung(recipe, url, page.policy)
            )

        rungs = page.rungs
        if page.growth is not None:
            # The growing render serves every browser attempt, the one after a refusal too: that one opens no site
            # session (INV-29's exception), whose cookies serve later HTTP fetches only.
            rungs = replace(rungs, browser=page.growth.rung(fetching, admit_next, known), exporting=None)

        async def once(validators: Validators | None) -> FetchResult:
            result = await acquire(
                url,
                page.policy,
                page.site.fetch_method,
                rungs,
                recipe=rung,
                validators=validators,
                admit_next=admit_next,
                send=send,
                needs_render=page.needs_render,
            )
            page.attempts.extend(result.attempts)
            return result

        return await fetch_unless_unchanged(once, page.validators, has_record=page.has_record)

    return fetch


async def fetch_now(
    engine: AsyncEngine, fetching: Fetching, url: str, page: PagePlan, *, tries: int = 1
) -> FetchResult | str:
    """The page at `url` fetched while the caller waits (`polite_fetch`, `IN_PLACE`), or why nothing was sent
    (`polite.Refused`); the adapter declines it made are stored on the site (D-1384). Raises `TargetRejected` when the
    guard refused a request of the fetch (INV-16)."""
    host = urlsplit(url).hostname or ""
    rules = rules_of(engine, fetching.rungs.http, page.attempts)
    fetch = page_fetch(fetching, page, rules, IN_PLACE)
    by_adapter = page.rungs.adapters.would_serve(url)
    result = await polite_fetch(
        url, page.policy, rules, fetching.limiter, IN_PLACE, fetch, by_adapter=by_adapter, tries=tries
    )
    async with engine.begin() as conn:
        await store_declines(conn, page.site, host, page.rungs)
    if isinstance(result, Refused):
        return result.reason
    if not isinstance(result, FetchResult):  # no validators are sent and nothing is postponed while the caller waits
        raise TypeError(f"a fetch the caller waits for answered {type(result).__name__}")
    if (refused := refusal(result)) is not None:
        raise TargetRejected(refused)
    return result


@dataclass(frozen=True)
class SiteHttp:
    """Plain HTTP fetches from one site through the polite fetch (robots.txt by its known `rules`, the site's rate,
    back-off), each with its attempts added to `attempts`: a site's sitemaps."""

    fetching: Fetching
    rules: HostRules
    policy: FetchPolicy
    attempts: list[AttemptRecord]
    waiting: Waiting = IN_PLACE

    async def fetch(self, url: str, policy: FetchPolicy) -> FetchResult | None:
        """`url` as fetched, or None when nothing was sent (robots.txt, or the host's turn too far off). Raises
        `TargetRejected` when the guard refused a request of the fetch."""
        http = self.fetching.rungs.http

        async def known(_url: str, _policy: FetchPolicy) -> HostRules:
            return self.rules

        async def once(target: str, _admit: Admit, _known: HostRules) -> FetchResult:
            result = await http(target, policy)
            self.attempts.extend(result.attempts)
            return result

        result = await polite_fetch(url, policy, known, self.fetching.limiter, self.waiting, once, endpoint=True)
        if not isinstance(result, FetchResult):
            return None
        if (refused := refusal(result)) is not None:
            raise TargetRejected(refused)
        return result

    async def sitemap_body(self, url: str) -> bytes | None:
        """The body of the sitemap at `url`, or `None` when there is none to read: not sent, not a 2xx, or failed.
        Raises `TargetRejected` as `fetch` does."""
        # sitemaps.org: a sitemap may be up to 50 MB uncompressed, larger than a page may be.
        policy = self.policy.model_copy(
            update={"max_body_bytes": MAX_SITEMAP_BYTES, "max_decompressed_bytes": MAX_SITEMAP_BYTES}
        )
        result = await self.fetch(url, policy)
        if result is None or result.attempts[-1].error is not None:
            return None
        return result.bundle.body if 200 <= result.bundle.manifest.status_code < 300 else None
