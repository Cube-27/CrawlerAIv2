"""Listing browser actions in a real browser (owner #52): each paging mechanism on a synthetic local page, the run's
stop reasons, its caps and the document states it keeps.

A local server on 127.0.0.1 serves the pages under `.test` hosts; nothing leaves the machine. Item and control markup
is generic: the rules read structure (links, controls, integers, document order), never words, so the pages' words are
arbitrary (C4, C9).
"""

import asyncio
import itertools
import json
import os
import re
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import IPv4Address
from urllib.parse import parse_qs, urlsplit

import pytest
from patchright.async_api import Error as PlaywrightError

from crawlerai.acquire.browser import BrowserSession, open_browser
from crawlerai.acquire.browser_tab import fetch_listing
from crawlerai.acquire.ssrf import IPAddress, SafeConnector, Target
from crawlerai.acquire.types import BrowserActions, FetchPolicy, PagedFetch
from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.crawl.paging import Caps, collect

pytestmark = pytest.mark.browser

_STYLE = "<style>li.card { height: 90px; margin: 4px; } button { padding: 8px; }</style>"
_ITEM_LINK = re.compile(rb'href="(/item/\d+)"')


def _cards(first: int, count: int, *, hidden_from: int | None = None) -> str:
    return "".join(
        f'<li class="card"{" hidden" if hidden_from is not None and i >= hidden_from else ""}>'
        f'<a href="/item/{i}">Thing {i}</a><p>Words about thing {i} for the card.</p></li>'
        for i in range(first, first + count)
    )


def _page(body: str, head: str = "") -> bytes:
    return f"<!doctype html><html><head>{_STYLE}{head}</head><body><main>{body}</main></body></html>".encode()


def _numbered(path: str, query: dict[str, list[str]]) -> bytes:
    """Server-rendered numbered pages `/num/N`, 10 items each, 5 pages, with integer links."""
    n = int(path.removeprefix("/num/"))
    pager = "".join(f'<a href="/num/{p}">{p}</a> ' for p in range(1, 6) if p != n)
    return _page(f'<ul class="grid">{_cards((n - 1) * 10, 10)}</ul><div class="pages">{pager}</div>')


_LETTERS = "kmqz"


def _lettered(path: str, query: dict[str, list[str]]) -> bytes:
    """Pages named by letters (`/seg/page-k.html`), which no integer link rule reads, under a pager of ordinal links:
    4 pages of 10 items."""
    n = 1 + _LETTERS.index(path.removeprefix("/seg/page-").removesuffix(".html"))
    pager = "".join(f'<li><a href="/seg/page-{_LETTERS[p - 1]}.html">{p}</a></li>' for p in range(1, 5) if p != n)
    return _page(f'<ul class="grid">{_cards((n - 1) * 10, 10)}</ul><nav><ul>{pager}</ul></nav>')


def _in_segment(path: str, query: dict[str, list[str]]) -> bytes:
    """Numbered pages whose integer is inside a path segment (`/inseg/page-N.html`), with one link to the next page
    after the items and no pager: 3 pages of 10 items."""
    n = int(path.removeprefix("/inseg/page-").removesuffix(".html"))
    following = f'<p><a href="page-{n + 1}.html">Onward</a></p>' if n < 3 else ""
    return _page(f'<ul class="grid">{_cards((n - 1) * 10, 10)}</ul>{following}')


def _cursor(path: str, query: dict[str, list[str]]) -> bytes:
    """Pages chained by `rel=next` with opaque cursors: 3 pages of 10 items, the last without a next link."""
    order = ["k7f", "q2m", "z9a"]
    at = order.index(query.get("cursor", ["k7f"])[0])
    head = f'<link rel="next" href="/rel?cursor={order[at + 1]}">' if at + 1 < len(order) else ""
    return _page(f'<ul class="grid">{_cards(at * 10, 10)}</ul>', head)


# A pager of buttons without URLs: each click fetches a page of 6 items and replaces the list (the URL stays).
_AJAX = _page(
    """<ul class="grid" id="grid"></ul><div id="pager"></div><script>
async function show(n) {
  const items = await (await fetch('/api/ajax?page=' + n)).json();
  if (n > 1) await new Promise(r => setTimeout(r, 600));
  document.getElementById('grid').innerHTML = Array.from(items, i =>
    '<li class="card"><a href="/item/' + i + '">Thing ' + i + '</a><p>Words about thing ' + i + '.</p></li>').join('');
  let pager = '';
  for (let p = 1; p <= 6; p++) pager += '<button' + (p === n ? ' aria-current="page"' : '') + ' data-p="' + p + '">'
    + p + '</button>';
  document.getElementById('pager').innerHTML = pager;
  for (const b of document.querySelectorAll('#pager button')) b.onclick = () => show(Number(b.dataset.p));
}
show(1);
</script>"""
)
# A control after the list that fetches 10 more items per click, 50 in all, then disappears.
_LOAD_MORE = _page(
    """<ul class="grid" id="grid"></ul><button id="more">+</button><script>
let next = 0;
async function more() {
  const items = await (await fetch('/api/more?from=' + next)).json();
  await new Promise(r => setTimeout(r, 400));
  document.getElementById('grid').insertAdjacentHTML('beforeend', Array.from(items, i =>
    '<li class="card"><a href="/item/' + i + '">Thing ' + i + '</a><p>Words about thing ' + i + '.</p></li>').join(''));
  next += items.length;
  if (next >= 50) document.getElementById('more').remove();
}
document.getElementById('more').onclick = more;
more();
</script>"""
)
# All 60 items are in the document; 15 show, and each click shows 15 more, with no request.
_SHOW_MORE = _page(
    f"""<ul class="grid" id="grid">{_cards(0, 60, hidden_from=15)}</ul><button id="more">+</button><script>
document.getElementById('more').onclick = () => {{
  const hidden = [...document.querySelectorAll('#grid li[hidden]')].slice(0, 15);
  setTimeout(() => hidden.forEach(li => li.removeAttribute('hidden')), 300);
}};
</script>"""
)
# Infinite scroll: reaching the end loads 8 more items, 48 in all.
_SCROLL = _page(
    """<ul class="grid" id="grid"></ul><div id="end"></div><script>
let next = 0, busy = false;
async function more() {
  if (busy || next >= 48) return;
  busy = true;
  const items = await (await fetch('/api/more?from=' + next + '&size=8')).json();
  await new Promise(r => setTimeout(r, 300));
  document.getElementById('grid').insertAdjacentHTML('beforeend', Array.from(items, i =>
    '<li class="card"><a href="/item/' + i + '">Thing ' + i + '</a><p>Words about thing ' + i + '.</p></li>').join(''));
  next += items.length;
  busy = false;
}
new IntersectionObserver(entries => { if (entries[0].isIntersecting && next > 0) more(); })
  .observe(document.getElementById('end'));
more();
</script>"""
)
# A virtualised list: reaching the end loads 8 more items, 48 in all, and the document keeps only the last 16.
_VIRTUAL = _page(
    """<ul class="grid" id="grid"></ul><div id="end"></div><script>
let next = 0, busy = false;
async function more() {
  if (busy || next >= 48) return;
  busy = true;
  const items = await (await fetch('/api/more?from=' + next + '&size=8')).json();
  await new Promise(r => setTimeout(r, 300));
  const grid = document.getElementById('grid');
  grid.insertAdjacentHTML('beforeend', Array.from(items, i =>
    '<li class="card"><a href="/item/' + i + '">Thing ' + i + '</a><p>Words about thing ' + i + '.</p></li>').join(''));
  while (grid.children.length > 16) grid.firstElementChild.remove();
  next += items.length;
  busy = false;
}
new IntersectionObserver(entries => { if (entries[0].isIntersecting && next > 0) more(); })
  .observe(document.getElementById('end'));
more();
</script>"""
)
# Infinite scroll whose items hold no link: each call answers 8 rows as JSON, shown as text, 40 in all. The site's one
# link is in its header (a page linking nowhere on its site is no site page, `acquire.classify`).
_TEXT_ROWS = _page(
    """<header><a href="/elsewhere">Home</a></header><ul class="grid" id="grid"></ul><div id="end"></div><script>
let next = 0, busy = false;
async function more() {
  if (busy || next >= 40) return;
  busy = true;
  const answer = await (await fetch('/api/rows?from=' + next)).json();
  await new Promise(r => setTimeout(r, 300));
  document.getElementById('grid').insertAdjacentHTML('beforeend', Array.from(answer.items, row =>
    '<li class="card"><p>' + row.title + '</p><p>Rank ' + row.rank + '</p></li>').join(''));
  next += answer.items.length;
  busy = false;
}
new IntersectionObserver(entries => { if (entries[0].isIntersecting && next > 0) more(); })
  .observe(document.getElementById('end'));
more();
</script>"""
)
# Twelve items, a link to another document after them, and nothing that pages.
_STILL = _page(f'<ul class="grid">{_cards(0, 12)}</ul><a href="/elsewhere">Elsewhere</a>')
# A fixed layer over the whole viewport takes every click.
_OVERLAY = _page(
    f'<ul class="grid">{_cards(0, 12)}</ul><button id="more">+</button>'
    '<div style="position: fixed; inset: 0; background: white; z-index: 10">Layer</div>'
)
_ROUTES: dict[str, bytes] = {
    "/ajax": _AJAX,
    "/load-more": _LOAD_MORE,
    "/show-more": _SHOW_MORE,
    "/scroll": _SCROLL,
    "/virtual": _VIRTUAL,
    "/text-rows": _TEXT_ROWS,
    "/still": _STILL,
    "/elsewhere": _page("<p>Another document.</p>"),
    "/overlay": _OVERLAY,
}


def _api(path: str, query: dict[str, list[str]]) -> bytes:
    if path == "/api/ajax":
        page = int(query["page"][0])
        return json.dumps(list(range((page - 1) * 6, page * 6))).encode()
    if path == "/api/rows":
        start = int(query["from"][0])
        rows = [{"title": f"Entry number {i} of the list", "rank": i} for i in range(start, min(start + 8, 40))]
        return json.dumps({"items": rows}).encode()
    start, size = int(query["from"][0]), int(query.get("size", ["10"])[0])
    return json.dumps(list(range(start, min(start + size, 50)))).encode()


@dataclass
class Server:
    port: int
    requests: list[str] = field(default_factory=list)

    def url(self, path: str) -> str:
        return f"http://shop.example.test:{self.port}{path}"


@pytest.fixture(scope="module")
def server() -> Iterator[Server]:
    state: list[Server] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            parts = urlsplit(self.path)
            state[0].requests.append(self.path)
            query = parse_qs(parts.query)
            status, kind, body = 200, "text/html; charset=utf-8", b""
            if parts.path.startswith("/num/"):
                body = _numbered(parts.path, query)
            elif parts.path.startswith("/seg/"):
                body = _lettered(parts.path, query)
            elif parts.path.startswith("/inseg/"):
                body = _in_segment(parts.path, query)
            elif parts.path == "/rel":
                body = _cursor(parts.path, query)
            elif parts.path.startswith("/api/"):
                kind, body = "application/json", _api(parts.path, query)
            elif parts.path in _ROUTES:
                body = _ROUTES[parts.path]
            else:
                status, body = 404, b"<html><body>not here</body></html>"
            self.send_response(status)
            self.send_header("Content-Type", kind)
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


class _Local(SafeConnector):
    """Admits `.test` hosts at the server's port, pinned to 127.0.0.1; every other name resolves to nothing, so the
    real guard refuses it (the browser's own background requests among them)."""

    def __init__(self, port: int) -> None:
        async def resolve(host: str) -> list[IPAddress]:
            raise OSError("no such host")

        super().__init__(resolve)
        self._port = port

    async def check(self, url: str) -> Target:
        parts = urlsplit(url)
        if (parts.hostname or "").endswith(".test") and parts.port == self._port:
            return Target(url=url, host=parts.hostname or "", port=self._port, ip=IPv4Address("127.0.0.1"))
        return await super().check(url)


@dataclass
class Browser:
    runner: asyncio.Runner
    session: BrowserSession
    server: Server
    gated: list[str | None] = field(default_factory=list)

    def run(self, path: str, request: BrowserActions, caps: Caps | None = None, refuse: str = "") -> PagedFetch:
        self.gated.clear()

        async def gate(url: str | None) -> bool:
            self.gated.append(url)
            return not (url and refuse and refuse in url)

        drive = partial(collect, request=request, gate=gate, deadline=time.monotonic() + 90, caps=caps or Caps())
        return self.runner.run(
            fetch_listing(
                self.server.url(path),
                FetchPolicy(browser_timeout_s=15, page_kind="listing"),
                drive,
                session=self.session,
                engine_version=ENGINE_VERSION,
                connector=_Local(self.server.port),
            )
        )


@pytest.fixture(scope="module")
def browser(server: Server) -> Iterator[Browser]:
    with pytest.MonkeyPatch.context() as env, asyncio.Runner() as runner:
        env.setenv("PLAYWRIGHT_DISABLE_FORCED_CHROMIUM_PROXIED_LOOPBACK", "1")
        opened = open_browser()
        try:
            session = runner.run(opened.__aenter__())
        except PlaywrightError as e:
            if os.environ.get("CI") or "Executable doesn't exist" not in e.message:
                raise
            pytest.skip("Chromium is not installed: run `uv run patchright install --no-shell chromium`")
        try:
            yield Browser(runner, session, server)
            assert session.browser.contexts == []
        finally:
            runner.run(opened.__aexit__(None, None, None))


def _items(fetched: PagedFetch) -> list[set[bytes]]:
    """The item links each kept page holds."""
    return [set(_ITEM_LINK.findall(page.bundle.body)) for page in fetched.pages]


def _summary(fetched: PagedFetch) -> tuple[object, ...]:
    report = fetched.report
    assert report is not None
    return report.mechanism, report.stop, report.pages, report.items


def test_numbered_links_are_followed_until_the_target_and_each_page_is_kept(browser: Browser) -> None:
    fetched = browser.run("/num/1", BrowserActions(records=25))

    # 10 per page: the third page passes the target of 25, and the run stops there (a soft target).
    assert _summary(fetched) == ("pagination", "records", 3, 30)
    assert [len(links) for links in _items(fetched)] == [10, 10, 10]
    assert [page.bundle.manifest.final_url for page in fetched.pages] == [
        browser.server.url(f"/num/{n}") for n in (1, 2, 3)
    ]
    # Each navigation asked the gate with its URL first (robots.txt, the site's rate).
    assert browser.gated == [browser.server.url("/num/2"), browser.server.url("/num/3")]


def test_a_pager_of_ordinal_links_in_nav_is_clicked_page_by_page_to_its_end(browser: Browser) -> None:
    fetched = browser.run("/seg/page-k.html", BrowserActions(records=100))

    assert _summary(fetched) == ("pagination", "end", 4, 40)
    # Three clicks on hyperlinks, each gated by its target first; page 4 links to no page 5.
    pages = [browser.server.url(f"/seg/page-{letter}.html") for letter in _LETTERS[1:]]
    assert browser.gated == pages
    # Each kept state is recorded under the URL it was asked for, not the listing's first one.
    assert [page.bundle.manifest.url for page in fetched.pages] == [browser.server.url("/seg/page-k.html"), *pages]


def test_an_integer_inside_a_path_segment_is_followed_as_the_next_page(browser: Browser) -> None:
    fetched = browser.run("/inseg/page-1.html", BrowserActions(records=100))

    assert _summary(fetched) == ("pagination", "end", 3, 30)
    pages = [browser.server.url(f"/inseg/page-{n}.html") for n in (2, 3)]
    assert browser.gated == pages
    assert [page.bundle.manifest.final_url for page in fetched.pages] == [
        browser.server.url("/inseg/page-1.html"),
        *pages,
    ]


def test_a_pager_link_the_gate_refuses_is_not_clicked(browser: Browser) -> None:
    fetched = browser.run("/seg/page-k.html", BrowserActions(records=100), refuse="page-m")

    assert _summary(fetched) == (None, "not_admitted", 1, 10)
    assert [page.bundle.manifest.final_url for page in fetched.pages] == [browser.server.url("/seg/page-k.html")]


def test_rel_next_with_opaque_cursors_runs_to_the_end_of_the_list(browser: Browser) -> None:
    fetched = browser.run("/rel?cursor=k7f", BrowserActions(records=100, hint="next"))

    assert _summary(fetched) == ("next", "end", 3, 30)
    assert all(page.block_class == "ok" for page in fetched.pages)


def test_robots_refusing_the_next_page_stops_the_run_with_the_first_page_kept(browser: Browser) -> None:
    fetched = browser.run("/rel?cursor=k7f", BrowserActions(hint="next"), refuse="q2m")

    # Nothing grew the list, so no mechanism is reported.
    assert _summary(fetched) == (None, "not_admitted", 1, 10)


def test_an_ajax_pager_is_clicked_by_its_integers_and_every_page_is_kept(browser: Browser) -> None:
    fetched = browser.run("/ajax", BrowserActions(records=20))

    assert _summary(fetched) == ("pagination", "records", 4, 24)
    assert [len(links) for links in _items(fetched)] == [6, 6, 6, 6]
    assert len(set().union(*_items(fetched))) == 24


def test_each_kept_page_holds_the_calls_since_the_last_with_the_browser_action_they_followed(browser: Browser) -> None:
    fetched = browser.run("/ajax", BrowserActions(records=20))

    calls = [
        [(urlsplit(e.url).query, e.resource_type, e.action) for e in page.bundle.manifest.network_bodies]
        for page in fetched.pages
    ]
    # The page's own load fetched the first page before any action; each click fetched the next one.
    assert [[(query, kind) for query, kind, _ in page] for page in calls] == [
        [(f"page={n}", "fetch")] for n in range(1, 5)
    ]
    actions = [page[0][2] or 0 for page in calls]
    assert calls[0][0][2] == 0
    assert all(earlier < later for earlier, later in itertools.pairwise(actions))


def test_a_load_more_control_is_found_without_a_hint_and_one_grown_page_is_kept(browser: Browser) -> None:
    fetched = browser.run("/load-more", BrowserActions(records=100))

    # Next pages and scroll find nothing; the control after the list adds 10 per click until it is gone.
    assert _summary(fetched) == ("load_more", "end", 1, 50)
    assert len(_items(fetched)[0]) == 50


def test_show_more_reveals_items_already_in_the_document_and_overshoots_the_target(browser: Browser) -> None:
    fetched = browser.run("/show-more", BrowserActions(records=40, hint="show_more"))

    report = fetched.report
    assert report is not None
    assert (report.mechanism, report.stop, report.pages, report.items, report.actions) == (
        "show_more",
        "records",
        1,
        45,
        2,
    )


def test_infinite_scroll_grows_one_document_to_the_target(browser: Browser) -> None:
    fetched = browser.run("/scroll", BrowserActions(records=30, hint="scroll"))

    report = fetched.report
    assert report is not None
    assert (report.mechanism, report.stop, report.pages) == ("scroll", "records", 1)
    assert 30 <= report.items <= 40
    assert len(_items(fetched)[0]) == report.items


def test_a_virtualised_list_keeps_a_state_per_batch_so_every_item_is_kept(browser: Browser) -> None:
    fetched = browser.run("/virtual", BrowserActions(records=100, hint="scroll"))

    report = fetched.report
    assert report is not None
    assert (report.mechanism, report.stop, report.items) == ("scroll", "end", 48)
    kept = set().union(*_items(fetched))
    assert kept == {f"/item/{i}".encode() for i in range(48)}
    assert report.pages == len(fetched.pages) > 1


def test_a_scroll_listing_whose_items_hold_no_link_loads_by_its_call_rows(browser: Browser) -> None:
    fetched = browser.run("/text-rows", BrowserActions(records=100))

    assert _summary(fetched) == ("scroll", "end", 1, 40)
    # The one kept state holds every call that loaded its rows.
    assert len(fetched.pages[0].bundle.network) == 5


def test_a_listing_without_paging_stops_with_no_mechanism_after_undoing_a_click_that_left(browser: Browser) -> None:
    fetched = browser.run("/still", BrowserActions())

    assert _summary(fetched) == (None, "no_mechanism", 1, 12)
    assert fetched.pages[0].bundle.manifest.final_url == browser.server.url("/still")


def test_the_action_cap_ends_the_run(browser: Browser) -> None:
    fetched = browser.run("/load-more", BrowserActions(hint="load_more"), caps=Caps(actions=2))

    report = fetched.report
    assert report is not None
    assert (report.stop, report.actions, report.items) == ("action_cap", 2, 30)


def test_a_layer_that_takes_the_click_is_reported_not_worked_around(browser: Browser) -> None:
    fetched = browser.run("/overlay", BrowserActions(hint="load_more"))

    assert _summary(fetched) == (None, "click_intercepted", 1, 12)
