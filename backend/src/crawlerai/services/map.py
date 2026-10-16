"""The map service (SPEC-10 §4.4, ARCHITECTURE §13.1): the URLs of a site, found while the caller waits, from its
sitemaps and the links of the start page. `POST /v1/map` calls it; the MCP `map` tool will (SPEC-10 PR 7).

The start page is fetched over HTTP only, and its links are read only when it was reached (`ok`). Its sitemaps are
read through `crawl.sitemaps`. Every fetch goes through robots.txt and the site's rate (SPEC-02 §4.6), and robots.txt
that cannot be reached allows nothing (RFC 9309 §2.3.1.4). URLs are canonical (`crawl.canonical`) and kept by the
request's scope (`crawl.rules`): the start page's exact host, or the `include` globs, less the `exclude` globs. The
start page's host is where the site's own redirects took it, on the same site (RFC 9110 §15.4; D-0991): a start URL
whose host redirects to its `www.` subdomain, or back, is mapped on that host, under its robots.txt and rate; a
redirect to an unrelated host leaves the start URL's (D-0672).

Sitemap URLs come first, in the order read, then the other links; `sources` counts the returned URLs by source, and a
URL both found counts as a sitemap's. `truncated` says that more URLs were found than `limit`, or that a cap or the
timeout stopped reading: past `TIMEOUT_S`, the URLs found so far are returned.

Nothing found is stored: a `job` of kind `map` records the request and its usage (§4.4). A target the SSRF guard
refuses is never fetched (INV-16): a refused start URL creates no job, and a refused fetch after it fails the job;
both raise `TargetRejected`.
"""

import asyncio
from collections.abc import Iterable
from contextlib import aclosing
from dataclasses import dataclass, field, replace
from typing import Final, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.types import AttemptRecord, FetchPolicy
from crawlerai.content.links import links
from crawlerai.content.page import ParsedPage
from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.crawl.canonical import canonicalize
from crawlerai.crawl.rules import Patterns, Scope, located
from crawlerai.crawl.sitemaps import SitemapReader, roots
from crawlerai.db.jobs import transition_job
from crawlerai.db.models import Job, JobId
from crawlerai.services.fetching import Fetching, PoliteHttp, TargetRejected, check_target, site_rules
from crawlerai.services.scrape_steps import DEFAULT_PROJECT, SiteRow, absolute_http_url, record_fetch_usage, site_row
from crawlerai.storage.capture_bundle import CaptureBundle

TIMEOUT_S: Final = 60.0  # SPEC-10 §4.4
MAX_LIMIT: Final = 5000  # D-0038

Source = Literal["sitemap", "links"]


class MapRequest(BaseModel):
    """The body of `POST /v1/map` (§4.4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str
    include: Patterns = []
    exclude: Patterns = []
    limit: int = Field(default=MAX_LIMIT, ge=1, le=MAX_LIMIT)
    use_sitemaps: bool = True
    use_links: bool = True

    @field_validator("url")
    @classmethod
    def _absolute_http_url(cls, url: str) -> str:
        return absolute_http_url(url)


class MapSources(BaseModel):
    """How many of the returned URLs came from each source; a URL both found counts as a sitemap's."""

    sitemap: int
    links: int


class MapResult(BaseModel):
    urls: list[str]
    sources: MapSources
    truncated: bool


@dataclass
class _Found:
    """The URLs in scope found so far, in order, each under the one source it is credited to: a sitemap URL is never
    also a link. `cut` says that a cap kept some from being read."""

    scope: Scope
    limit: int
    sitemap: dict[str, None] = field(default_factory=dict)
    links: dict[str, None] = field(default_factory=dict)
    cut: bool = False

    def add(self, source: Source, urls: Iterable[str]) -> None:
        for url in filter(self.scope.admits, urls):
            if source == "sitemap":
                self.links.pop(url, None)
                self.sitemap[url] = None
            elif url not in self.sitemap:
                self.links[url] = None

    @property
    def full(self) -> bool:
        """More URLs were found than are returned: reading more changes nothing."""
        return len(self.sitemap) + len(self.links) > self.limit

    def result(self) -> MapResult:
        # Sitemap URLs come first, so the returned sitemap URLs are the first of them.
        urls = [*self.sitemap, *self.links][: self.limit]
        from_sitemaps = min(len(self.sitemap), len(urls))
        sources = MapSources(sitemap=from_sitemaps, links=len(urls) - from_sitemaps)
        return MapResult(urls=urls, sources=sources, truncated=self.cut or self.full)


async def map_urls(
    engine: AsyncEngine, fetching: Fetching, request: MapRequest, *, timeout_s: float = TIMEOUT_S
) -> MapResult:
    """Run `request` as a map job. Raises `TargetRejected` for a target the SSRF guard refused: before any job for
    the start URL, failing the job for a fetch after it."""
    await check_target(fetching.connector, request.url)
    start = canonicalize(request.url) or request.url  # the request's validator refuses a URL without a canonical form
    host = urlsplit(start).hostname or ""
    found = _Found(Scope(host, tuple(request.include), tuple(request.exclude)), request.limit)
    job_id, site = await _start(engine, request, host)
    attempts: list[AttemptRecord] = []
    try:
        async with asyncio.timeout(timeout_s):
            await _discover(engine, fetching, request, start, site, found, attempts)
    except TimeoutError:
        found.cut = True
    except TargetRejected:
        await _finish(engine, job_id, "failed", attempts, site.proxy_pool)
        raise
    await _finish(engine, job_id, "completed", attempts, site.proxy_pool)
    return found.result()


async def _start(engine: AsyncEngine, request: MapRequest, host: str) -> tuple[JobId, SiteRow]:
    async with engine.begin() as conn:
        job_id = (
            await conn.execute(
                pg_insert(Job)
                .values(
                    project_id=DEFAULT_PROJECT,
                    kind="map",
                    request=request.model_dump(mode="json"),
                    status="running",
                    started_at=func.now(),
                    engine_version=ENGINE_VERSION,
                )
                .returning(Job.id)
            )
        ).scalar_one()
        return job_id, await site_row(conn, host)


async def _discover(
    engine: AsyncEngine,
    fetching: Fetching,
    request: MapRequest,
    start: str,
    site: SiteRow,
    found: _Found,
    attempts: list[AttemptRecord],
) -> None:
    """Add to `found` the links of the start page, then the URLs of the sitemaps: the one fetch of the start page comes
    before the sitemaps, which can take the rest of the timeout. The start page is fetched even when its links are not
    taken, for where it is: when the site redirects it to another host of the site (`crawl.rules.located`), the scope,
    robots.txt and the sitemaps are that host's."""
    polite = await _polite(engine, fetching, site, found.scope.host, request.url, attempts)
    if polite is None:
        return
    page = await polite.fetch(request.url, polite.policy)
    site_url = located(start, None if page is None else (page.bundle.manifest.method, page.bundle.manifest.final_url))
    host = urlsplit(site_url).hostname or ""
    if host != found.scope.host:
        found.scope = replace(found.scope, host=host)
        async with engine.begin() as conn:
            site = await site_row(conn, host)
        polite = await _polite(engine, fetching, site, host, site_url, attempts)
    if request.use_links and page is not None and page.block_class == "ok":
        # Parsing and canonicalizing are CPU work: one thread keeps the event loop free.
        found.add("links", await asyncio.to_thread(_page_links, page.bundle))
    if polite is not None and request.use_sitemaps and not found.full:
        await _read_sitemaps(polite, site_url, found)


async def _polite(
    engine: AsyncEngine, fetching: Fetching, site: SiteRow, host: str, url: str, attempts: list[AttemptRecord]
) -> PoliteHttp | None:
    """Fetches from `site`, on `host`, under the robots.txt of `url` there; `None` when that robots.txt is
    unreachable."""
    policy = FetchPolicy(method_hint="http", proxy_pool=site.proxy_pool)
    robots = await site_rules(engine, fetching.rungs.http, site, url, policy, attempts)
    if robots is None:
        return None
    return PoliteHttp(fetching, host, site.crawl_delay_ms, robots, policy, attempts)


async def _read_sitemaps(polite: PoliteHttp, site_url: str, found: _Found) -> None:
    """Add to `found` the URLs of the sitemaps of the start page's host, `site_url` there, until it is full."""
    listed = () if polite.robots is None else polite.robots.sitemaps
    reader = SitemapReader(polite.sitemap_body, found.scope.host)
    async with aclosing(reader.urls(roots(site_url, listed))) as urls:
        async for url in urls:
            found.add("sitemap", (url,))
            if found.full:
                break
    found.cut = found.cut or reader.cut


def _page_links(bundle: CaptureBundle) -> tuple[str, ...]:
    found = links(ParsedPage.of(bundle), bundle.manifest.final_url)
    return tuple(filter(None, map(canonicalize, found)))


async def _finish(
    engine: AsyncEngine,
    job_id: JobId,
    status: Literal["completed", "failed"],
    attempts: list[AttemptRecord],
    proxy_pool: str | None,
) -> None:
    async with engine.begin() as conn:
        await record_fetch_usage(conn, job_id, attempts, proxy_pool)
        await transition_job(conn, job_id, status)
