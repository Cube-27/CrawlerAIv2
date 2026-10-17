"""`eval capture` and `eval import-sites` (SPEC-03 §4.4): pages fetched from a local server land in the store of their
split, and only there (C1, INV-01). Synthetic pages under `.test` hosts on 127.0.0.1; throwaway main and private
databases (`CRAWLERAI_TEST_DATABASE_URL`, `CRAWLERAI_TEST_PRIVATE_DATABASE_URL`) and temporary object roots."""

import threading
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import aclosing
from dataclasses import dataclass, field
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import IPv4Address
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from crawlerai.acquire.http import fetch_http
from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.ssrf import SafeConnector, Target
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.core.settings import IMPERSONATE_DEFAULT, Settings
from crawlerai.db.models import Capture, EvalPage, SchemaDef, SchemaId, Site, Split
from crawlerai.db.private_models import PrivateBase
from crawlerai.eval.cli import (
    Captured,
    EvalCliError,
    PageRequest,
    SchemaRef,
    Skipped,
    capture_pages,
    run_capture,
)
from crawlerai.eval.store import DevEvalStore, EvalPageRow, get_store
from crawlerai.storage.fs import FsStore

pytestmark = pytest.mark.anyio

SCHEMA = "eval_capture_detail"
LISTING_SCHEMA = "eval_capture_listing"
HOST = "shop.eval-capture.example.test"
_LINKS = "".join(f'<a href="/item/{i}">Item {i}</a>' for i in range(8))
_PAGE = f"<html><body><h1>Catalogue</h1>{_LINKS}</body></html>".encode()


@dataclass
class Server:
    port: int
    routes: dict[str, tuple[int, bytes]] = field(default_factory=dict)
    requests: list[str] = field(default_factory=list)

    def url(self, path: str, host: str = HOST) -> str:
        return f"http://{host}:{self.port}{path}"


@pytest.fixture
def server() -> Iterator[Server]:
    state: list[Server] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            srv = state[0]
            srv.requests.append(self.headers.get("Host", "").rsplit(":", 1)[0] + self.path)
            status, body = srv.routes.get(self.path, (404, b"no route"))
            self.send_response(status)
            self.send_header("Content-Type", "text/html" if self.path != "/robots.txt" else "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    state.append(Server(port=httpd.server_address[1]))
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield state[0]
    httpd.shutdown()
    httpd.server_close()


class LoopbackConnector(SafeConnector):
    """Sends `.test` hosts on the server's port to 127.0.0.1; everything else goes through the real guard."""

    def __init__(self, port: int) -> None:
        super().__init__()
        self._port = port

    async def check(self, url: str) -> Target:
        parts = urlsplit(url)
        if parts.hostname and parts.hostname.endswith(".test") and parts.port == self._port:
            return Target(url=url, host=parts.hostname, port=self._port, ip=IPv4Address("127.0.0.1"))
        return await super().check(url)


@dataclass
class Env:
    settings: Settings
    main_root: Path
    private_root: Path
    schema_ids: dict[str, SchemaId]


def _fs(path: Path) -> str:
    return "fs:///" + path.as_posix().lstrip("/")


def _files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()) if root.exists() else []


@pytest.fixture
async def env(database_url: str, tmp_path: Path, request: pytest.FixtureRequest) -> AsyncIterator[Env]:
    """Main settings always; private ones only for tests that ask for `private_database_url`."""
    private_url = (
        request.getfixturevalue("private_database_url") if "private_database_url" in request.fixturenames else None
    )
    main_root, private_root = tmp_path / "main", tmp_path / "private"
    settings = Settings.model_validate(
        {
            "database_url": database_url,
            "object_store": _fs(main_root),
            "eval_private_database_url": private_url,
            "eval_private_object_store": _fs(private_root) if private_url else None,
            "impersonate": IMPERSONATE_DEFAULT,
        }
    )
    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        schema_ids = {
            name: (
                await conn.execute(
                    insert(SchemaDef)
                    .values(name=name, page_kind=kind, fields={}, origin="user", status="active")
                    .returning(SchemaDef.id)
                )
            ).scalar_one()
            for name, kind in ((SCHEMA, "detail"), (LISTING_SCHEMA, "listing"))
        }
    yield Env(settings, main_root, private_root, schema_ids)
    async with engine.begin() as conn:
        await conn.execute(delete(EvalPage))
        await conn.execute(delete(Capture).where(Capture.object_key.like("eval/dev/%")))
        await conn.execute(delete(Site).where(Site.host.like("%.example.test")))
        await conn.execute(delete(SchemaDef).where(SchemaDef.name.in_([SCHEMA, LISTING_SCHEMA])))
    await engine.dispose()
    if private_url:
        private_engine = create_async_engine(private_url)
        async with private_engine.begin() as conn:
            for table in reversed(PrivateBase.metadata.sorted_tables):
                await conn.execute(delete(table))
        await private_engine.dispose()


def _requests(server: Server, *paths: str, schema: str = SCHEMA) -> list[PageRequest]:
    return [PageRequest(n, server.url(path), schema, "custom_store") for n, path in enumerate(paths, start=1)]


async def _main_rows(engine: AsyncEngine) -> tuple[list[str], list[str]]:
    """The hosts in the main `site` table and the object keys in its `capture` table."""
    async with engine.connect() as conn:
        hosts = list((await conn.execute(select(Site.host).where(Site.host.like("%.example.test")))).scalars())
        keys = list((await conn.execute(select(Capture.object_key).order_by(Capture.object_key))).scalars())
    return hosts, keys


async def test_dev_captures_land_in_the_main_store_as_unlabeled_pages(env: Env, server: Server) -> None:
    server.routes |= {"/robots.txt": (404, b""), "/p/1": (200, _PAGE), "/p/2": (200, _PAGE)}

    outcomes = await run_capture(
        env.settings, "dev", _requests(server, "/p/1", "/p/2"), "detail", LoopbackConnector(server.port)
    )

    assert [type(o) for o in outcomes] == [Captured, Captured]
    captured = [o for o in outcomes if isinstance(o, Captured)]
    assert [(o.n, o.status_code, o.block_class, o.error) for o in captured] == [
        (1, 200, "ok", None),
        (2, 200, "ok", None),
    ]
    assert _files(env.main_root) == sorted(f"eval/dev/{o.capture_id}.bundle.zst" for o in captured)
    assert _files(env.private_root) == []
    async with aclosing(get_store("dev", env.settings)) as store:
        pages = await store.list_pages(schema_name=SCHEMA)
        bundles = [await store.get_bundle(o.capture_id) for o in captured]
        # What `import-labels` skips when run again (D-1460).
        assert isinstance(store, DevEvalStore)
        assert await store.page_urls() == {server.url("/p/1"), server.url("/p/2")}
    assert pages == [
        EvalPageRow(
            id=o.page_id,
            capture_id=o.capture_id,
            split="dev",
            schema_id=env.schema_ids[SCHEMA],
            schema_name=SCHEMA,
            page_kind="detail",
            category="custom_store",
        )
        for o in captured
    ]
    assert [(b.manifest.url, b.body) for b in bundles] == [(server.url("/p/1"), _PAGE), (server.url("/p/2"), _PAGE)]


@pytest.mark.parametrize("split", ["hidden", "fresh"])
async def test_private_captures_land_only_in_the_private_store(
    env: Env, server: Server, private_database_url: str, engine: AsyncEngine, split: Split
) -> None:
    server.routes |= {"/robots.txt": (404, b""), "/p/1": (200, _PAGE)}

    (outcome,) = await run_capture(env.settings, split, _requests(server, "/p/1"), None, LoopbackConnector(server.port))

    assert isinstance(outcome, Captured)
    assert _files(env.private_root) == [f"{split}/{outcome.capture_id}.bundle.zst"]
    assert _files(env.main_root) == []
    # A private host enters neither the main `site` table nor the main `capture` table.
    assert await _main_rows(engine) == ([], [])
    async with aclosing(get_store(split, env.settings)) as store:
        (page,) = await store.list_pages()
        bundle = await store.get_bundle(outcome.capture_id)
    assert (page.id, page.capture_id, page.split, page.schema_name) == (
        outcome.page_id,
        outcome.capture_id,
        split,
        SCHEMA,
    )
    assert bundle.body == _PAGE


async def test_a_page_robots_txt_disallows_is_not_fetched_or_stored(env: Env, server: Server) -> None:
    server.routes |= {"/robots.txt": (200, b"User-agent: *\nDisallow: /private/\n"), "/private/1": (200, _PAGE)}
    server.routes["/p/1"] = (200, _PAGE)

    outcomes = await run_capture(
        env.settings, "dev", _requests(server, "/private/1", "/p/1"), None, LoopbackConnector(server.port)
    )

    assert isinstance(outcomes[1], Captured)
    assert outcomes[0] == Skipped(1, "robots")
    assert f"{HOST}/private/1" not in server.requests
    assert server.requests.count(f"{HOST}/robots.txt") == 1
    assert len(_files(env.main_root)) == 1


async def test_an_unreachable_robots_txt_allows_nothing(env: Env, server: Server) -> None:
    # RFC 9309 §2.3.1.4: a 5xx robots.txt means the site is unreachable.
    server.routes |= {"/robots.txt": (503, b""), "/p/1": (200, _PAGE)}

    outcomes = await run_capture(env.settings, "dev", _requests(server, "/p/1"), None, LoopbackConnector(server.port))

    assert outcomes == [Skipped(1, "robots_unreachable")]
    assert _files(env.main_root) == []


async def test_a_failed_fetch_is_stored_with_its_outcome(env: Env, server: Server) -> None:
    # The acquisition mix per category (SPEC-03 §4.6) counts pages that did not come back as `ok`.
    server.routes["/robots.txt"] = (404, b"")

    (outcome,) = await run_capture(
        env.settings, "dev", _requests(server, "/gone"), None, LoopbackConnector(server.port)
    )

    assert isinstance(outcome, Captured)
    assert (outcome.status_code, outcome.block_class) == (404, "not_found")
    assert _files(env.main_root) == [f"eval/dev/{outcome.capture_id}.bundle.zst"]


async def test_pages_of_one_host_are_spaced_by_the_robots_crawl_delay(env: Env, server: Server) -> None:
    server.routes |= {"/robots.txt": (200, b"User-agent: *\nCrawl-delay: 5\n"), "/p/1": (200, _PAGE)}
    server.routes |= {"/p/2": (200, _PAGE), "/p/3": (200, _PAGE)}
    now = [0.0]
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    store = DevEvalStore(create_async_engine(env.settings.database_url.get_secret_value()), FsStore(env.main_root))
    schemas = {SCHEMA: SchemaRef(env.schema_ids[SCHEMA], SCHEMA, "detail")}
    fetch = partial(
        fetch_http,
        policy=FetchPolicy(),
        engine_version="test",
        impersonate=IMPERSONATE_DEFAULT,
        connector=LoopbackConnector(server.port),
    )

    async with aclosing(store):
        outcomes = await capture_pages(
            store, schemas, _requests(server, "/p/1", "/p/2", "/p/3"), fetch, HostLimiter(lambda: now[0]), sleep
        )

    assert [type(o) for o in outcomes] == [Captured] * 3
    assert slept == [5.0, 5.0]


async def test_a_schema_of_another_page_kind_is_refused_before_any_fetch(env: Env, server: Server) -> None:
    requests, connector = _requests(server, "/p/1", schema=LISTING_SCHEMA), LoopbackConnector(server.port)

    with pytest.raises(EvalCliError, match=f"schema {LISTING_SCHEMA} is for listing pages, not detail"):
        await run_capture(env.settings, "dev", requests, "detail", connector)

    assert server.requests == []


async def test_an_unknown_schema_is_refused_before_any_fetch(env: Env, server: Server) -> None:
    requests, connector = _requests(server, "/p/1", schema="eval_capture_unknown"), LoopbackConnector(server.port)

    with pytest.raises(EvalCliError, match="no active schema named eval_capture_unknown"):
        await run_capture(env.settings, "dev", requests, None, connector)

    assert server.requests == []


async def test_a_retired_schema_is_refused_before_any_fetch(env: Env, server: Server, engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(update(SchemaDef).where(SchemaDef.name == SCHEMA).values(status="retired"))
    requests, connector = _requests(server, "/p/1"), LoopbackConnector(server.port)

    with pytest.raises(EvalCliError, match=f"no active schema named {SCHEMA}"):
        await run_capture(env.settings, "dev", requests, None, connector)

    assert server.requests == []


async def _seed(env: Env, split: Split, host: str, fetch_result: Callable[..., FetchResult]) -> None:
    """One captured page of `host` in `split`'s store."""
    bundle = fetch_result(f"https://{host}/seed", body=_PAGE).bundle
    async with aclosing(get_store(split, env.settings)) as store:
        capture_id = await store.put_capture(bundle, "custom_store")
        await store.put_page(
            EvalPageRow(
                capture_id=capture_id,
                split=split,
                schema_id=env.schema_ids[SCHEMA],
                schema_name=SCHEMA,
                page_kind="detail",
                category="custom_store",
            )
        )


async def _pages(env: Env, split: Split) -> list[EvalPageRow]:
    async with aclosing(get_store(split, env.settings)) as store:
        return await store.list_pages()


OTHER_HOST = "other.eval-capture.example.test"


@pytest.mark.parametrize(
    ("split", "other"),
    # One private split against the other, a private split against the main store, the main store against a private
    # split: `hosts_elsewhere` reads every other split alike, so the remaining pairs take the same path.
    [("fresh", "hidden"), ("hidden", "dev"), ("dev", "fresh")],
)
async def test_a_host_with_pages_in_another_split_is_refused_before_any_fetch(
    env: Env,
    server: Server,
    private_database_url: str,
    fetch_result: Callable[..., FetchResult],
    split: Split,
    other: Split,
) -> None:
    # A host sits in one split only: fresh is sites nobody has seen, hidden is sites absent from dev (§16.1).
    await _seed(env, other, HOST, fetch_result)
    server.routes |= {"/robots.txt": (404, b""), "/p/1": (200, _PAGE)}
    requests = [*_requests(server, "/p/1"), PageRequest(2, server.url("/p/1", OTHER_HOST), SCHEMA, "custom_store")]
    connector = LoopbackConnector(server.port)

    with pytest.raises(EvalCliError) as error:
        await run_capture(env.settings, split, requests, None, connector)

    assert str(error.value) == (
        f"1 host(s) of the input already have pages in another split ({other}: 1); a host belongs to one split"
        " (ARCHITECTURE §16.1), so nothing was fetched"
    )
    assert server.requests == []
    assert await _pages(env, split) == []


async def test_a_host_already_in_the_same_split_is_captured_again(
    env: Env, server: Server, private_database_url: str, fetch_result: Callable[..., FetchResult]
) -> None:
    await _seed(env, "fresh", HOST, fetch_result)
    server.routes |= {"/robots.txt": (404, b""), "/p/1": (200, _PAGE)}

    (outcome,) = await run_capture(
        env.settings, "fresh", _requests(server, "/p/1"), None, LoopbackConnector(server.port)
    )

    assert isinstance(outcome, Captured)
    assert len(await _pages(env, "fresh")) == 2
