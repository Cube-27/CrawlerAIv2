"""Stand-ins the tests/db files share: a site the rungs fetch from (`Web`), the `Fetching` built over it
(`fetching_from`), the kettle schema's fields, and the app with a client holding a key (`api`). `conftest.py` makes
fixtures of them."""

import itertools
import socket
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from ipaddress import ip_address
from pathlib import Path
from typing import Any, NamedTuple, Self

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rung, Rungs
from crawlerai.acquire.ssrf import IPAddress, Resolver, SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.api.app import create_app
from crawlerai.core.capture import BlockClass, CaptureMethod
from crawlerai.core.egress import Egresses
from crawlerai.db.keys import create_key
from crawlerai.services.fetching import Fetching
from crawlerai.storage.artifacts import SCREENSHOT
from crawlerai.storage.base import ObjectStore
from crawlerai.storage.capture_bundle import HeaderList
from crawlerai.storage.fs import FsStore

# A detail schema's fields: the product's name and its price (the schema.org properties `Product.name` and
# `Offer.price` with `priceCurrency`).
TITLE: dict[str, Any] = {
    "type": "text",
    "required": True,
    "description": "The product's name",
    "schema_org": "Product.name",
}
PRICE: dict[str, Any] = {
    "type": "money",
    "required": True,
    "description": "The price",
    "schema_org": "Offer.price+priceCurrency",
}
# robots.txt allowing every path (RFC 9309).
ALLOW_ALL = b"User-agent: *\nAllow: /\n"
PRIVATE_HOST = "intranet.example.test"
UNRESOLVED_HOST = "gone.example.test"  # a host the stub resolver finds no address for
KEY_LABEL = "api-test"  # the label of the key `api` creates


async def resolve(host: str) -> list[IPAddress]:
    """A stub resolver: `PRIVATE_HOST` has a private address, `UNRESOLVED_HOST` none, every other host a public one."""
    if host == UNRESOLVED_HOST:
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
    return [ip_address("10.0.0.7" if host == PRIVATE_HOST else "93.184.215.14")]


class Page(NamedTuple):
    """One URL's answer: what a rung reports for it."""

    status: int
    body: bytes
    block_class: BlockClass = "ok"
    error: str | None = None
    headers: HeaderList = ()


NOT_FOUND = Page(404, b"gone", "not_found")


@dataclass
class Web:
    """A site for the rungs: each URL answers from `pages`, reached through the site's redirect when it is in
    `redirects`; anything else is a 404. Every rung answers the same pages; `fetched` lists each fetch's method and
    URL. A browser fetch whose policy asks for a screenshot carries `screenshot` as the page's PNG. A test's own
    stand-in extends `fetch`, or `rungs` for the rungs it adds."""

    fetch_result: Callable[..., FetchResult]
    pages: dict[str, Page] = field(default_factory=dict)
    redirects: dict[str, str] = field(default_factory=dict)  # a URL -> where its redirects end
    fetched: list[tuple[CaptureMethod, str]] = field(default_factory=list)
    screenshot: bytes = b"\x89PNG"

    @classmethod
    def site(cls, fetch_result: Callable[..., FetchResult], origin: str, **fields: Any) -> Self:
        """`origin` as a site whose robots.txt allows everything."""
        web = cls(fetch_result, **fields)
        web.robots(origin)
        return web

    def serve(self, url: str, body: bytes, status: int = 200, block_class: BlockClass = "ok") -> None:
        self.pages[url] = Page(status, body, block_class)

    def robots(self, origin: str, body: bytes = ALLOW_ALL) -> None:
        self.serve(f"{origin}/robots.txt", body)

    def answer(self, url: str, method: CaptureMethod, policy: FetchPolicy) -> FetchResult:
        final_url = self.redirects.get(url, url)
        page = self.pages.get(final_url, NOT_FOUND)
        return self.fetch_result(
            url,
            page.status,
            page.body,
            page.headers,
            block_class=page.block_class,
            error=page.error,
            method=method,
            policy=policy,
            final_url=final_url,
        )

    async def fetch(self, method: CaptureMethod, url: str, policy: FetchPolicy) -> FetchResult:
        self.fetched.append((method, url))
        result = self.answer(url, method, policy)
        if method == "browser" and policy.screenshot is not None:
            return result.model_copy(update={"artifacts": {SCREENSHOT: self.screenshot}})
        return result

    def rung(self, method: CaptureMethod) -> Rung:
        async def fetch(url: str, policy: FetchPolicy) -> FetchResult:
            return await self.fetch(method, url, policy)

        return fetch

    def rungs(self) -> Rungs:
        return Rungs(http=self.rung("http"), browser=self.rung("browser"))

    def urls(self, method: CaptureMethod | None = None) -> list[str]:
        """The URLs fetched, by `method` only when given."""
        return [url for used, url in self.fetched if method in (None, used)]

    def page_fetches(self) -> list[tuple[CaptureMethod, str]]:
        """The fetches, robots.txt's left out."""
        return [(method, url) for method, url in self.fetched if not url.endswith("/robots.txt")]


def unpaced() -> HostLimiter:
    """A limiter whose clock jumps an hour ahead on every reading, so no host's spacing makes a test wait."""
    clock = itertools.count(step=3600)
    return HostLimiter(clock=lambda: float(next(clock)))


def fetching_from(
    web: Web | Rungs,
    store: Path | ObjectStore,
    *,
    resolver: Resolver = resolve,
    limiter: HostLimiter | None = None,
    egresses: Egresses | None = None,
) -> Fetching:
    """What a service fetches with: `web`'s rungs (or `web` itself, rungs a test built), through the SSRF guard on
    `resolver`, storing captures in `store` (a directory, else the store itself)."""
    rungs = web.rungs() if isinstance(web, Web) else web
    objects = FsStore(store) if isinstance(store, Path) else store
    return Fetching(rungs, SafeConnector(resolver), objects, limiter or HostLimiter(), egresses or Egresses())


@asynccontextmanager
async def api(engine: AsyncEngine) -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient]]:
    """The app, in its lifespan, on the settings of the environment (`app_env`), and a client holding a new key."""
    async with engine.begin() as conn:
        key = await create_key(conn, KEY_LABEL)
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://api.test",
            headers={"authorization": f"Bearer {key.key}"},
        ) as client,
    ):
        yield app, client
