"""`site.fetch_method` memory (SPEC-02 §4.4, ARCHITECTURE §7.1): set to `browser` when HTTP fails, or lacks what the
caller reads, and the browser passes, and back to `http` by the 7-day re-check when HTTP passes again.

The web is a stub answering synthetic pages on RFC 2606 hosts; no network.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.rungs import Rungs, acquire, remember_fetch_method
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.core.capture import BlockClass, CaptureMethod
from crawlerai.db.models import Capture, FetchMethod, Project, Site, SiteId
from crawlerai.scheduler.recheck import recheck_fetch_method

pytestmark = pytest.mark.anyio

ORIGIN = "https://shop.example.test"
PAGE = f"{ORIGIN}/item/1"
DEFAULT_PROJECT = select(Project.id).where(Project.name == "default").scalar_subquery()
LONG_AGO = func.now() - timedelta(days=8)


@dataclass
class Web:
    """Answers each URL with its outcome in `pages` (robots.txt allows everything unless set); anything else is a
    404. Records the URLs fetched."""

    fetch_result: Callable[..., FetchResult]
    method: CaptureMethod
    pages: dict[str, BlockClass] = field(default_factory=dict)
    robots: str = ""
    fetched: list[str] = field(default_factory=list)
    policies: list[FetchPolicy | None] = field(default_factory=list)  # one per fetch

    async def __call__(self, url: str, policy: FetchPolicy | None = None) -> FetchResult:
        self.fetched.append(url)
        self.policies.append(policy)
        if url == f"{ORIGIN}/robots.txt":
            return self.fetch_result(url, 200, self.robots.encode(), method=self.method)
        block_class = self.pages.get(url, "not_found")
        status = {"ok": 200, "shell": 200, "blocked": 403, "not_found": 404}.get(block_class, 500)
        return self.fetch_result(url, status, b"", block_class=block_class, method=self.method)


@pytest.fixture
def http(fetch_result: Callable[..., FetchResult]) -> Web:
    return Web(fetch_result, "http")


@pytest.fixture
def browser(fetch_result: Callable[..., FetchResult]) -> Web:
    return Web(fetch_result, "browser")


async def _site(conn: AsyncConnection, host: str = "shop.example.test", **columns: Any) -> SiteId:
    values = {"project_id": DEFAULT_PROJECT, "host": host, **columns}
    site_id: SiteId = (await conn.execute(insert(Site).values(**values).returning(Site.id))).scalar_one()
    return site_id


async def _capture(conn: AsyncConnection, site_id: SiteId, url: str, block_class: BlockClass, days_ago: int) -> None:
    await conn.execute(
        insert(Capture).values(
            site_id=site_id,
            url=url,
            final_url=url,
            method="browser",
            status_code=200,
            fetched_at=datetime.now(UTC) - timedelta(days=days_ago),
            block_class=block_class,
            object_key=f"captures/2026/10/{site_id}-{days_ago}.bundle.zst",
            html_sha256="0" * 64,
            size_bytes=1,
            duration_ms=1,
        )
    )


async def _memory(conn: AsyncConnection, site_id: SiteId) -> tuple[FetchMethod, datetime | None]:
    row = (await conn.execute(select(Site.fetch_method, Site.fetch_method_checked_at).where(Site.id == site_id))).one()
    return row.fetch_method, row.fetch_method_checked_at


async def _now(conn: AsyncConnection) -> datetime:
    now: datetime = (await conn.execute(select(func.now()))).scalar_one()
    return now


async def _acquire_and_remember(
    conn: AsyncConnection, site_id: SiteId, http: Web, browser: Web, policy: FetchPolicy | None = None
) -> FetchResult:
    remembered = (await _memory(conn, site_id))[0]
    result = await acquire(PAGE, policy or FetchPolicy(), remembered, Rungs(http=http, browser=browser))
    await remember_fetch_method(conn, site_id, result)
    return result


@pytest.mark.parametrize("http_outcome", ["shell", "blocked"])
async def test_http_failing_and_the_browser_passing_sets_the_site_to_browser(
    conn: AsyncConnection, http: Web, browser: Web, http_outcome: BlockClass
) -> None:
    site_id = await _site(conn)
    http.pages[PAGE], browser.pages[PAGE] = http_outcome, "ok"

    await _acquire_and_remember(conn, site_id, http, browser)

    assert await _memory(conn, site_id) == ("browser", await _now(conn))


async def test_a_render_kept_over_a_lacking_http_page_sets_the_site_to_browser_and_skips_http_next(
    conn: AsyncConnection, http: Web, browser: Web
) -> None:
    # D-1260: HTTP answered `ok` but lacked what the caller reads (owner #49, #54); the render held it.
    site_id = await _site(conn)
    http.pages[PAGE], browser.pages[PAGE] = "ok", "ok"

    async def lacking(result: FetchResult) -> bool:
        return result.method == "http"

    remembered = (await _memory(conn, site_id))[0]
    result = await acquire(PAGE, FetchPolicy(), remembered, Rungs(http=http, browser=browser), needs_render=lacking)
    await remember_fetch_method(conn, site_id, result)
    assert await _memory(conn, site_id) == ("browser", await _now(conn))

    http.fetched.clear()
    await _acquire_and_remember(conn, site_id, http, browser)
    assert http.fetched == []  # the next fetch goes straight to the browser


async def test_a_render_that_holds_no_more_than_http_leaves_the_site_on_http(
    conn: AsyncConnection, http: Web, browser: Web
) -> None:
    site_id = await _site(conn)
    http.pages[PAGE], browser.pages[PAGE] = "ok", "ok"

    async def lacking(result: FetchResult) -> bool:
        return True  # the render lacks it too: HTTP's page is kept

    result = await acquire(PAGE, FetchPolicy(), "http", Rungs(http=http, browser=browser), needs_render=lacking)
    await remember_fetch_method(conn, site_id, result)

    assert await _memory(conn, site_id) == ("http", None)


@pytest.mark.parametrize(
    ("http_outcome", "browser_outcome", "policy"),
    [
        ("ok", "ok", FetchPolicy()),  # HTTP passed: the browser never ran
        ("shell", "shell", FetchPolicy()),  # the browser did no better
        ("ok", "ok", FetchPolicy(method_hint="browser")),  # a browser fetch asked for is no evidence about HTTP
    ],
)
async def test_the_site_stays_on_http_without_evidence_for_the_browser(
    conn: AsyncConnection,
    http: Web,
    browser: Web,
    http_outcome: BlockClass,
    browser_outcome: BlockClass,
    policy: FetchPolicy,
) -> None:
    site_id = await _site(conn)
    http.pages[PAGE], browser.pages[PAGE] = http_outcome, browser_outcome

    await _acquire_and_remember(conn, site_id, http, browser, policy)

    assert await _memory(conn, site_id) == ("http", None)


async def test_more_evidence_for_a_site_already_on_browser_keeps_its_recheck_clock(
    conn: AsyncConnection, http: Web, browser: Web
) -> None:
    checked = datetime(2026, 10, 1, tzinfo=UTC)
    site_id = await _site(conn, fetch_method="browser", fetch_method_checked_at=checked)
    http.pages[PAGE], browser.pages[PAGE] = "shell", "ok"

    # A worker that read the site while it was still on `http`.
    result = await acquire(PAGE, FetchPolicy(), "http", Rungs(http=http, browser=browser))
    await remember_fetch_method(conn, site_id, result)

    assert await _memory(conn, site_id) == ("browser", checked)


async def test_a_shell_then_browser_ok_then_a_passing_recheck_goes_http_browser_http(
    conn: AsyncConnection, http: Web, browser: Web
) -> None:
    site_id = await _site(conn)
    http.pages[PAGE], browser.pages[PAGE] = "shell", "ok"
    result = await _acquire_and_remember(conn, site_id, http, browser)
    await _capture(conn, site_id, PAGE, result.block_class, days_ago=0)
    assert (await _memory(conn, site_id))[0] == "browser"

    assert await recheck_fetch_method(conn, http, batch=10) == 0  # not due for 7 days
    await conn.execute(update(Site).where(Site.id == site_id).values(fetch_method_checked_at=LONG_AGO))
    http.pages[PAGE] = "ok"
    assert await recheck_fetch_method(conn, http, batch=10) == 1

    assert await _memory(conn, site_id) == ("http", await _now(conn))
    remembered = (await _memory(conn, site_id))[0]
    after = await acquire(PAGE, FetchPolicy(), remembered, Rungs(http=http, browser=browser))
    assert [attempt.method for attempt in after.attempts] == ["http"]


async def test_a_recheck_that_fails_over_http_keeps_browser_until_the_next_turn(
    conn: AsyncConnection, http: Web
) -> None:
    site_id = await _site(conn, fetch_method="browser", fetch_method_checked_at=LONG_AGO)
    await _capture(conn, site_id, PAGE, "ok", days_ago=1)
    http.pages[PAGE] = "shell"

    assert await recheck_fetch_method(conn, http, batch=10) == 1

    assert await _memory(conn, site_id) == ("browser", await _now(conn))
    assert http.fetched == [f"{ORIGIN}/robots.txt", PAGE]


async def test_the_recheck_tries_the_latest_ok_capture(conn: AsyncConnection, http: Web) -> None:
    site_id = await _site(conn, fetch_method="browser")
    await _capture(conn, site_id, f"{ORIGIN}/item/old", "ok", days_ago=5)
    await _capture(conn, site_id, f"{ORIGIN}/item/recent", "ok", days_ago=2)
    await _capture(conn, site_id, f"{ORIGIN}/item/gone", "not_found", days_ago=1)
    http.pages[f"{ORIGIN}/item/recent"] = "ok"

    await recheck_fetch_method(conn, http, batch=10)

    assert http.fetched[-1] == f"{ORIGIN}/item/recent"
    assert (await _memory(conn, site_id))[0] == "http"


async def test_the_recheck_fetches_through_the_sites_proxy_pool(conn: AsyncConnection, http: Web) -> None:
    # ARCHITECTURE §7.1: a site with a pool is fetched through it on every rung, the re-check's included.
    site_id = await _site(conn, fetch_method="browser", proxy_pool="dc")
    await _capture(conn, site_id, PAGE, "ok", days_ago=1)
    http.pages[PAGE] = "ok"

    await recheck_fetch_method(conn, http, batch=10)

    assert http.fetched == [f"{ORIGIN}/robots.txt", PAGE]
    assert http.policies == [FetchPolicy(proxy_pool="dc"), FetchPolicy(proxy_pool="dc")]


async def test_the_recheck_honours_robots(conn: AsyncConnection, http: Web) -> None:
    site_id = await _site(conn, fetch_method="browser")
    await _capture(conn, site_id, PAGE, "ok", days_ago=1)
    http.pages[PAGE], http.robots = "ok", "User-agent: *\nDisallow: /item/\n"

    await recheck_fetch_method(conn, http, batch=10)

    assert http.fetched == [f"{ORIGIN}/robots.txt"]
    assert await _memory(conn, site_id) == ("browser", await _now(conn))


async def test_a_site_without_an_ok_capture_is_marked_checked_without_a_fetch(conn: AsyncConnection, http: Web) -> None:
    site_id = await _site(conn, fetch_method="browser")
    await _capture(conn, site_id, PAGE, "blocked", days_ago=1)

    assert await recheck_fetch_method(conn, http, batch=10) == 1

    assert http.fetched == []
    assert await _memory(conn, site_id) == ("browser", await _now(conn))


async def test_the_recheck_takes_due_browser_sites_only_the_longest_unchecked_first_up_to_its_batch(
    conn: AsyncConnection, http: Web
) -> None:
    never = await _site(conn, "never.example.test", fetch_method="browser")
    oldest = await _site(conn, "oldest.example.test", fetch_method="browser", fetch_method_checked_at=LONG_AGO)
    later = await _site(
        conn, "later.example.test", fetch_method="browser", fetch_method_checked_at=func.now() - timedelta(days=7.5)
    )
    recent = await _site(
        conn, "recent.example.test", fetch_method="browser", fetch_method_checked_at=func.now() - timedelta(days=6)
    )
    on_http = await _site(conn, "http.example.test", fetch_method="http")
    now = await _now(conn)

    assert await recheck_fetch_method(conn, http, batch=2) == 2
    assert [(await _memory(conn, site))[1] == now for site in (never, oldest, later)] == [True, True, False]
    assert await recheck_fetch_method(conn, http, batch=2) == 1

    assert (await _memory(conn, later))[1] == now
    assert (await _memory(conn, recent))[1] != now
    assert await _memory(conn, on_http) == ("http", None)
