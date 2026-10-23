"""A crawl's frontier: the URLs a fetched page contributes, which of them the crawl
takes, and enqueueing them as the job's tasks.

A page contributes its links and its next-page candidates, in canonical form
(`crawl.canonical`). The crawl takes those its request's scope admits (`crawl.rules.Scope`), and never one off the start
page's host and its subdomains, whatever an `include` glob matches: every page fetched is on the site the
caller named, on the host the site's own redirect of the start URL put it, when that host is on the same site.
A URL is enqueued once per job (`url_task` UNIQUE (`job_id`, `canonical_url`)), and never when a task of the job was
already fetched at it after a redirect (`url_task.final_url`), at its parent's depth plus one, up to
`max_depth`, until the job has `limit` tasks; its page kind is the first matching page-kind rule's. Patterns come from
requests; this module names no host."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Final

from sqlalchemy import Text, and_, any_, bindparam, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.content.links import anchor_texts, links
from crawlerai.content.page import ParsedPage
from crawlerai.crawl.rules import PageKindRule, Scope, on_site, page_kind_for
from crawlerai.crawl.scoring import Strategy, best_first_scores, depth_score, page_relevance
from crawlerai.db.jobs import lock_job
from crawlerai.db.models import Job, JobId, UrlTask, UrlTaskId
from crawlerai.db.queue import ClaimedTask
from crawlerai.normalize.url_key import canonicalize
from crawlerai.resolve.pagination import next_page_candidates

# A scored crawl queues up to this many candidates per page it may fetch, so that a link found late can still outrank
# one found early; the candidates the budget does not reach are cancelled unfetched (`Frontier.close_if_spent`).
CANDIDATE_FACTOR: Final = 5


def discovered(page: ParsedPage, final_url: str) -> tuple[str, ...]:
    """The URLs `page`, fetched at `final_url`, contributes: its links, then its next-page candidates, canonical and
    each once, in that order."""
    found = (*links(page, final_url), *next_page_candidates(page, final_url))
    return tuple(dict.fromkeys(filter(None, map(canonicalize, found))))


@dataclass(frozen=True)
class Links:
    """What a page contributes: its `urls` (`discovered`) and, for a best-first crawl, their link texts and the page's
    own relevance to the query, which they inherit."""

    urls: tuple[str, ...] = ()
    texts: Mapping[str, str] = field(default_factory=dict)
    relevance: float = 0.0


def read_links(page: ParsedPage, final_url: str, wanted: tuple[str, ...] | None) -> Links:
    """The links `page`, fetched at `final_url`, contributes; with `wanted` (a best-first crawl's query terms) also what
    scores them."""
    urls = discovered(page, final_url)
    if wanted is None:
        return Links(urls)
    anchor_text = {url: text for raw, text in anchor_texts(page, final_url).items() if (url := canonicalize(raw))}
    return Links(urls, anchor_text, page_relevance(page.cleaned_text.text, wanted))


@dataclass(frozen=True)
class Frontier:
    """Which URLs a crawl takes (`scope` on the start URL's site), the page kind `rules` give them, and how deep and
    how many it goes."""

    scope: Scope
    rules: tuple[PageKindRule, ...]
    max_depth: int
    limit: int
    strategy: Strategy = "bfs"
    wanted: tuple[str, ...] = ()  # the query terms of a best-first crawl (`scoring.query_terms`)
    home: str = ""  # the start URL's directory: the section a best-first crawl prefers (`scoring`)

    @property
    def capacity(self) -> int:
        """How many tasks the job holds: `limit`, or for a scored crawl `CANDIDATE_FACTOR` times as many candidates."""
        return self.limit * (1 if self.strategy == "bfs" else CANDIDATE_FACTOR)

    def admits(self, url: str) -> bool:
        """Whether the crawl's scope takes `url`, in canonical form."""
        return (self.scope.external or on_site(url, self.scope.host)) and self.scope.admits(url)

    def task_row(
        self, job_id: JobId, url: str, depth: int, parent: UrlTaskId | None, score: float | None = None
    ) -> dict[str, object]:
        """The `url_task` row of `url`, in canonical form, for the job; `score` orders its lease."""
        page_kind = page_kind_for(url, self.rules)
        return (
            {"job_id": job_id, "url": url, "canonical_url": url, "page_kind": page_kind, "depth": depth}
            | ({} if parent is None else {"parent_task_id": parent})
            | ({} if score is None else {"score": score})
        )

    def scores(
        self,
        urls: list[str],
        depth: int,
        anchor_text: Mapping[str, str],
        priorities: Mapping[str, float],
        inherited: float,
    ) -> dict[str, float]:
        """The lease score of each of `urls` at `depth`, by the crawl's strategy; none for breadth first."""
        match self.strategy:
            case "bfs":
                return {}
            case "dfs":
                return dict.fromkeys(urls, depth_score(depth))
            case "best_first":
                return best_first_scores(
                    urls,
                    depth=depth,
                    wanted=self.wanted,
                    anchors=anchor_text,
                    priorities=priorities,
                    inherited=inherited,
                    home=self.home,
                )

    async def enqueue(
        self,
        conn: AsyncConnection,
        job_id: JobId,
        urls: Iterable[str],
        *,
        depth: int,
        parent: UrlTaskId | None,
        anchor_text: Mapping[str, str] | None = None,
        priorities: Mapping[str, float] | None = None,
        inherited: float = 0.0,
    ) -> int:
        """Add the URLs of `urls` the crawl takes and the job has no task for yet, in order, as queued tasks at
        `depth`, scored by the strategy from the links' `anchor_text`, the sitemaps' `priorities` and the `inherited`
        relevance of the page that holds them, until the job has `capacity` tasks (a scored crawl then replaces its
        weakest queued tasks by better candidates); none past `max_depth` or once the job's cancel was requested. A URL
        a task was fetched at after a redirect is that task's page, never a task of its own. Returns how many
        were added."""
        taken = list(dict.fromkeys(filter(self.admits, urls)))
        if depth > self.max_depth or not taken:
            return 0
        # The job's row lock makes counting and adding one step: two workers adding a job's URLs at once would each
        # see room for the same `limit`.
        if (await lock_job(conn, job_id, Job.cancel_requested)).cancel_requested:
            return 0
        tasks = select(func.count()).where(UrlTask.job_id == job_id)
        room = self.capacity - (await conn.execute(tasks)).scalar_one()
        if room <= 0 and self.strategy == "bfs":
            return 0
        listed = bindparam("listed", taken, type_=ARRAY(Text))
        by_url = select(UrlTask.canonical_url).where(UrlTask.job_id == job_id, UrlTask.canonical_url == any_(listed))
        by_final_url = select(UrlTask.final_url).where(UrlTask.job_id == job_id, UrlTask.final_url == any_(listed))
        existing: set[str | None] = set((await conn.execute(by_url.union(by_final_url))).scalars())
        new = [url for url in taken if url not in existing]
        scores = self.scores(new, depth, anchor_text or {}, priorities or {}, inherited)
        chosen = (
            new[: max(room, 0)] if self.strategy == "bfs" else await self._make_room(conn, job_id, new, scores, room)
        )
        if chosen:
            rows = [self.task_row(job_id, url, depth, parent, scores.get(url)) for url in chosen]
            await conn.execute(pg_insert(UrlTask).values(rows).on_conflict_do_nothing())
        return len(chosen)

    async def _make_room(
        self, conn: AsyncConnection, job_id: JobId, new: list[str], scores: Mapping[str, float], room: int
    ) -> list[str]:
        """Which of `new` a scored crawl adds: the best `room` of them, and past that each one that outscores a queued
        task, which it replaces (the task is deleted), the weakest first. The best candidates are kept, however late
        they are found. A task being claimed is not replaced."""
        ranked = sorted(new, key=lambda url: -scores[url])
        kept = ranked[: max(room, 0)]
        rest = ranked[len(kept) :]
        if not rest:
            return kept
        queued = (UrlTask.job_id == job_id, UrlTask.status == "queued", UrlTask.score.is_not(None))
        # The rows are locked as `claim_tasks` locks them (FOR UPDATE SKIP LOCKED): one a worker is claiming is skipped,
        # and one locked here cannot be claimed before it is deleted, so no worker's lease is deleted under it.
        weakest = (
            select(UrlTask.id, UrlTask.score)
            .where(*queued)
            .order_by(UrlTask.score, UrlTask.id.desc())
            .with_for_update(skip_locked=True)
        )
        evicted: list[UrlTaskId] = []
        for url, row in zip(rest, (await conn.execute(weakest.limit(len(rest)))).all(), strict=False):
            if scores[url] <= row.score:
                break
            evicted.append(row.id)
            kept.append(url)
        if evicted:
            await conn.execute(delete(UrlTask).where(UrlTask.id.in_(evicted)))
        return kept

    async def spent_before(self, conn: AsyncConnection, task: ClaimedTask) -> int:
        """How many of a scored crawl's pages are spent before `task`: the tasks finished, and those leased that rank
        ahead of it (the order of the lease: score, then id). A worker runs the tasks it leased together one after the
        other, best first, so those behind `task` have not started. A plain count, with no lock: it runs before the
        page is fetched, and a lock would be held until the task commits."""
        if task.score is None:
            ahead = or_(UrlTask.score.is_not(None), UrlTask.id < task.id)
        else:
            ahead = or_(UrlTask.score > task.score, and_(UrlTask.score == task.score, UrlTask.id < task.id))
        leased = and_(UrlTask.status == "claimed", ahead)
        spent = select(func.count()).where(
            UrlTask.job_id == task.job_id, UrlTask.id != task.id, or_(UrlTask.status.in_(("done", "failed")), leased)
        )
        return (await conn.execute(spent)).scalar_one()

    async def over_limit(self, conn: AsyncConnection, task: ClaimedTask) -> bool:
        """Whether a scored crawl's `limit` pages are spent before `task` starts."""
        return await self.spent_before(conn, task) >= self.limit

    async def outranked(self, conn: AsyncConnection, task: ClaimedTask) -> bool:
        """Whether a queued task of the job scores above `task`: a page read since `task` was leased found a better
        candidate, so `task` goes back to the queue and the better one is fetched first."""
        if task.score is None:
            return False
        better = select(UrlTask.id).where(
            UrlTask.job_id == task.job_id,
            UrlTask.status == "queued",
            UrlTask.next_attempt_at <= func.now(),  # one a claim would skip (backoff, host delay) outranks nothing
            UrlTask.score > task.score,
        )
        return (await conn.execute(select(better.exists()))).scalar_one()

    async def close_if_spent(self, conn: AsyncConnection, task: ClaimedTask) -> None:
        """Once `task` has spent the last of a scored crawl's `limit` pages, cancel its queued candidates: the best were
        leased first."""
        if self.strategy == "bfs":
            return
        # The job's row lock makes the count and the cancel one step, as in `enqueue`.
        await lock_job(conn, task.job_id)
        if await self.spent_before(conn, task) + 1 >= self.limit:
            queued = (UrlTask.job_id == task.job_id, UrlTask.status == "queued")
            await conn.execute(update(UrlTask).where(*queued).values(status="cancelled"))
