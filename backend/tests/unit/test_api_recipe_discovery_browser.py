"""API discovery end to end (SPEC-09 §6): a local server serves an HTML shell whose script loads a JSON endpoint keyed
by a path parameter of the page URL; the browser captures the bodies, discovery finds the endpoint and binding
templates it from the page URL.

Synthetic `.test` hosts on 127.0.0.1; no live network.
"""

import asyncio
import json
import os
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import IPv4Address
from urllib.parse import urlsplit

import pytest
from patchright.async_api import Error as PlaywrightError

from crawlerai.acquire.browser import fetch_browser, open_browser
from crawlerai.acquire.ssrf import IPAddress, SafeConnector, Target
from crawlerai.acquire.types import FetchPolicy
from crawlerai.config_ir.api_recipe.binding import Sample, bind
from crawlerai.config_ir.api_recipe.discovery import DiscoverySample, discover
from crawlerai.config_ir.api_recipe.model import RequestSpec
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from crawlerai.storage.capture_bundle import CaptureBundle

pytestmark = pytest.mark.browser

SCHEMA = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="synthetic",
    page_kind="detail",
    fields={
        "title": FieldSpec(type=FieldType.TEXT, description="d", required=True),
        "price": FieldSpec(type=FieldType.MONEY, description="d", required=True),
    },
)
PRODUCTS = {"desk-lamp": ("Desk Lamp", 19.5), "oak-chair": ("Oak Chair", 120)}
# The shell renders the product from the endpoint named by the page path's second segment.
SHELL = b"""<html><body><main id="root">Loading</main><script>
const slug = location.pathname.split('/')[2];
fetch('/api/v1/products/' + slug + '?view=full').then(r => r.json()).then(d => {
  const item = d['item'], price = item['price'];
  document.getElementById('root').innerHTML =
    '<h1>' + item['name'] + '</h1><p>' + price['value'] + ' ' + price['currency'] + '</p>';
});
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        segments = urlsplit(self.path).path.split("/")
        if segments[1] == "p":
            self._send("text/html; charset=utf-8", SHELL)
        else:
            name, value = PRODUCTS[segments[4]]
            item = {"sku": segments[4], "name": name, "price": {"value": value, "currency": "EUR"}}
            self._send("application/json", json.dumps({"item": item}).encode())

    def _send(self, content_type: str, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


class LocalConnector(SafeConnector):
    """Admits `.test` hosts at the server's port, pinned to 127.0.0.1; anything else goes through the real guard,
    which resolves nothing."""

    def __init__(self, port: int) -> None:
        async def resolve(_host: str) -> list[IPAddress]:
            raise OSError("no such host")

        super().__init__(resolve)
        self._port = port

    async def check(self, url: str) -> Target:
        parts = urlsplit(url)
        if (parts.hostname or "").endswith(".test") and parts.port == self._port:
            return Target(url=url, host=parts.hostname or "", port=self._port, ip=IPv4Address("127.0.0.1"))
        return await super().check(url)


@pytest.fixture(scope="module")
def port() -> Iterator[int]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


async def _capture(urls: list[str], port: int) -> list[CaptureBundle]:
    async with open_browser() as session:
        results = [
            await fetch_browser(
                url,
                FetchPolicy(browser_timeout_s=10),
                session=session,
                engine_version="test",
                connector=LocalConnector(port),
            )
            for url in urls
        ]
    return [result.bundle for result in results]


def _captures(urls: list[str], port: int) -> list[CaptureBundle]:
    with pytest.MonkeyPatch.context() as env:
        # Read by the Playwright driver when it starts: loopback goes through the guard like any other address.
        env.setenv("PLAYWRIGHT_DISABLE_FORCED_CHROMIUM_PROXIED_LOOPBACK", "1")
        try:
            return asyncio.run(_capture(urls, port))
        except PlaywrightError as e:
            if os.environ.get("CI") or "Executable doesn't exist" not in e.message:
                raise
            pytest.skip("Chromium is not installed: run `uv run patchright install chromium`")


def test_discovery_finds_the_endpoint_of_browser_captures_and_binding_templates_it(port: int) -> None:
    site = f"http://shop.example.test:{port}"
    urls = [f"{site}/p/{slug}" for slug in PRODUCTS]
    bundles = _captures(urls, port)
    samples = [
        DiscoverySample(
            bundle=bundle,
            values={"title": name, "price": {"amount": str(value), "currency": "EUR"}},
            ctx=Context(captured_at=datetime.now(UTC), base_url=url, page_url=url),
        )
        for bundle, url, (name, value) in zip(bundles, urls, PRODUCTS.values(), strict=True)
    ]

    best, *others = discover(samples, SCHEMA)

    assert others == []
    assert [request.url for request in best.requests] == [
        f"{site}/api/v1/products/{slug}?view=full" for slug in PRODUCTS
    ]
    assert best.map == {
        "title": "$['item']['name']",
        "price": "$['item']['price']['value']+$['item']['price']['currency']",
    }
    spec = bind([Sample(url, request) for url, request in zip(urls, best.requests, strict=True)])
    assert spec == RequestSpec(
        method="GET", url=f"{site}/api/v1/products/{{p1}}?view=full", params_from_url={"p1": "path:1"}
    )
