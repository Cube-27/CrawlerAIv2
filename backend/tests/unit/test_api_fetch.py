"""JSON fetch over httpx (SPEC-02 §4.1, §4.5, §4.7): the checked address, manual redirects through the SSRF guard,
caps, the outcome and the manifest.

An `httpx.MockTransport` stands in for the network and the guard resolves through a stub; no DNS. One test talks to
a local server on 127.0.0.1, to show httpx's own transport connects to the pinned address under the host's name.
"""

import asyncio
import gzip
import json
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import IPv4Address, ip_address

import httpx
import pytest

from crawlerai.acquire.api import JsonRequest, fetch_json
from crawlerai.acquire.ssrf import IPAddress, SafeConnector, Target
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.storage.capture_bundle import decode, encode

PAGE = "https://jobs.example.com/board"
API = "https://api.example.com/v1/board/jobs"
_DNS = {"api.example.com": "93.184.215.14", "cdn.example.com": "93.184.215.15", "internal.example.com": "10.0.0.1"}
_JSON = b'{"jobs": [{"id": 1, "title": "Synthetic"}]}'

Handler = Callable[[httpx.Request], httpx.Response]


def connector() -> SafeConnector:
    async def resolve(host: str) -> list[IPAddress]:
        if host not in _DNS:
            raise OSError("no such host")
        return [ip_address(_DNS[host])]

    return SafeConnector(resolve)


def fetch(handler: Handler, policy: FetchPolicy | None = None, url: str = API) -> FetchResult:
    return asyncio.run(
        fetch_json(
            JsonRequest(url=url, page_url=PAGE),
            policy or FetchPolicy(),
            engine_version="test",
            connector=connector(),
            transport=httpx.MockTransport(handler),
        )
    )


def outcome(result: FetchResult) -> tuple[int, str, str | None]:
    (attempt,) = result.attempts
    return result.bundle.manifest.status_code, result.block_class, attempt.error


def streamed(status: int, body: bytes, headers: dict[str, str]) -> httpx.Response:
    """A response whose body arrives as a stream, as from the network (a `content=` body is decoded up front)."""
    return httpx.Response(status, headers=headers, stream=httpx.ByteStream(body))


def json_reply(body: bytes = _JSON, status: int = 200) -> Handler:
    return lambda _request: streamed(status, body, {"Content-Type": "application/json"})


def test_the_request_goes_to_the_checked_address_under_its_host_name() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return json_reply()(request)

    fetch(handler)

    (request,) = seen
    assert (request.url.host, request.headers["Host"], request.extensions["sni_hostname"]) == (
        "93.184.215.14",
        "api.example.com",
        "api.example.com",
    )
    assert request.headers["Accept"] == "application/json"


def test_a_json_response_is_an_ok_api_capture_recorded_under_the_page() -> None:
    result = fetch(json_reply())

    manifest = result.bundle.manifest
    assert outcome(result) == (200, "ok", None)
    assert (manifest.method, manifest.url, manifest.final_url) == ("api", PAGE, API)
    assert result.bundle.body == _JSON
    assert decode(encode(result.bundle)) == result.bundle


@pytest.mark.parametrize(
    ("status", "expected"),
    [(404, "not_found"), (410, "not_found"), (403, "blocked"), (429, "blocked"), (500, "error"), (400, "error")],
)
def test_a_status_classifies_as_in_the_http_fetch(status: int, expected: str) -> None:
    assert outcome(fetch(json_reply(b'{"error": "x"}', status))) == (status, expected, None)


def test_a_success_status_without_json_is_a_decode_error_with_no_body() -> None:
    result = fetch(lambda _r: httpx.Response(200, headers={"Content-Type": "text/html"}, content=b"<html></html>"))

    assert outcome(result) == (200, "error", "decode_error")
    assert result.bundle.body == b""


def test_a_redirect_is_followed_through_the_guard() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["Host"] == "api.example.com":
            return httpx.Response(302, headers={"Location": "https://cdn.example.com/jobs.json"})
        return json_reply()(request)

    result = fetch(handler)

    assert outcome(result) == (200, "ok", None)
    assert result.bundle.manifest.final_url == "https://cdn.example.com/jobs.json"


def test_a_redirect_to_a_private_address_is_rejected() -> None:
    result = fetch(lambda _r: httpx.Response(302, headers={"Location": "http://internal.example.com/"}))

    assert outcome(result) == (302, "error", "ssrf_rejected: private_address")


def test_a_private_first_url_is_rejected_before_any_request() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return json_reply()(request)

    result = fetch(handler, url="http://internal.example.com/jobs")

    assert outcome(result) == (0, "error", "ssrf_rejected: private_address")
    assert seen == []


def test_more_than_five_redirects_end_the_fetch() -> None:
    result = fetch(lambda _r: httpx.Response(301, headers={"Location": "/again"}))

    assert outcome(result) == (301, "error", "too_many_redirects")


def test_a_body_over_the_compressed_cap_is_an_error() -> None:
    result = fetch(json_reply(b"[" + b"1," * 600 + b"1]"), FetchPolicy(max_body_bytes=1000))

    assert outcome(result) == (200, "error", "body_cap")


def test_a_compression_bomb_stops_at_the_decompressed_cap() -> None:
    bomb = gzip.compress(b"[" + b"0," * 500_000 + b"0]")

    def handler(_request: httpx.Request) -> httpx.Response:
        return streamed(200, bomb, {"Content-Encoding": "gzip"})

    result = fetch(handler, FetchPolicy(max_decompressed_bytes=100_000))

    assert len(bomb) < 100_000
    assert outcome(result) == (200, "error", "body_cap")


def test_a_corrupt_content_encoding_is_a_decode_error() -> None:
    result = fetch(lambda _r: streamed(200, b"not gzip", {"Content-Encoding": "gzip"}))

    assert outcome(result) == (200, "error", "decode_error")


def test_a_network_failure_names_its_kind_and_not_the_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}", request=request)

    assert outcome(fetch(handler)) == (0, "error", "network_error: ConnectError")


def test_a_body_slower_than_the_time_budget_is_a_timeout() -> None:
    async def slow() -> AsyncIterator[bytes]:
        yield b"["
        await asyncio.sleep(5)
        yield b"]"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=slow())

    assert outcome(fetch(handler, FetchPolicy(timeout_s=0.2))) == (0, "error", "timeout")


def test_cookies_are_not_recorded() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Set-Cookie": "session=secret"}, content=json.dumps([]).encode())

    result = fetch(handler)

    assert [name for name, _ in result.bundle.manifest.headers.response if name.lower() == "set-cookie"] == []


@pytest.fixture
def echo_port() -> Iterator[int]:
    """A local server answering every GET with the Host header it received, as JSON."""

    class Echo(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = json.dumps({"host": self.headers.get("Host")}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Echo)
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


class PinToLoopback(SafeConnector):
    """Pins every URL to 127.0.0.1, which the real guard would refuse: the test server is local."""

    async def check(self, url: str) -> Target:
        parts = httpx.URL(url)
        return Target(url=url, host=parts.host, port=parts.port or 80, ip=IPv4Address("127.0.0.1"))


def test_the_real_transport_connects_to_the_pinned_address_under_the_host_name(echo_port: int) -> None:
    url = f"http://api.example.test:{echo_port}/jobs"
    request = JsonRequest(url=url, page_url=PAGE)

    result = asyncio.run(fetch_json(request, FetchPolicy(), engine_version="test", connector=PinToLoopback()))

    assert outcome(result) == (200, "ok", None)
    assert json.loads(result.bundle.body) == {"host": f"api.example.test:{echo_port}"}
