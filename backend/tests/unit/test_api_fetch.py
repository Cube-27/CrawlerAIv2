"""JSON fetch: the HTTP rung's client, manual redirects through the SSRF
guard, the request a page's own `fetch()` would send, caps, the outcome and the manifest.

The guard, redirect and cookie rules run against a stand-in network (`tests.stand_in`) with a stub resolver; no DNS.
What the network does (the pinned address, the headers on the wire, caps, decoding, time) is shown against a local
server on 127.0.0.1 (`tests.local_server`).
"""

import asyncio
import gzip
from collections.abc import Callable, Iterator
from ipaddress import ip_address

import httpx
import pytest

from crawlerai.acquire.api import JsonRequest, fetch_json
from crawlerai.acquire.ssrf import IPAddress, SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.storage.capture_bundle import decode, encode
from tests.local_server import LoopbackConnector, Reply, Server, serving
from tests.stand_in import IMPERSONATE, handler_transport

PAGE = "https://jobs.example.com/board"
API = "https://api.example.com/v1/board/jobs"
_DNS = {"api.example.com": "93.184.215.14", "cdn.example.com": "93.184.215.15", "internal.example.com": "10.0.0.1"}
_JSON = b'{"jobs": [{"id": 1, "title": "Synthetic"}]}'

Handler = Callable[[httpx.Request], httpx.Response]


def connector(dns: dict[str, str]) -> SafeConnector:
    async def resolve(host: str) -> list[IPAddress]:
        if host not in dns:
            raise OSError("no such host")
        return [ip_address(dns[host])]

    return SafeConnector(resolve)


def fetch(
    handler: Handler,
    request: JsonRequest | None = None,
    policy: FetchPolicy | None = None,
    dns: dict[str, str] = _DNS,
) -> FetchResult:
    return asyncio.run(
        fetch_json(
            request or JsonRequest(url=API, page_url=PAGE),
            policy or FetchPolicy(),
            engine_version="test",
            impersonate=IMPERSONATE,
            connector=connector(dns),
            transport=handler_transport(handler),
        )
    )


def recording(handler: Handler) -> tuple[Handler, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return record, seen


def outcome(result: FetchResult) -> tuple[int, str, str | None]:
    (attempt,) = result.attempts
    return result.bundle.manifest.status_code, result.block_class, attempt.error


def json_reply(body: bytes = _JSON, status: int = 200) -> Handler:
    return lambda _request: httpx.Response(status, headers={"Content-Type": "application/json"}, content=body)


def test_a_json_response_is_an_ok_api_capture_recorded_under_the_page() -> None:
    result = fetch(json_reply())

    manifest = result.bundle.manifest
    assert outcome(result) == (200, "ok", None)
    assert (manifest.method, manifest.url, manifest.final_url) == ("api", PAGE, API)
    assert result.bundle.body == _JSON
    assert result.attempts[0].challenge is None
    assert decode(encode(result.bundle)) == result.bundle


def test_a_redirect_to_a_private_address_is_rejected() -> None:
    result = fetch(lambda _r: httpx.Response(302, headers={"Location": "http://internal.example.com/"}))

    assert outcome(result) == (302, "error", "ssrf_rejected: private_address")


def test_a_private_first_url_is_rejected_before_any_request() -> None:
    handler, seen = recording(json_reply())

    result = fetch(handler, JsonRequest(url="http://internal.example.com/jobs", page_url=PAGE))

    assert outcome(result) == (0, "error", "ssrf_rejected: private_address")
    assert seen == []


# --- the request a page's `fetch()` sends -------------------------------------------------------------------


# --- challenge labels ---------------------------------------------------------------------------------------


# --- cookies stay inside one fetch -----------------------------------------------------------------------


# --- the network: a local server ---------------------------------------------------------------------------------


@pytest.fixture
def server() -> Iterator[Server]:
    yield from serving()


def fetch_local(server: Server, path: str, policy: FetchPolicy | None = None, page: str = PAGE) -> FetchResult:
    return asyncio.run(
        fetch_json(
            JsonRequest(url=server.url(path, host="api.example.test"), page_url=page),
            policy or FetchPolicy(),
            engine_version="test",
            impersonate=IMPERSONATE,
            connector=LoopbackConnector(server.port, {}),
        )
    )


def json_route(body: bytes = _JSON, *headers: tuple[str, str], delay_s: float = 0.0) -> Reply:
    return Reply(200, (("Content-Type", "application/json"), *headers), body, delay_s)


def test_inv30_a_body_over_the_cap_is_an_error_without_a_body(server: Server) -> None:
    server.route("/jobs", json_route(b"[" + b"1," * 600 + b"1]"))

    result = fetch_local(server, "/jobs", FetchPolicy(max_body_bytes=1000))

    assert outcome(result) == (200, "error", "body_cap")
    assert result.bundle.body == b""


def test_inv30_a_compression_bomb_stops_at_the_decompressed_cap_without_a_body(server: Server) -> None:
    bomb = gzip.compress(b"[" + b"0," * 500_000 + b"0]")
    server.route("/jobs", json_route(bomb, ("Content-Encoding", "gzip")))

    result = fetch_local(server, "/jobs", FetchPolicy(max_decompressed_bytes=100_000))

    assert len(bomb) < 100_000
    assert outcome(result) == (200, "error", "body_cap")
    assert result.bundle.body == b""
