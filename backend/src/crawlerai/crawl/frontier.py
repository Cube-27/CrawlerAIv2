"""A crawl's frontier (SPEC-10 §4.5, ARCHITECTURE §13.2): the URLs a fetched page contributes, which of them the crawl
takes, and enqueueing them as the job's tasks.

A page contributes its links (SPEC-07 §4.5) and its next-page candidates (SPEC-05 §4.12), in canonical form
(`crawl.canonical`). The crawl takes those its request's scope admits (`crawl.rules.Scope`), and never one off the start
page's host and its subdomains, whatever an `include` glob matches (D-0037): every page fetched is on the site the
caller named, on the host the site's own redirect of the start URL put it, when that host is on the same site (D-0991).
A URL is enqueued once per job (`url_task` UNIQUE (`job_id`, `canonical_url`)), at its parent's depth plus one, up to
`max_depth`, until the job has `limit` tasks; its page kind is the first matching page-kind rule's. Patterns come from
requests; this module names no host (INV-03)."""

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import Text, any_, bindparam, func, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.content.links import links
from crawlerai.content.page import ParsedPage
from crawlerai.crawl.rules import PageKindRule, Scope, on_site, page_kind_for
from crawlerai.db.models import Job, JobId, UrlTask, UrlTaskId
from crawlerai.normalize.url_key import canonicalize
from crawlerai.resolve.pagination import next_page_candidates


def discovered(page: ParsedPage, final_url: str) -> tuple[str, ...]:
    """The URLs `page`, fetched at `final_url`, contributes: its links, then its next-page candidates, canonical and
    each once, in that order."""
    found = (*links(page, final_url), *next_page_candidates(page, final_url))
    return tuple(dict.fromkeys(filter(None, map(canonicalize, found))))


@dataclass(frozen=True)
class Frontier:
    """Which URLs a crawl takes (`scope` on the start URL's site), the page kind `rules` give them, and how deep and
    how many it goes. `fetched` is a URL the crawl's start page was fetched at after a redirect: its page is the
    start task's, so it is never a task of its own (D-1285)."""

    scope: Scope
    rules: tuple[PageKindRule, ...]
    max_depth: int
    limit: int
    fetched: str | None = None

    def admits(self, url: str) -> bool:
        """Whether the crawl takes `url`, in canonical form."""
        return url != self.fetched and on_site(url, self.scope.host) and self.scope.admits(url)

    def task_row(self, job_id: JobId, url: str, depth: int, parent: UrlTaskId | None) -> dict[str, object]:
        """The `url_task` row of `url`, in canonical form, for the job."""
        page_kind = page_kind_for(url, self.rules)
        return {"job_id": job_id, "url": url, "canonical_url": url, "page_kind": page_kind, "depth": depth} | (
            {} if parent is None else {"parent_task_id": parent}
        )

    async def enqueue(
        self, conn: AsyncConnection, job_id: JobId, urls: Iterable[str], *, depth: int, parent: UrlTaskId | None
    ) -> int:
        """Add the URLs of `urls` the crawl takes and the job has no task for yet, in order, as queued tasks at
        `depth`, until the job has `limit` tasks; none past `max_depth` or once the job's cancel was requested. Returns
        how many were added."""
        taken = list(dict.fromkeys(filter(self.admits, urls)))
        if depth > self.max_depth or not taken:
            return 0
        # The job's row lock makes counting and adding one step: two workers adding a job's URLs at once would each
        # see room for the same `limit`. FOR NO KEY UPDATE, as `settle_job` takes: another task's inserts that refer
        # to the job do not hold it up.
        locked = select(Job.cancel_requested).where(Job.id == job_id).with_for_update(key_share=True)
        if (await conn.execute(locked)).scalar_one():
            return 0
        tasks = select(func.count()).where(UrlTask.job_id == job_id)
        room = self.limit - (await conn.execute(tasks)).scalar_one()
        if room <= 0:
            return 0
        listed = bindparam("listed", taken, type_=ARRAY(Text))
        known = select(UrlTask.canonical_url).where(UrlTask.job_id == job_id, UrlTask.canonical_url == any_(listed))
        existing = set((await conn.execute(known)).scalars())
        new = [url for url in taken if url not in existing][:room]
        if new:
            rows = [self.task_row(job_id, url, depth, parent) for url in new]
            await conn.execute(pg_insert(UrlTask).values(rows).on_conflict_do_nothing())
        return len(new)
