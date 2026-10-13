"""`crawlerai eval capture` and `crawlerai eval import-sites` (SPEC-03 §4.4): fetch pages over HTTP and store each as
an eval capture and an unlabeled eval page of one split.

Each page goes to the store of its split (`get_store`): hidden and fresh captures never touch the main database or
object store (C1). Fetches are polite as the worker's are (SPEC-02 §4.6): robots.txt is read once per origin and
obeyed, and requests to one host are spaced by the default interval or the robots `Crawl-delay`, whichever is longer.
The CLI waits out that interval; it runs one page at a time. A host with pages in another split is refused before
anything is fetched, so a site sits in one split only (ARCHITECTURE §16.1).

Nothing printed or raised names a URL or host, so a hidden or fresh site does not reach a log (C1): outcomes are
reported by their position in the input.
"""

import asyncio
import json
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence, Set
from contextlib import aclosing
from dataclasses import dataclass
from functools import partial
from typing import get_args
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from crawlerai.acquire.http import fetch_http
from crawlerai.acquire.politeness import HostLimiter, interval
from crawlerai.acquire.robots import Fetch, Robots, robots_url, snapshot_of
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy
from crawlerai.core.capture import BlockClass
from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.core.settings import Settings
from crawlerai.db.models import CaptureId, EvalCategory, EvalPageId, PageKind, SchemaDef, SchemaId, Split
from crawlerai.eval.store import EvalPageRow, EvalStore, PrivateCredentialsMissing, get_store

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
        host = _host(url)
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
    bad = [str(n) for n, url in enumerate(urls, start=1) if _host(url) is None]
    if bad:
        raise EvalCliError(f"not an http or https URL with a host: URL {', '.join(bad)}")


def _host(url: str) -> str | None:
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return None
    return host if parts.scheme in _SCHEMES and host else None


def check_hosts(requests: Sequence[PageRequest], taken: Mapping[Split, Set[str]]) -> None:
    """Refuse every request when a host of the input has pages in another split: a site sits in one split only, fresh
    being sites nobody has seen and hidden sites absent from dev (ARCHITECTURE §16.1). The refusal gives counts, never
    a host or a line, so it names no hidden or fresh site (C1)."""
    hosts = {host for request in requests if (host := _host(request.url)) is not None}
    overlaps = {split: hosts & taken[split] for split in sorted(taken)}
    refused = set[str]().union(*overlaps.values())
    if refused:
        counts = ", ".join(f"{split}: {len(overlap)}" for split, overlap in overlaps.items() if overlap)
        raise EvalCliError(
            f"{len(refused)} host(s) of the input already have pages in another split ({counts}); a host belongs to"
            " one split (ARCHITECTURE §16.1), so nothing was fetched"
        )


async def hosts_elsewhere(settings: Settings, split: Split) -> dict[Split, set[str]]:
    """The hosts with pages in each split other than `split`. A dev capture reads the private splits only on a
    custodian's machine: elsewhere their hosts are unreadable by design (C1), and a dev capture is not checked
    against them."""
    taken: dict[Split, set[str]] = {}
    for other in get_args(Split):
        if other == split:
            continue
        try:
            opened = get_store(other, settings)
        except PrivateCredentialsMissing:
            if split != "dev":
                raise
            continue
        async with aclosing(opened) as store:
            try:
                taken[other] = await store.hosts()
            except Exception as e:
                # By type only: a dev command shows its failures, and this one comes from a private database (C1).
                raise EvalCliError(f"reading the hosts of the {other} split failed with {type(e).__name__}") from None
    return taken


async def resolve_schemas(database_url: str, names: set[str]) -> dict[str, SchemaRef]:
    """The active version of each schema named, from the main database's `schema_def`. Hidden and fresh pages name
    their schema too; the private database records the id and name only (D-0172)."""
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(SchemaDef.id, SchemaDef.name, SchemaDef.page_kind)
                    .where(SchemaDef.name.in_(names), SchemaDef.status == "active")
                    .order_by(SchemaDef.version)
                )
            ).all()
    finally:
        await engine.dispose()
    # Ordered by version, so the newest active version of each name wins.
    schemas = {row.name: SchemaRef(row.id, row.name, row.page_kind) for row in rows}
    missing = sorted(names - schemas.keys())
    if missing:
        raise EvalCliError(f"no active schema named {', '.join(missing)}")
    return schemas


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
        schema = schemas[request.schema_name]
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
        outcomes.append(
            Captured(
                request.n, capture_id, page_id, manifest.status_code, manifest.block_class, result.attempts[-1].error
            )
        )
    return outcomes


async def run_capture(
    settings: Settings,
    split: Split,
    requests: Sequence[PageRequest],
    page_kind: PageKind | None = None,
    connector: SafeConnector | None = None,
) -> list[Outcome]:
    """Capture `requests` into `split`'s store. `page_kind`, when given, must be every schema's page kind."""
    schemas = await resolve_schemas(
        settings.database_url.get_secret_value(), {request.schema_name for request in requests}
    )
    if page_kind is not None:
        for schema in schemas.values():
            if schema.page_kind != page_kind:
                raise EvalCliError(f"schema {schema.name} is for {schema.page_kind} pages, not {page_kind}")
    check_hosts(requests, await hosts_elsewhere(settings, split))
    store = get_store(split, settings)
    fetch = partial(
        fetch_http,
        policy=FetchPolicy(),
        engine_version=ENGINE_VERSION,
        impersonate=settings.impersonate,
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
