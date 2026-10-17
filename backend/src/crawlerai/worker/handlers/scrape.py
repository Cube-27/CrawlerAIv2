"""The handler of `batch_scrape` and `extract` tasks (SPEC-10 §4.3, §4.6): a scrape's steps
(`crawlerai.services.scrape_steps`), run by a worker instead of while a caller waits. An `extract` job is a records job
whose URLs are all caller-supplied, as a batch's are (ARCHITECTURE §10), so its tasks run as a records batch's do.

The page is fetched politely (`crawlerai.worker.polite`): robots.txt over HTTP, the site's rate, backoff through the
queue. Its capture is stored, and for `records` it is extracted with what the job pinned when it was submitted
(INV-28): the schema document, the precedence orders and calibration, and the site's active config then, if it had one
(`config` mode; the page joins the config's drift window, as a scrape's does). Its record is stored. Page outputs are
not stored: `/v1/jobs/{id}/results` makes them from the capture.

A records task is how a recurring run sees a page again (SPEC-11 §4.2, §4.3). When records already stand for the page
(`standing_record`, or `standing_listing` for a listing, in `crawlerai.recurring.state`), the page is fetched with the
validators it last answered with, and a 304 ends the task `unchanged` with no capture (`steps.fetch_page`). A page
fetched whole whose visible words are the same as last time (an equal content digest, D-1340), or a listing without
words whose links are (D-1383), ends `unchanged` with its capture, and is not extracted. Having no extraction, an unchanged page joins no drift window (SPEC-08 §4.9) and does
not count toward `pages_extracted` (ARCHITECTURE §8.3 counts `extracted` and `partial` pages). Only records tasks read
or write `url_state`: a fingerprint or validators stored without the record made from that content would let a stale
record stand.

Everything is written in the worker's transaction for the task, so a task that raises rolls back alone and fails no
other (INV-31). A page that was not reached ends with its outcome (`blocked`, `shell`, `not_found`); a fetch error is a
transient failure, retried by the queue and `failed` once attempts run out; a redirect the SSRF guard refused fails
the task at once (INV-16).
"""

import asyncio
import logging

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.config_ir.drift import DriftMargins
from crawlerai.content.links import links
from crawlerai.content.page import ParsedPage
from crawlerai.db.models import PageKind, SiteId
from crawlerai.db.queue import ClaimedTask
from crawlerai.llm.client import LLMClient
from crawlerai.recurring.simhash import ContentFingerprint, content_fingerprint
from crawlerai.recurring.state import record_content, record_fetch, stand_for_listing
from crawlerai.recurring.versions import link_records
from crawlerai.resolve.pipeline import EngineData
from crawlerai.services.fetching import Fetching
from crawlerai.services.scrape_steps import FetchOptions
from crawlerai.worker.handlers.steps import (
    Ended,
    FetchedPage,
    Records,
    count_fetch,
    extract_records,
    fetch_page,
    load_job,
    unreached,
)
from crawlerai.worker.loop import Failed, Finished, TaskHandler, TaskResult

log = logging.getLogger(__name__)


class _PageFetch(BaseModel):
    """How the job's request asks its pages to be fetched: the members a batch and an extract request share."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    fetch: FetchOptions
    locale: str | None


def scrape_handler(
    fetching: Fetching, data: EngineData | None, margins: DriftMargins | None, *, llm: LLMClient | None
) -> TaskHandler:
    """The `batch_scrape` and `extract` handler of a worker that fetches with `fetching`; `data` is None in a worker
    without the engine's data files, whose records tasks then fail. `margins` decide drift suspensions (SPEC-08 §4.9);
    role C runs on `llm` (None: no role C)."""

    async def handle(task: ClaimedTask, conn: AsyncConnection) -> TaskResult:
        job = await load_job(conn, task, data, margins)
        if isinstance(job, Failed):
            return job
        request, records = _PageFetch.model_validate(job[0]), job[1]
        # A records job asks for nothing else of its pages (`BatchScrapeRequest`, `ExtractRequest`).
        page = await fetch_page(
            conn, fetching, task, request.fetch, request.locale, recurring=records, served=records, llm=llm
        )
        result = page.task_result if isinstance(page, Ended) else await _settle(conn, task, page, records, llm)
        await count_fetch(conn, task, page)
        return result

    return handle


async def _settle(
    conn: AsyncConnection, task: ClaimedTask, page: FetchedPage, records: Records | None, llm: LLMClient | None
) -> TaskResult:
    """The fetched page's result: its outcome when it was not reached or the job has no records, else its record's."""
    ended = unreached(page)
    if ended is not None:
        return ended
    if records is None:
        return Finished("extracted", capture_id=page.capture_id)
    parsed = page.parsed
    final_url = page.result.bundle.manifest.final_url
    kind = records.schema.page_kind
    changed = await _content_changed(conn, page.site.id, task.canonical_url, parsed, final_url, kind)
    if not changed and page.standing:
        await record_fetch(conn, page.site.id, task.canonical_url, page.result)
        await link_records(conn, task.id, page.standing)
        return Finished("unchanged", capture_id=page.capture_id)
    result = await extract_records(conn, task, page, records, caller_supplied=True, llm=llm, parsed=parsed)
    if isinstance(result, Finished):
        # The validators are stored with the record made from the content they describe, never without it.
        await record_fetch(conn, page.site.id, task.canonical_url, page.result)
        if records.schema.page_kind == "listing":
            await stand_for_listing(conn, page.site.id, task.canonical_url, task.id)
    return result


async def _content_changed(
    conn: AsyncConnection, site_id: SiteId, canonical_url: str, parsed: ParsedPage, final_url: str, kind: PageKind
) -> bool:
    """Whether the page's content changed since it was last fingerprinted (`record_content`). A page without a
    fingerprint (`page_fingerprint`), or one whose fingerprint fails, counts as changed and is extracted: an error
    never skips extraction (§4.6)."""
    try:
        # Rendering the text is CPU work, as resolution is: a thread keeps the event loop serving other tasks.
        fingerprint = await asyncio.to_thread(page_fingerprint, parsed, final_url, kind)
    except Exception:
        log.exception("the content fingerprint failed; the page is extracted")
        return True
    return fingerprint is None or await record_content(conn, site_id, canonical_url, fingerprint)


def page_fingerprint(parsed: ParsedPage, final_url: str, kind: PageKind) -> ContentFingerprint | None:
    """The fingerprint of the page's visible words; for a listing without words (rows of images, text drawn by script),
    of the URLs it links to, in document order (`content.links`): its rows' links are what such a listing shows of them
    (D-1383). None for a detail page without words, or a listing with neither words nor links."""
    fingerprint = content_fingerprint(parsed.cleaned_text.text)
    if fingerprint is not None or kind != "listing":
        return fingerprint
    # A canonical URL holds no whitespace (WHATWG URL Standard percent-encodes it), so each link is one word.
    return content_fingerprint(" ".join(links(parsed, final_url)))
