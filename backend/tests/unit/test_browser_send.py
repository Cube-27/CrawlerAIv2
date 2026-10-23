"""A custom recipe's call sent by the browser from a warm page (`acquire.browser_send`), in a real browser: a synthetic
local page whose `fetch` hook adds a header its endpoint requires, served under a `.test` host on 127.0.0.1
(`tests.local_server`); nothing leaves the machine.
"""

import asyncio
import os
from collections.abc import Iterator
from dataclasses import dataclass
from functools import partial

import pytest
from patchright.async_api import Error as PlaywrightError

from crawlerai.acquire.api import JsonRequest
from crawlerai.acquire.browser_send import send_in_page
from crawlerai.acquire.browser_session import BrowserSession, open_browser
from crawlerai.acquire.session import SiteSessions
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.core.engine_version import ENGINE_VERSION
from tests.local_server import LoopbackConnector, Reply, Server, serving

pytestmark = pytest.mark.browser

_HTML = (("Content-Type", "text/html; charset=utf-8"),)
_JSON = (("Content-Type", "application/json"),)
# The page's script wraps `fetch`, as an application's request interceptor does: every call carries its header.
_HOOKED = (
    b"<!doctype html><html><head><title>t</title><script>const sent = window.fetch;"
    b"window.fetch = (url, init = {}) => sent(url, {...init, headers: {...init.headers, 'x-page-token': 'k7'}});"
    b"</script></head><body><main>item</main></body></html>"
)
_PLAIN = b"<!doctype html><html><head><title>t</title></head><body><main>item</main></body></html>"


@dataclass
class Sender:
    runner: asyncio.Runner
    session: BrowserSession
    server: Server
    connector: LoopbackConnector

    def send(self, page: str) -> FetchResult:
        policy = FetchPolicy(browser_timeout_s=20)
        request = JsonRequest(self.server.url("/api/item?id=1"), self.server.url(page))
        sending = send_in_page(
            request,
            policy,
            self.server.url(page),
            session=self.session,
            engine_version=ENGINE_VERSION,
            connector=self.connector,
            scope=SiteSessions().scope_for(policy),
        )
        return self.runner.run(sending)


def _endpoint(server: Server, _host: str) -> Reply:
    headers = dict((name.lower(), value) for name, value in server.requests[-1][1])
    if headers.get("x-page-token") != "k7":
        return Reply(403, _JSON, b'{"error": "refused"}')
    return Reply(200, _JSON, b'{"name": "item one", "price": 12}')


@pytest.fixture
def server() -> Iterator[Server]:
    for srv in serving():
        srv.route("/hooked/1", Reply(200, _HTML, _HOOKED))
        srv.route("/plain/1", Reply(200, _HTML, _PLAIN))
        srv.route("/api/item?id=1", partial(_endpoint, srv))
        yield srv


@pytest.fixture
def sender(server: Server) -> Iterator[Sender]:
    with pytest.MonkeyPatch.context() as env, asyncio.Runner() as runner:
        env.setenv("PLAYWRIGHT_DISABLE_FORCED_CHROMIUM_PROXIED_LOOPBACK", "1")
        opened = open_browser()
        try:
            browser = runner.run(opened.__aenter__())
        except PlaywrightError as e:
            if os.environ.get("CI") or "is not found at" not in e.message:
                raise
            pytest.skip("Google Chrome is not installed: run `uv run patchright install chrome`")
        try:
            yield Sender(runner, browser, server, LoopbackConnector(server.port, {}))
            assert browser.profiles.busy == 0
        finally:
            runner.run(opened.__aexit__(None, None, None))


def _loads(server: Server, path: str) -> int:
    return sum(1 for target, _ in server.requests if target.endswith(path))


def test_a_call_from_the_warm_page_carries_its_hooks_header_and_reuses_the_page(sender: Sender) -> None:
    first = sender.send("/hooked/1")
    second = sender.send("/hooked/1")

    for result in (first, second):
        assert (result.method, result.block_class, result.bundle.manifest.status_code) == ("api", "ok", 200)
        assert result.bundle.body == b'{"name": "item one", "price": 12}'
        assert result.bundle.manifest.url == sender.server.url("/hooked/1")
    assert _loads(sender.server, "/hooked/1") == 1  # the page loaded once; each call rendered nothing


def test_a_page_without_the_hook_gets_the_endpoints_refusal_with_its_status(sender: Sender) -> None:
    result = sender.send("/plain/1")

    assert result.block_class != "ok"
    assert result.bundle.manifest.status_code == 403
