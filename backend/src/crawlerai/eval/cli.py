"""`crawlerai eval capture` and `crawlerai eval import-sites`: fetch pages over HTTP and store each as an eval capture
and an unlabeled page of the golden set.

Fetches are polite as the worker's are (acquisition spec, politeness): robots.txt is read once per origin and obeyed,
and requests to one host are spaced by the default interval or the robots `Crawl-delay`, whichever is longer. The CLI
waits out that interval; it runs one page at a time. Outcomes are reported by their position in the input.
"""

import asyncio
import json
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import aclosing
from dataclasses import dataclass
from functools import partial
from typing import get_args
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from crawlerai.acquire.http import fetch_http
from crawlerai.acquire.impersonate import rung_impersonation
from crawlerai.acquire.politeness import HostLimiter, interval
from crawlerai.acquire.robots import Fetch, Robots, robots_url, snapshot_of
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.core.capture import BlockClass
from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.core.settings import Settings
from crawlerai.db.models import CaptureId, EvalCategory, EvalPageId, PageKind, SchemaId
from crawlerai.db.models import SchemaDef as SchemaRow
from crawlerai.eval.store import EvalPageRow, EvalStore, dev_store
from crawlerai.schemas.registry import list_schemas
from crawlerai.schemas.types import SchemaDef as Schema

_CATEGORIES: dict[str, EvalCategory] = {category: category for category in get_args(EvalCategory)}
_SCHEMES = frozenset({"http", "https"})  # RFC 9110 §4.2: the URI schemes a page is fetched over


class EvalCliError(Exception):
    """The input is unusable; nothing was fetched or stored."""


@dataclass(frozen=True)
class PageRequest:
    n: int  # the page's position in the input: its argument number, or its line in a site list
    url: str
    schema_name: str
    category: EvalCategory


@dataclass(frozen=True)
class SchemaRef:
    id: SchemaId
    name: str
    page_kind: PageKind


@dataclass(frozen=True)
class Captured:
    n: int
    capture_id: CaptureId
    page_id: EvalPageId
    status_code: int
    block_class: BlockClass
    error: str | None


@dataclass(frozen=True)
class Skipped:
    """Not fetched: robots.txt disallows the page or is unreachable (RFC 9309 §2.3.1.4: then nothing is allowed), or
    the site list already has `--pages-per-site` pages of its host."""

    n: int
    reason: str


Outcome = Captured | Skipped


@dataclass(frozen=True)
class SiteList:
    requests: tuple[PageRequest, ...]
    over_limit: tuple[Skipped, ...]


def parse_site_list(text: str, pages_per_site: int) -> SiteList:
    """A site list: one page per line, `<category> <schema> <url>`; blank lines and lines starting with `#` are
    ignored. A host's pages after its first `pages_per_site` are skipped. Every error is reported by line number,
    without the line, and any error rejects the whole list."""
    requests: list[PageRequest] = []
    over_limit: list[Skipped] = []
    errors: list[str] = []
    seen: set[str] = set()
    per_host: Counter[str] = Counter()
    for n, line in enumerate(text.splitlines(), start=1):
        columns = line.split()
        if not columns or columns[0].startswith("#"):
            continue
        if len(columns) != 3:
            errors.append(f"line {n}: expected `<category> <schema> <url>`")
            continue
        category, schema_name, url = _CATEGORIES.get(columns[0]), columns[1], columns[2]
        if category is None:
            errors.append(f"line {n}: the category is not one of {', '.join(sorted(_CATEGORIES))}")
            continue
        host = http_host(url)
        if host is None:
            errors.append(f"line {n}: not an http or https URL with a host")
            continue
        if url in seen:
            errors.append(f"line {n}: the URL is listed twice")
            continue
        seen.add(url)
        per_host[host] += 1
        if per_host[host] > pages_per_site:
            over_limit.append(Skipped(n, "pages_per_site"))
            continue
        requests.append(PageRequest(n, url, schema_name, category))
    if errors:
        raise EvalCliError("the site list is invalid:\n" + "\n".join(errors))
    return SiteList(tuple(requests), tuple(over_limit))


def check_urls(urls: Sequence[str]) -> None:
    bad = [str(n) for n, url in enumerate(urls, start=1) if http_host(url) is None]
    if bad:
        raise EvalCliError(f"not an http or https URL with a host: URL {', '.join(bad)}")


def http_host(url: str) -> str | None:
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return None
    return host if parts.scheme in _SCHEMES and host else None


async def resolve_schemas(database_url: str, names: set[str]) -> dict[str, SchemaRef]:
    """Each active schema named, from the main database's `schema_def`."""
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(SchemaRow.id, SchemaRow.name, SchemaRow.page_kind).where(
                        SchemaRow.name.in_(names), SchemaRow.status == "active"
                    )
                )
            ).all()
    finally:
        await engine.dispose()
    _check_found(names, {row.name for row in rows})
    return {row.name: SchemaRef(row.id, row.name, row.page_kind) for row in rows}


def _check_found(names: set[str], found: set[str]) -> None:
    if missing := sorted(names - found):
        raise EvalCliError(f"no active schema named {', '.join(missing)}")


async def active_schemas(database_url: str, names: set[str] | None = None) -> dict[str, Schema]:
    """The active schemas of the main database's `schema_def` by name, as documents the engine runs: those named in
    `names`, or every one."""
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            if names is None:
                return {schema.name: schema for schema in await list_schemas(conn, status="active")}
            found = [
                schema for name in sorted(names) for schema in await list_schemas(conn, name=name, status="active")
            ]
    finally:
        await engine.dispose()
    _check_found(names, {schema.name for schema in found})
    return {schema.name: schema for schema in found}


async def capture_pages(
    store: EvalStore,
    schemas: Mapping[str, SchemaRef],
    requests: Sequence[PageRequest],
    fetch: Fetch,
    limiter: HostLimiter,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> list[Outcome]:
    """Fetch each page in order, politely, and store it with an unlabeled eval page in `store`. Every fetched page is
    stored whatever its outcome, so the acquisition mix per category (§4.6) includes blocked and failed fetches."""
    robots: dict[str, Robots | None] = {}
    outcomes: list[Outcome] = []
    for request in requests:
        origin = robots_url(request.url)
        if origin not in robots:
            # robots.txt fetches are not spaced (D-0165): one per origin per run.
            snapshot = snapshot_of(await fetch(origin))
            robots[origin] = None if snapshot is None else Robots(snapshot.body)
        rules = robots[origin]
        if rules is None:
            outcomes.append(Skipped(request.n, "robots_unreachable"))
            continue
        if not rules.allows(request.url):
            outcomes.append(Skipped(request.n, "robots"))
            continue
        host = urlsplit(request.url).hostname or ""
        while (wait := limiter.admit(host, interval(None, rules.crawl_delay))).total_seconds() > 0:
            await sleep(wait.total_seconds())
        result = await fetch(request.url)
        outcomes.append(await store_page(store, schemas[request.schema_name], request, result))
    return outcomes


async def store_page(store: EvalStore, schema: SchemaRef, request: PageRequest, result: FetchResult) -> Captured:
    """Store a fetched page as an eval capture and an unlabeled eval page, whatever its outcome."""
    capture_id = await store.put_capture(result.bundle, request.category)
    page_id = await store.put_page(
        EvalPageRow(
            capture_id=capture_id,
            split=store.split,
            schema_id=schema.id,
            schema_name=schema.name,
            page_kind=schema.page_kind,
            category=request.category,
        )
    )
    manifest = result.bundle.manifest
    return Captured(
        request.n, capture_id, page_id, manifest.status_code, manifest.block_class, result.attempts[-1].error
    )


async def run_capture(
    settings: Settings,
    requests: Sequence[PageRequest],
    page_kind: PageKind | None = None,
    connector: SafeConnector | None = None,
) -> list[Outcome]:
    """Capture `requests` into the golden set. `page_kind`, when given, must be every schema's page kind."""
    schemas = await resolve_schemas(
        settings.database_url.get_secret_value(), {request.schema_name for request in requests}
    )
    if page_kind is not None:
        for schema in schemas.values():
            if schema.page_kind != page_kind:
                raise EvalCliError(f"schema {schema.name} is for {schema.page_kind} pages, not {page_kind}")
    store = dev_store(settings)
    fetch = partial(
        fetch_http,
        policy=FetchPolicy(),
        engine_version=ENGINE_VERSION,
        impersonate=rung_impersonation(settings),
        connector=connector,
    )
    async with aclosing(store):
        return await capture_pages(store, schemas, requests, fetch, HostLimiter())


def report(outcomes: Sequence[Outcome]) -> str:
    """One JSON line per page, in input order."""
    return "".join(json.dumps(_line(outcome)) + "\n" for outcome in sorted(outcomes, key=lambda o: o.n))


def _line(outcome: Outcome) -> dict[str, object]:
    match outcome:
        case Captured():
            return {
                "n": outcome.n,
                "capture_id": str(outcome.capture_id),
                "page_id": str(outcome.page_id),
                "status_code": outcome.status_code,
                "block_class": outcome.block_class,
                "error": outcome.error,
            }
        case Skipped():
            return {"n": outcome.n, "skipped": outcome.reason}
