"""INV-16 at the endpoints (SPEC-10 §6, §21 L3 done-when): every REST endpoint that takes a URL refuses a target that
is not a public address, wherever the target comes from: a URL the request names (`url`, `urls`, a glob of `urls`,
`webhook_url`), a redirect hop, or a location a sitemap or page lists.

A target the request names is refused before anything is stored or fetched: a 422 `ssrf_rejected` problem that names
the member and never echoes the URL. A target reached while fetching is refused by the guard on that hop: an endpoint
that answers while the caller waits (`scrape`, `map`, a glob's map in `extract`) answers the 422; a job's task fails
with the guard's reason, and the job goes on.

The app runs with the real guard (`SafeConnector`) and the real HTTP rung (`fetch_http`) against a local server on
127.0.0.1. Only the test site's host, at the server's port, is pinned to the server; every other name goes through the
guard with a stub resolver (RFC 2606 `.test` names), so nothing leaves the machine.
"""

import asyncio
import functools
import itertools
import threading
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import IPv4Address, ip_address
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent
from pydantic import SecretStr
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from crawlerai.acquire.http import fetch_http
from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import IPAddress, SafeConnector, Target
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.api.app import create_app
from crawlerai.core.settings import IMPERSONATE_DEFAULT, Settings
from crawlerai.db.models import ApiKey, Job, JobId, JobKind, UrlTask
from crawlerai.resolve.pipeline import EngineData
from crawlerai.schemas import registry
from crawlerai.schemas.types import SchemaDocument
from crawlerai.services.fetching import Fetching
from crawlerai.services.keys import create_key
from crawlerai.storage.fs import FsStore
from crawlerai.worker.handlers.crawl import crawl_handler
from crawlerai.worker.handlers.scrape import scrape_handler
from crawlerai.worker.loop import TaskHandler, run_worker

pytestmark = pytest.mark.anyio

NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
TITLE = {"type": "text", "required": True, "description": "The product's name", "schema_org": "Product.name"}

# The stub resolver's names (RFC 2606 `.test`): a name whose first label is `PRIVATE_LABEL` has a private address,
# and any other name not in `DNS` a public one.
PRIVATE_LABEL = "intranet"
DNS: dict[str, tuple[str, ...]] = {
    "ula.example.test": ("fd00::7",),
    # One private address among public ones refuses the name (SPEC-02 §4.5: "if any address is private").
    "mixed.example.test": ("93.184.215.14", "192.168.1.9"),
}
UNRESOLVED = "nowhere.example.test"


def html(content: str) -> str:
    """A page with enough visible text to classify as a page, not a shell (SPEC-02 §4.3)."""
    text = "<p>A shop that sells kettles, teapots and cups, delivered within three working days.</p>" * 4
    head = "<!doctype html><html lang='en'><head><title>Shop</title></head>"
    return f"{head}<body><main>{text}{content}</main></body></html>"


# --- the local server and the guard in front of it ----------------------------------------------------------------


@dataclass
class Server:
    """Answers each path from `routes` with (status, headers, body); anything else is a 404."""

    port: int
    routes: dict[str, tuple[int, tuple[tuple[str, str], ...], bytes]] = field(default_factory=dict)

    def page(self, path: str, body: str, content_type: str = "text/html; charset=utf-8") -> None:
        self.routes[path] = (200, (("Content-Type", content_type),), body.encode())

    def redirect(self, path: str, location: str) -> None:
        self.routes[path] = (302, (("Location", location),), b"")


@pytest.fixture
def server() -> Iterator[Server]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            status, headers, body = srv.routes.get(self.path, (404, (), b"no route"))
            self.send_response(status)
            for name, value in headers:
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    srv = Server(port=httpd.server_address[1])  # the handler reads it when a request arrives
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield srv
    httpd.shutdown()
    httpd.server_close()


async def resolve(host: str) -> list[IPAddress]:
    if host == UNRESOLVED:
        raise OSError("no such host")
    if host.split(".", 1)[0] == PRIVATE_LABEL:
        return [ip_address("10.0.0.7")]
    return [ip_address(address) for address in DNS.get(host, ("93.184.215.14",))]


class SiteConnector(SafeConnector):
    """The guard, except that the test site's host at the server's port is pinned to the server: the one target the
    test admits without the guard. Every other URL, a redirect hop included, is checked by the real guard."""

    def __init__(self, host: str, port: int) -> None:
        super().__init__(resolve)
        self._host = host
        self._port = port

    async def check(self, url: str) -> Target:
        parts = urlsplit(url)
        if (parts.hostname, parts.port) == (self._host, self._port):
            return Target(url=url, host=self._host, port=self._port, ip=IPv4Address("127.0.0.1"))
        return await super().check(url)


@pytest.fixture
def site(server: Server, own_origin: str) -> str:
    """The test site's origin, served by the local server: `own_origin`'s host at the server's port."""
    return f"http://{urlsplit(own_origin).hostname}:{server.port}"


@pytest.fixture
def fetching(server: Server, site: str, tmp_path: Path) -> Fetching:
    """The real HTTP rung through the guard; the browser is never needed. The limiter's clock jumps ahead on every
    reading, so the site's rate never makes a test wait."""
    connector = SiteConnector(urlsplit(site).hostname or "", server.port)
    http = functools.partial(fetch_http, engine_version="test", impersonate=IMPERSONATE_DEFAULT, connector=connector)

    async def browser(url: str, policy: FetchPolicy) -> FetchResult:
        raise AssertionError("no page here needs a browser")

    clock = itertools.count(step=3600)
    limiter = HostLimiter(clock=lambda: float(next(clock)))
    rungs = Rungs(http=http, browser=browser, conditional=http)
    return Fetching(rungs, connector, FsStore(tmp_path / "objects"), limiter)


@pytest.fixture
async def schema_id(engine: AsyncEngine, schema_name: str) -> str:
    document = {"name": schema_name, "version": 1, "page_kind": "detail", "fields": {"title": TITLE}}
    async with engine.begin() as conn:
        return str((await registry.create(conn, SchemaDocument.model_validate(document), "user")).id)


@pytest.fixture
async def client(
    database_url: str,
    engine: AsyncEngine,
    engine_data: EngineData,
    fetching: Fetching,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> AsyncIterator[httpx.AsyncClient]:
    """The app against the test database, fetching through `fetching`. `engine` deletes the jobs afterwards; the key
    is deleted here."""
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", database_url)
    monkeypatch.setenv("CRAWLERAI_OBJECT_STORE", "fs:///" + tmp_path.as_posix().lstrip("/"))
    monkeypatch.setenv("CRAWLERAI_TRUSTED_PROXIES", "[]")
    async with engine.begin() as conn:
        key = await create_key(conn, "ssrf-matrix-test")
    app = create_app(eval_ui=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://api.test",
            headers={"authorization": f"Bearer {key.key}"},
        ) as client,
    ):
        app.state.fetching = fetching
        app.state.engine_data = engine_data
        yield client
    keys_engine = create_async_engine(database_url)
    async with keys_engine.begin() as conn:
        await conn.execute(update(Job).where(Job.api_key_id == key.id).values(api_key_id=None))
        await conn.execute(delete(ApiKey).where(ApiKey.id == key.id))
    await keys_engine.dispose()


async def job_count(engine: AsyncEngine) -> int:
    async with engine.connect() as conn:
        return (await conn.execute(select(func.count()).select_from(Job))).scalar_one()


async def run_job(engine: AsyncEngine, fetching: Fetching, data: EngineData, job_id: JobId) -> dict[str, Any]:
    """Run a worker loop, with the handlers of every job kind that fetches, until the job has ended; its tasks by
    URL."""
    url = engine.url.render_as_string(hide_password=False)
    settings = Settings(database_url=SecretStr(url), object_store="fs:///unused")
    handlers: dict[JobKind, TaskHandler] = {
        "batch_scrape": scrape_handler(fetching, data, None, llm=None),
        "crawl": crawl_handler(fetching, data, None, llm=None),
        "extract": scrape_handler(fetching, data, None, llm=None),
    }
    stop = asyncio.Event()
    loop = asyncio.create_task(run_worker(settings, handlers, stop))
    try:
        async with asyncio.timeout(60):
            while await _status(engine, job_id) not in ("completed", "failed", "cancelled"):
                await asyncio.sleep(0.1)
    finally:
        # A timed-out wait stops the worker too, before the fixtures delete what it would claim.
        stop.set()
        await loop
    async with engine.connect() as conn:
        rows = await conn.execute(select(UrlTask).where(UrlTask.job_id == job_id))
    return {row.url: row for row in rows}


async def _status(engine: AsyncEngine, job_id: JobId) -> str:
    async with engine.connect() as conn:
        return (await conn.execute(select(Job.status).where(Job.id == job_id))).scalar_one()


# --- targets the request names --------------------------------------------------------------------------------------

# Each form of a target that is not a public address, as the authority and path of an http URL, with the guard's
# reason (SPEC-02 §4.5, RFC 6890 registries).
TARGETS: Sequence[tuple[str, str]] = [
    ("10.0.0.1/", "private_address"),  # RFC 1918
    ("172.16.0.1/", "private_address"),  # RFC 1918
    ("192.168.0.1/", "private_address"),  # RFC 1918
    ("127.0.0.1/", "private_address"),  # loopback, RFC 1122 §3.2.1.3
    ("169.254.169.254/latest/meta-data/", "private_address"),  # link-local (RFC 3927), cloud metadata
    ("100.64.0.1/", "private_address"),  # shared address space, RFC 6598
    ("0.0.0.0/", "private_address"),  # unspecified, RFC 1122
    ("224.0.0.1/", "private_address"),  # multicast, RFC 5771
    ("[::1]/", "private_address"),  # IPv6 loopback, RFC 4291 §2.5.3
    ("[fe80::1]/", "private_address"),  # IPv6 link-local, RFC 4291 §2.5.6
    ("[fd00::1]/", "private_address"),  # unique-local, RFC 4193
    ("[::ffff:10.0.0.1]/", "private_address"),  # IPv4-mapped, RFC 4291 §2.5.5.2
    ("[64:ff9b::a00:1]/", "private_address"),  # NAT64 of 10.0.0.1, RFC 6052
    ("user@10.0.0.1/", "private_address"),  # userinfo does not hide the host, RFC 3986 §3.2.1
    ("2130706433/", "host"),  # 127.0.0.1 as one number, WHATWG URL §3.5
    ("0x7f.0.0.1/", "host"),  # a hex part, WHATWG URL §3.5
    ("127.1/", "host"),  # a short form, WHATWG URL §3.5
    ("intranet.example.test/", "private_address"),  # a name with a private address
    ("ula.example.test/", "private_address"),  # a name with a unique-local address
    ("mixed.example.test/", "private_address"),  # a name with one private address among public ones
    (f"{UNRESOLVED}/", "dns"),  # a name that does not resolve
    ("www.example.test:6379/", "port"),  # a port no web page is served on
]


@dataclass(frozen=True)
class Member:
    """Where a request names a target: `body` builds the request around it, `field` is the member a refusal names
    (`None` where the endpoint has one target, which its problem does not name)."""

    path: str
    field: str | None
    body: Callable[[str, str, str], dict[str, Any]]  # (target, a public URL of the site, a schema id) -> body
    glob: bool = False

    def __str__(self) -> str:
        return f"{self.path}:{self.field or 'url'}{':glob' if self.glob else ''}"


def _extract(urls: list[str], schema_id: str, **members: Any) -> dict[str, Any]:
    return {"urls": urls, "schema": {"id": schema_id}, "page_kind": "detail", **members}


def _glob(target: str) -> str:
    return target.rstrip("/") + "/p/*"


MEMBERS: Sequence[Member] = [
    Member("/v1/scrape", None, lambda target, _, __: {"url": target, "formats": ["markdown"]}),
    Member("/v1/map", None, lambda target, _, __: {"url": target}),
    Member(
        "/v1/batch/scrape", "urls[1]", lambda target, public, _: {"urls": [public, target], "formats": ["markdown"]}
    ),
    Member(
        "/v1/batch/scrape",
        "webhook_url",
        lambda target, public, _: {"urls": [public], "formats": ["markdown"], "webhook_url": target},
    ),
    Member("/v1/crawl", "url", lambda target, _, __: {"url": target, "formats": ["markdown"]}),
    Member(
        "/v1/crawl",
        "webhook_url",
        lambda target, public, _: {"url": public, "formats": ["markdown"], "webhook_url": target},
    ),
    Member("/v1/extract", "urls[1]", lambda target, public, schema: _extract([public, target], schema)),
    Member(
        "/v1/extract", "urls[1]", lambda target, public, schema: _extract([public, _glob(target)], schema), glob=True
    ),
    Member("/v1/extract", "webhook_url", lambda target, public, schema: _extract([public], schema, webhook_url=target)),
]


def _named() -> list[Any]:
    cases = []
    for member, (authority, reason) in itertools.product(MEMBERS, TARGETS):
        target = f"http://{authority}"
        # A glob's `[` is a pattern character, so a glob on an IPv6 literal (RFC 3986 §3.2.2) is no glob on one host:
        # it is invalid before the guard sees it (`test_a_glob_on_an_ipv6_literal_is_invalid`).
        if not (member.glob and "[" in target):
            cases.append(pytest.param(member, target, reason, id=f"{member}-{target}"))
    return cases


@pytest.mark.parametrize(("member", "target", "reason"), _named())
async def test_a_named_target_is_refused_before_anything_is_stored(
    client: httpx.AsyncClient, engine: AsyncEngine, site: str, schema_id: str, member: Member, target: str, reason: str
) -> None:
    jobs = await job_count(engine)

    response = await client.post(member.path, json=member.body(target, f"{site}/p/1", schema_id))

    assert response.status_code == 422, response.text
    assert response.headers["content-type"] == "application/problem+json"
    problem = response.json()
    refusal = f"ssrf_rejected: {reason}"
    if member.field is None:
        assert (problem["type"], problem["detail"], problem["errors"]) == ("ssrf_rejected", refusal, [])
    else:
        assert (problem["type"], problem["errors"]) == ("ssrf_rejected", [{"field": member.field, "reason": refusal}])
    # The problem never echoes the target (SPEC-02 §4.11).
    assert str(urlsplit(target).hostname) not in response.text
    assert await job_count(engine) == jobs


@dataclass(frozen=True)
class Tool:
    """Where an MCP tool's request names a target (SPEC-10 §4.7): `request` builds the tool's `request` around it,
    `field` is the member a refusal names (`None` where the tool has one target)."""

    name: str
    field: str | None
    request: Callable[[str, str, str], dict[str, Any]]  # (target, a public URL of the site, a schema id) -> request
    glob: bool = False

    def __str__(self) -> str:
        return f"{self.name}:{self.field or 'url'}{':glob' if self.glob else ''}"


# The tools that fetch, each target as its REST endpoint takes it (`MEMBERS`).
TOOLS: Sequence[Tool] = [
    Tool("scrape", None, lambda target, _, __: {"url": target, "formats": ["markdown"]}),
    Tool("map", None, lambda target, _, __: {"url": target}),
    Tool("crawl_start", "url", lambda target, _, __: {"url": target, "formats": ["markdown"]}),
    Tool(
        "crawl_start",
        "webhook_url",
        lambda target, public, _: {"url": public, "formats": ["markdown"], "webhook_url": target},
    ),
    Tool("extract", "urls[1]", lambda target, public, schema: _extract([public, target], schema)),
    Tool("extract", "urls[1]", lambda target, public, schema: _extract([public, _glob(target)], schema), glob=True),
    Tool("extract", "webhook_url", lambda target, public, schema: _extract([public], schema, webhook_url=target)),
]


@pytest.fixture
async def mcp(client: httpx.AsyncClient) -> AsyncIterator[ClientSession]:
    """The SDK's MCP client, connected to `/mcp` through `client`."""
    async with (
        streamable_http_client("http://api.test/mcp", http_client=client) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield session


def _named_to_tools() -> list[Any]:
    cases = []
    for tool, (authority, reason) in itertools.product(TOOLS, TARGETS):
        target = f"http://{authority}"
        if not (tool.glob and "[" in target):  # as in `_named`
            cases.append(pytest.param(tool, target, reason, id=f"{tool}-{target}"))
    return cases


@pytest.mark.parametrize(("tool", "target", "reason"), _named_to_tools())
async def test_a_target_named_to_an_mcp_tool_is_refused_before_anything_is_stored(
    mcp: ClientSession, engine: AsyncEngine, site: str, schema_id: str, tool: Tool, target: str, reason: str
) -> None:
    jobs = await job_count(engine)

    result = await mcp.call_tool(tool.name, {"request": tool.request(target, f"{site}/p/1", schema_id)})

    refusal = f"ssrf_rejected: {reason}" if tool.field is None else f"{tool.field}: ssrf_rejected: {reason}"
    texts = [block.text for block in result.content if isinstance(block, TextContent)]
    assert (result.isError, texts) == (True, [f"Error executing tool {tool.name}: {refusal}"])
    assert await job_count(engine) == jobs


@pytest.mark.parametrize("target", ["file:///etc/passwd", "gopher://www.example.test/", "ftp://www.example.test/"])
@pytest.mark.parametrize("member", MEMBERS, ids=str)
async def test_a_target_of_another_scheme_is_invalid(
    client: httpx.AsyncClient, engine: AsyncEngine, site: str, schema_id: str, member: Member, target: str
) -> None:
    jobs = await job_count(engine)

    response = await client.post(member.path, json=member.body(target, f"{site}/p/1", schema_id))

    assert response.status_code == 422, response.text
    assert response.json()["type"] == "validation"
    assert await job_count(engine) == jobs


async def test_a_glob_on_an_ipv6_literal_is_invalid(
    client: httpx.AsyncClient, engine: AsyncEngine, site: str, schema_id: str
) -> None:
    jobs = await job_count(engine)

    response = await client.post("/v1/extract", json=_extract([f"{site}/p/1", "http://[::1]/p/*"], schema_id))

    assert response.status_code == 422, response.text
    assert response.json()["type"] == "validation"
    assert await job_count(engine) == jobs


# --- targets reached while fetching -------------------------------------------------------------------------------

# Redirect locations the guard refuses on the hop (SPEC-02 §4.5: every hop is checked from scratch).
REDIRECTS: Sequence[tuple[str, str]] = [
    ("http://intranet.example.test/admin", "private_address"),
    ("http://169.254.169.254/latest/meta-data/", "private_address"),
    ("http://[::1]:8080/", "private_address"),
    ("//10.0.0.1/", "private_address"),  # scheme-relative, resolved against the current URL (RFC 3986 §5.2)
    ("http://www.example.test:6379/", "port"),
]


@pytest.mark.parametrize(("location", "reason"), REDIRECTS, ids=[location for location, _ in REDIRECTS])
@pytest.mark.parametrize(
    ("moved", "path", "body"),
    [
        pytest.param(
            "/moved", "/v1/scrape", lambda site: {"url": f"{site}/moved", "formats": ["markdown"]}, id="scrape"
        ),
        pytest.param("/", "/v1/map", lambda site: {"url": f"{site}/"}, id="map-start-page"),
    ],
)
async def test_a_page_redirected_to_a_refused_target_is_a_problem(
    client: httpx.AsyncClient,
    server: Server,
    site: str,
    moved: str,
    path: str,
    body: Callable[[str], dict[str, Any]],
    location: str,
    reason: str,
) -> None:
    server.redirect(moved, location)

    response = await client.post(path, json=body(site))

    assert response.status_code == 422, response.text
    assert {k: response.json()[k] for k in ("type", "detail")} == {
        "type": "ssrf_rejected",
        "detail": f"ssrf_rejected: {reason}",
    }


async def test_a_map_whose_sitemap_redirects_to_a_refused_target_is_a_problem(
    client: httpx.AsyncClient, server: Server, site: str
) -> None:
    server.page("/robots.txt", f"User-agent: *\nAllow: /\nSitemap: {site}/s.xml\n", "text/plain")
    server.page("/", html("<h1>Home</h1>"))
    server.redirect("/s.xml", "http://intranet.example.test/s.xml")

    response = await client.post("/v1/map", json={"url": f"{site}/"})

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "ssrf_rejected: private_address"


async def test_an_extract_glob_whose_map_redirects_to_a_refused_target_is_a_problem(
    client: httpx.AsyncClient, engine: AsyncEngine, server: Server, site: str, schema_id: str
) -> None:
    server.redirect("/", "http://169.254.169.254/latest/meta-data/")
    jobs = await job_count(engine)

    response = await client.post("/v1/extract", json=_extract([f"{site}/p/*"], schema_id))

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "ssrf_rejected: private_address"
    # The glob's map is a job of its own, which failed; no extract job was stored.
    async with engine.connect() as conn:
        kinds = (await conn.execute(select(Job.kind, Job.status).order_by(Job.created_at))).all()
    assert [tuple(row) for row in kinds[jobs:]] == [("map", "failed")]


@pytest.mark.parametrize(
    "submit",
    [
        pytest.param(
            lambda site, _: ("/v1/batch/scrape", {"urls": [f"{site}/moved"], "formats": ["markdown"]}), id="batch"
        ),
        pytest.param(lambda site, _: ("/v1/crawl", {"url": f"{site}/moved", "formats": ["markdown"]}), id="crawl"),
        pytest.param(lambda site, schema: ("/v1/extract", _extract([f"{site}/moved"], schema)), id="extract"),
    ],
)
async def test_a_job_task_redirected_to_a_refused_target_fails_with_the_guards_reason(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    engine_data: EngineData,
    fetching: Fetching,
    server: Server,
    site: str,
    schema_id: str,
    submit: Callable[[str, str], tuple[str, dict[str, Any]]],
) -> None:
    server.redirect("/moved", "http://intranet.example.test/admin")
    path, body = submit(site, schema_id)

    response = await client.post(path, json=body)
    assert response.status_code == 202, response.text
    tasks = await run_job(engine, fetching, engine_data, response.json()["job_id"])

    moved = tasks[f"{site}/moved"]
    # Refused at once, never retried (SPEC-02 §4.11).
    assert (moved.outcome, moved.attempts, moved.last_error) == ("failed", 1, "ssrf_rejected: private_address")


async def test_a_crawl_takes_private_locations_only_on_its_site_and_the_guard_refuses_them(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    engine_data: EngineData,
    fetching: Fetching,
    server: Server,
    site: str,
) -> None:
    # A crawl takes only its site's URLs, subdomains included (D-0037); `include` admits the subdomains. So a private
    # location off the site never becomes a task, and one on a subdomain of the site is a task the guard refuses.
    host = urlsplit(site).hostname
    on_site = [f"http://intranet.{host}/admin", f"http://intranet.{host}:8080/meta"]
    off_site = ["http://intranet.example.test/admin", "http://169.254.169.254/latest/meta-data/"]
    entries = "".join(f"<url><loc>{loc}</loc></url>" for loc in (f"{site}/p/1", on_site[0], off_site[0]))
    server.page("/robots.txt", f"User-agent: *\nAllow: /\nSitemap: {site}/s.xml\n", "text/plain")
    server.page("/s.xml", f'<?xml version="1.0"?><urlset xmlns="{NS}">{entries}</urlset>', "application/xml")
    server.page("/", html("".join(f'<a href="{href}">link</a>' for href in ("/p/1", on_site[1], off_site[1]))))
    server.page("/p/1", html("<h1>Kettle</h1>"))

    response = await client.post("/v1/crawl", json={"url": f"{site}/", "formats": ["markdown"], "include": ["*"]})
    assert response.status_code == 202, response.text
    tasks = await run_job(engine, fetching, engine_data, response.json()["job_id"])

    assert {url: (task.outcome, task.last_error) for url, task in tasks.items()} == {
        f"{site}/": ("extracted", None),
        f"{site}/p/1": ("extracted", None),
        **dict.fromkeys(on_site, ("failed", "ssrf_rejected: private_address")),
    }
    assert await _status(engine, response.json()["job_id"]) == "completed"
