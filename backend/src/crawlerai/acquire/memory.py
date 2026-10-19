"""Domain memory (acquisition spec, "Acquisition contract and block history"): two tiers, kept apart, because a
durable strategy and a short-lived safety bias age differently.

- The acquisition contract (`site_contract`), durable, per site and page kind (`remembered_as`): the rung the pages
  start with, the browser engine that taught it, the learned wait condition (`FetchPolicy.settle_on`), what the browser
  was needed for (render, the page's data calls, browser steps), whether it was needed only to pass a block (`handoff`:
  the pages stay on HTTP with the cookies that browser `ok` held, `acquire.session`), and the field coverage of the
  last extraction with a record. It is learned from a fetch that tried HTTP in `auto` (`learn_fetch`), and goes stale
  after `STALE_FAILURES` consecutive extractions without a record (`learn_extraction`); a block is never one. A stale
  contract is kept but not used; an extraction with a record makes it fresh again. The 7-day re-check
  (`scheduler.recheck`) still sets a `browser` contract back to `http` when HTTP passes.
- The block history (`site_block`), short-lived, per site: each HTTP request the site refused (`refused`) counts, the
  count starting over when the last one is older than `BLOCK_TTL`; at `BROWSER_FIRST_BLOCKS` the site's pages start in
  the browser for one `BLOCK_TTL`. An HTTP `ok` kept for the site clears it.

Precedence (`remembered`): a job's own setting (`FetchPolicy.method_hint` other than `auto`) beats memory, which the
caller applies; the block history's browser-first beats the contract's method; a fresh contract beats the defaults
(HTTP, the browser's default settle). Both tiers are rows, so every process reads the same memory.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from sqlalchemy import case, delete, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.politeness import SLOW_DOWN
from crawlerai.acquire.session import ENGINE
from crawlerai.acquire.types import AttemptRecord, FetchResult, fetched_as
from crawlerai.db.models import BrowserEngine, FetchMethod, PageKind, SettleOn, SiteBlock, SiteContract, SiteId

__all__ = [
    "BLOCK_TTL",
    "BROWSER_FIRST_BLOCKS",
    "STALE_FAILURES",
    "Coverage",
    "Lesson",
    "Remembered",
    "learn_extraction",
    "learn_fetch",
    "lesson",
    "refused",
    "remembered",
    "remembered_as",
]

# Owner plan 2026-10-19 P4 (domain memory): unmeasured starting points.
BLOCK_TTL: Final = timedelta(minutes=15)
BROWSER_FIRST_BLOCKS: Final = 2
STALE_FAILURES: Final = 2

# The last extraction with a record: the schema's field names it published (`found`) and those it did not (`missing`).
Coverage = dict[str, list[str]]


@dataclass(frozen=True)
class Remembered:
    """What memory says a fetch of a site's page of one kind starts with: the defaults without memory."""

    method: FetchMethod = "http"
    settle_on: SettleOn | None = None


@dataclass(frozen=True)
class Lesson:
    """What one fetch teaches the contract (`lesson`)."""

    method: FetchMethod
    engine: BrowserEngine | None = None
    settle_on: SettleOn | None = None
    needs_render: bool = False
    needs_xhr: bool = False
    needs_traversal: bool = False
    handoff: bool = False


def remembered_as(kind: PageKind | None) -> PageKind:
    """The page kind whose memory a fetch of `kind` reads and writes. A fetch with no page kind is classified as a
    detail page is (`classify` applies the listing rule to listings only), so it shares the detail pages' memory."""
    return kind or "detail"


async def remembered(
    conn: AsyncConnection, site_id: SiteId, kind: PageKind | None, *, blocks: bool = True
) -> Remembered:
    """The memory of the site's pages of `kind` (module docstring, precedence): browser-first while the block history
    says so, else the fresh contract's method and wait condition, else the defaults. Without `blocks`, the durable
    contract alone, for what outlives the block history (a learned config's `Target.fetch`)."""
    fresh = (
        SiteContract.site_id == site_id,
        SiteContract.page_kind == remembered_as(kind),
        SiteContract.failures < STALE_FAILURES,
    )
    browser_first = exists().where(SiteBlock.site_id == site_id, SiteBlock.browser_first_until > func.now())
    query = select(
        select(SiteContract.method).where(*fresh).scalar_subquery(),
        select(SiteContract.settle_on).where(*fresh).scalar_subquery(),
        browser_first,
    )
    method, settle_on, first = (await conn.execute(query)).one()
    if first and blocks:
        return Remembered("browser", settle_on)
    return Remembered(method or "http", settle_on)


def refused(attempt: AttemptRecord) -> bool:
    """Whether an HTTP request was refused by the site (`classify`): `blocked` other than a 429 or 503, which ask for
    fewer requests and are the politeness step's (RFC 6585 §4, RFC 9110 §15.6.4), or a `shell` a challenge names
    (`acquire.challenge`). A block needs this corroboration; an error or a shell alone is not one."""
    if attempt.method != "http":
        return False
    if attempt.block_class == "blocked":
        return attempt.status not in SLOW_DOWN
    return attempt.block_class == "shell" and attempt.challenge is not None


def lesson(result: FetchResult, lacks: bool | None) -> Lesson | None:
    """What an `auto` fetch that tried HTTP and kept an `ok` teaches; None for any other fetch (a job's own method, a
    page that started in the browser or was served by an API: nothing new about HTTP). An HTTP `ok` teaches the
    defaults. A browser `ok` teaches the browser and what it was needed for: rendering, when HTTP was `ok` but lacked
    what the caller reads or was a shell no challenge named; the page's data calls, when its rendered document still
    `lacks` what the caller reads and the render captured network JSON; browser steps. Its wait condition is the
    content alone when the rendered document has what the caller reads, the data calls too when they carried it, the
    default settle when `lacks` is unknown (None). When HTTP was `refused` and the render needed nothing else, and its
    cookies went on to HTTP (an attempt's `site_session`), it was needed only to pass the block: `handoff`, and the
    pages stay on HTTP."""
    http = [attempt for attempt in result.attempts if attempt.method == "http"]
    if result.bundle.manifest.fetch_policy.get("method_hint") != "auto" or result.block_class != "ok" or not http:
        return None
    if result.method == "http":
        return Lesson("http")
    return _rendered(result, http[-1], lacks) if result.method == "browser" else None


def _rendered(result: FetchResult, http: AttemptRecord, lacks: bool | None) -> Lesson:
    """What a browser `ok` kept over the HTTP attempt `http` teaches (`lesson`)."""
    passed_block = refused(http)
    needs_xhr = lacks is True and bool(result.bundle.network)
    needs_traversal = any(attempt.steps for attempt in result.attempts if attempt.method == "browser")
    settle_on: SettleOn | None = None
    if lacks is not None:
        settle_on = "data_call" if needs_xhr else None if lacks else "content"
    carried = any(attempt.site_session for attempt in result.attempts)
    handoff = passed_block and carried and not (needs_xhr or needs_traversal)
    return Lesson(
        method="http" if handoff else "browser",
        engine=ENGINE,
        settle_on=settle_on,
        needs_render=not passed_block and http.block_class in ("ok", "shell"),
        needs_xhr=needs_xhr,
        needs_traversal=needs_traversal,
        handoff=handoff,
    )


async def learn_fetch(conn: AsyncConnection, site_id: SiteId, result: FetchResult, lacks: bool | None) -> None:
    """Remember what the fetch `result` of a site's page taught: its block or HTTP success in the block history, and
    its `lesson` in the contract of the kind it was fetched as. A plain HTTP `ok` leaves a contract on HTTP as it is (a
    handoff's HTTP `ok` is the handoff working); a contract the lesson would not change is not rewritten."""
    await _record_block(conn, site_id, result)
    learned = lesson(result, lacks)
    if learned is None:
        return
    values = {
        "method": learned.method,
        "engine": learned.engine,
        "settle_on": learned.settle_on,
        "needs_render": learned.needs_render,
        "needs_xhr": learned.needs_xhr,
        "needs_traversal": learned.needs_traversal,
        "handoff": learned.handoff,
    }
    kind = remembered_as(fetched_as(result.bundle.manifest.fetch_policy))
    insert = pg_insert(SiteContract).values(site_id=site_id, page_kind=kind, checked_at=func.now(), **values)
    changed = (
        SiteContract.method != "http"
        if learned == Lesson("http")
        else or_(*(getattr(SiteContract, name).is_distinct_from(value) for name, value in values.items()))
    )
    await conn.execute(
        insert.on_conflict_do_update(
            index_elements=[SiteContract.site_id, SiteContract.page_kind],
            set_={**values, "checked_at": func.now()},
            where=changed,
        )
    )


async def _record_block(conn: AsyncConnection, site_id: SiteId, result: FetchResult) -> None:
    """Count the fetch's last `refused` HTTP request in the site's block history, or clear the history when the fetch
    kept an HTTP `ok`."""
    block = next((attempt for attempt in reversed(result.attempts) if refused(attempt)), None)
    if block is None:
        if result.block_class == "ok" and result.method == "http":
            await conn.execute(delete(SiteBlock).where(SiteBlock.site_id == site_id))
        return
    blocks = case((SiteBlock.last_block_at > func.now() - BLOCK_TTL, SiteBlock.blocks + 1), else_=1)
    first_until = case((blocks >= BROWSER_FIRST_BLOCKS, func.now() + BLOCK_TTL), else_=SiteBlock.browser_first_until)
    insert = pg_insert(SiteBlock).values(
        site_id=site_id, blocks=1, last_block_at=func.now(), vendor=block.challenge, browser_first_until=None
    )
    await conn.execute(
        insert.on_conflict_do_update(
            index_elements=[SiteBlock.site_id],
            set_={
                "blocks": blocks,
                "last_block_at": func.now(),
                "vendor": insert.excluded.vendor,
                "browser_first_until": first_until,
            },
        )
    )


async def learn_extraction(conn: AsyncConnection, site_id: SiteId, kind: PageKind, coverage: Coverage | None) -> None:
    """Remember how an extraction of a reached page of the site's `kind` went: with a record, its `coverage`, which
    makes the contract fresh (a row with the defaults when there is none); without one (None), one more consecutive
    failure towards `STALE_FAILURES`. An unchanged contract is not rewritten."""
    key = (SiteContract.site_id == site_id, SiteContract.page_kind == kind)
    if coverage is None:
        await conn.execute(update(SiteContract).where(*key).values(failures=SiteContract.failures + 1))
        return
    insert = pg_insert(SiteContract).values(
        site_id=site_id, page_kind=kind, method="http", checked_at=func.now(), coverage=coverage
    )
    await conn.execute(
        insert.on_conflict_do_update(
            index_elements=[SiteContract.site_id, SiteContract.page_kind],
            set_={"coverage": insert.excluded.coverage, "failures": 0},
            where=or_(SiteContract.failures != 0, SiteContract.coverage.is_distinct_from(insert.excluded.coverage)),
        )
    )
