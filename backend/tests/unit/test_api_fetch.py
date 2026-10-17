"""JSON fetch (SPEC-02 §4.1, §4.5, §4.7; D-1320, D-1322): the HTTP rung's client, manual redirects through the SSRF
guard, the request a page's own `fetch()` would send, caps, the outcome and the manifest.

The guard, redirect and cookie rules run against a stand-in network (`tests.stand_in`) with a stub resolver; no DNS.
What the network does (the pinned address, the headers on the wire, caps, decoding, time) is shown against a local
server on 127.0.0.1 (`tests.local_server`).
"""

import asyncio
import gzip
import json
import socket
from collections.abc import Callable, Iterator
from ipaddress import ip_address

import httpx
import pytest

from crawlerai.acquire.api import JsonRequest, fetch_json, referrer, site_relation
from crawlerai.acquire.challenge import STRUCTURAL
from crawlerai.acquire.http import fetch_http
from crawlerai.acquire.ssrf import IPAddress, SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.challenges import SIGNATURES, ChallengeSignature
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


@pytest.mark.parametrize(("status", "expected"), [(404, "not_found"), (429, "blocked"), (500, "error")])
def test_a_status_classifies_as_in_the_http_fetch(status: int, expected: str) -> None:
    assert outcome(fetch(json_reply(b'{"error": "x"}', status))) == (status, expected, None)


def test_a_success_status_without_json_is_a_decode_error_with_no_body() -> None:
    result = fetch(lambda _r: httpx.Response(200, headers={"Content-Type": "text/html"}, content=b"<html></html>"))

    assert outcome(result) == (200, "error", "decode_error")
    assert result.bundle.body == b""


def test_a_redirect_is_followed_through_the_guard() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.example.com":
            return httpx.Response(302, headers={"Location": "https://cdn.example.com/jobs.json"})
        return json_reply()(request)

    result = fetch(handler)

    assert outcome(result) == (200, "ok", None)
    assert result.bundle.manifest.final_url == "https://cdn.example.com/jobs.json"


def test_a_recipe_request_sends_its_method_body_and_headers_but_keeps_the_host() -> None:
    handler, seen = recording(json_reply())
    headers = (("Accept", "application/vnd.test+json"), ("X-Requested-With", "XMLHttpRequest"), ("Host", "a.test"))

    fetch(handler, JsonRequest(url=API, page_url=PAGE, method="POST", headers=headers, body='{"id": "1"}'))

    (sent,) = seen
    assert (sent.method, sent.content) == ("POST", b'{"id": "1"}')
    assert [sent.headers[name] for name in ("Accept", "X-Requested-With", "Host")] == [
        "application/vnd.test+json",
        "XMLHttpRequest",
        "api.example.com",
    ]


def test_a_body_without_a_content_type_is_sent_as_fetch_sends_a_string() -> None:
    handler, seen = recording(json_reply())

    fetch(handler, JsonRequest(url=API, page_url=PAGE, method="POST", body="q=1"))

    # Fetch §5.2 "extract a body": a string body's type.
    assert seen[0].headers["Content-Type"] == "text/plain;charset=UTF-8"


@pytest.mark.parametrize(
    ("status", "method", "body", "content_type"),
    # WHATWG Fetch §4.4 (HTTP-redirect fetch) step 12: 303, and 301/302 after a POST, go on as a GET without a
    # body or its headers; 307 and 308 repeat the request as it was.
    [(302, "GET", b"", None), (303, "GET", b"", None), (307, "POST", b"{}", "application/json")],
)
def test_a_redirected_post_follows_the_fetch_standard(
    status: int, method: str, body: bytes, content_type: str | None
) -> None:
    def route(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/board/jobs":
            return httpx.Response(status, headers={"Location": "/v1/board/all"})
        return json_reply()(request)

    handler, seen = recording(route)
    headers = (("Content-Type", "application/json"),)

    fetch(handler, JsonRequest(url=API, page_url=PAGE, method="POST", headers=headers, body="{}"))

    assert (seen[1].method, seen[1].content, seen[1].headers.get("Content-Type")) == (method, body, content_type)


def test_a_redirect_to_a_private_address_is_rejected() -> None:
    result = fetch(lambda _r: httpx.Response(302, headers={"Location": "http://internal.example.com/"}))

    assert outcome(result) == (302, "error", "ssrf_rejected: private_address")


def test_a_private_first_url_is_rejected_before_any_request() -> None:
    handler, seen = recording(json_reply())

    result = fetch(handler, JsonRequest(url="http://internal.example.com/jobs", page_url=PAGE))

    assert outcome(result) == (0, "error", "ssrf_rejected: private_address")
    assert seen == []


def test_more_than_five_redirects_end_the_fetch() -> None:
    result = fetch(lambda _r: httpx.Response(301, headers={"Location": "/again"}))

    assert outcome(result) == (301, "error", "too_many_redirects")


def test_cookies_are_not_recorded() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        headers = {"Set-Cookie": "session=secret", "X-Trace": "t1"}
        return httpx.Response(200, headers=headers, content=json.dumps([]).encode())

    result = fetch(handler)

    recorded = {name.lower(): value for name, value in result.bundle.manifest.headers.response}
    assert recorded["x-trace"] == "t1"
    assert "set-cookie" not in recorded


# --- the request a page's `fetch()` sends (D-1322) -------------------------------------------------------------------


def test_a_cross_site_call_carries_the_fetch_metadata_referrer_and_origin_of_a_cors_request() -> None:
    handler, seen = recording(json_reply())
    dns = {**_DNS, "api.example.net": "93.184.215.18"}

    fetch(handler, JsonRequest(url="https://api.example.net/jobs", page_url=f"{PAGE}?x=1#top"), dns=dns)

    headers = seen[0].headers
    assert [headers.get(name) for name in ("Sec-Fetch-Site", "Sec-Fetch-Mode", "Sec-Fetch-Dest")] == [
        "cross-site",
        "cors",
        "empty",
    ]
    assert (headers.get("Referer"), headers.get("Origin")) == ("https://jobs.example.com/", "https://jobs.example.com")
    assert "Sec-Fetch-User" not in headers
    assert "Upgrade-Insecure-Requests" not in headers


def test_a_same_origin_get_names_the_page_and_sends_no_origin() -> None:
    handler, seen = recording(json_reply())
    dns = {**_DNS, "jobs.example.com": "93.184.215.16"}
    page = "https://u:p@jobs.example.com/b?x=1#top"

    fetch(handler, JsonRequest(url="https://jobs.example.com/api/jobs", page_url=page), dns=dns)

    headers = seen[0].headers
    assert headers["Sec-Fetch-Site"] == "same-origin"
    assert headers["Referer"] == "https://jobs.example.com/b?x=1"  # Referrer Policy §8.4: no fragment, no credentials
    assert "Origin" not in headers


def test_a_redirect_to_another_site_makes_the_chain_cross_site() -> None:
    def route(request: httpx.Request) -> httpx.Response:
        if request.url.host == "jobs.example.com":
            return httpx.Response(302, headers={"Location": "https://cdn.example.net/jobs.json"})
        return json_reply()(request)

    handler, seen = recording(route)
    dns = {**_DNS, "jobs.example.com": "93.184.215.16", "cdn.example.net": "93.184.215.17"}

    fetch(handler, JsonRequest(url="https://jobs.example.com/api", page_url=PAGE), dns=dns)

    assert [request.headers["Sec-Fetch-Site"] for request in seen] == ["same-origin", "cross-site"]
    assert seen[1].headers["Origin"] == "https://jobs.example.com"


@pytest.mark.parametrize(
    ("page", "url", "relation"),
    [
        ("https://a.example.com/p", "https://a.example.com:443/j", "same-origin"),  # RFC 6454: default port
        ("https://a.example.com/p", "https://b.example.com/j", "same-site"),
        ("https://a.example.com/p", "http://a.example.com/j", "cross-site"),  # HTML "same site" is schemeful
        ("https://a.example.com/p", "https://a.example.org/j", "cross-site"),
    ],
)
def test_the_site_relation_follows_fetch_metadata(page: str, url: str, relation: str) -> None:
    assert site_relation(page, url) == relation


def test_no_referrer_goes_from_an_https_page_to_an_http_url() -> None:
    assert referrer("https://a.example.com/p", "http://a.example.com/j") is None


# --- challenge labels (D-1326) ---------------------------------------------------------------------------------------


def _showing(signature: ChallengeSignature) -> httpx.Response:
    """A 403 showing one mark of `signature`: a header if it has any, else a cookie, else a script path."""
    if signature.header_names:
        return httpx.Response(403, headers={min(signature.header_names): "1"})
    if signature.cookie_prefixes:
        return httpx.Response(403, headers={"Set-Cookie": f"{signature.cookie_prefixes[0]}1=v; Path=/"})
    return httpx.Response(403, content=f'<script src="{signature.script_paths[0]}x"></script>'.encode())


@pytest.mark.parametrize("signature", SIGNATURES, ids=[s.vendor for s in SIGNATURES])
def test_a_refusal_showing_a_vendors_signature_is_labelled_with_it(signature: ChallengeSignature) -> None:
    result = fetch(lambda _r: _showing(signature))

    assert result.attempts[0].challenge == signature.vendor
    assert result.block_class == "blocked"  # INV-24: the label changes no class


def test_a_refusal_whose_document_stands_in_for_the_page_is_labelled_structural() -> None:
    body = b"<html><body><script>setTimeout(function(){location.reload()},1000)</script></body></html>"

    result = fetch(lambda _r: httpx.Response(403, headers={"Content-Type": "text/html"}, content=body))

    assert (result.block_class, result.attempts[0].challenge) == ("blocked", STRUCTURAL)


def test_a_plain_refusal_is_not_a_challenge() -> None:
    result = fetch(lambda _r: httpx.Response(403, headers={"Content-Type": "text/html"}, content=b"<p>Forbidden</p>"))

    assert (result.block_class, result.attempts[0].challenge) == ("blocked", None)


# --- INV-29: cookies stay inside one fetch -----------------------------------------------------------------------


def test_inv29_a_cookie_set_by_one_fetch_is_absent_from_the_next() -> None:
    handler, seen = recording(lambda _r: httpx.Response(200, headers={"Set-Cookie": "session=s1"}, content=_JSON))

    fetch(handler)
    fetch(handler)

    assert [request.headers.get("Cookie") for request in seen] == [None, None]


@pytest.mark.parametrize(
    ("set_cookie", "next_hop"),
    [
        # RFC 6265 §5.4: a host-only cookie goes to its own host only, even when both hosts share an address;
        # `keep`, for the parent domain, does go (§5.1.3 domain-match), so the hop carries cookies at all.
        (("other=1", "keep=1; Domain=example.com"), "https://cdn.example.com/v1/board/all"),
        (("other=1", "keep=1; Domain=example.com"), "https://eu.api.example.com/v1/board/all"),
        # §5.3 step 6: a Domain attribute that the setting host does not domain-match is ignored with its cookie.
        (("other=1; Domain=cdn.example.com", "keep=1"), "/v1/board/all"),
        # §5.1.4: a cookie goes only to request paths its Path matches.
        (("other=1; Path=/private", "keep=1; Path=/"), "/v1/board/all"),
    ],
    ids=["another_host", "sub_host", "foreign_domain_attribute", "another_path"],
)
def test_inv29_a_cookie_that_does_not_match_the_next_hop_is_not_sent(
    set_cookie: tuple[str, str], next_hop: str
) -> None:
    def route(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/board/jobs":
            headers = [("Location", next_hop), *(("Set-Cookie", c) for c in set_cookie)]
            return httpx.Response(302, headers=headers)
        return json_reply()(request)

    handler, seen = recording(route)
    shared_address = dict.fromkeys(("api.example.com", "cdn.example.com", "eu.api.example.com"), "93.184.215.14")
    assert outcome(fetch(handler, dns=shared_address)) == (200, "ok", None)

    assert seen[1].headers.get("Cookie") == "keep=1"


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


def test_the_request_reaches_the_pinned_address_under_its_host_name(server: Server) -> None:
    server.route("/jobs", json_route())

    result = fetch_local(server, "/jobs")

    assert outcome(result) == (200, "ok", None)
    assert [request for request, _ in server.requests] == ["api.example.test/jobs"]


def test_the_json_call_sends_the_impersonations_headers_in_its_order(server: Server) -> None:
    """D-1321: the JSON rung's headers take the impersonation profile's positions, as the HTTP rung's do; the fields
    a navigation alone sends are gone and the Fetch Metadata are a CORS request's."""
    page = server.url("/page", host="api.example.test")
    server.route("/jobs", json_route())
    server.route("/page", Reply(200, (("Content-Type", "text/html"),), b"<a href='/x'>x</a>" * 5))
    asyncio.run(
        fetch_http(
            page,
            FetchPolicy(),
            engine_version="test",
            impersonate=IMPERSONATE,
            connector=LoopbackConnector(server.port, {}),
        )
    )
    fetch_local(server, "/jobs", page=page)

    navigation, call = ([name.lower() for name, _ in headers] for _, headers in server.requests)
    shared = [name for name in navigation if name in call]
    assert [name for name in call if name in shared] == shared
    assert {"user-agent", "accept", "sec-fetch-site", "accept-encoding"} <= set(shared)
    assert {"sec-fetch-user", "upgrade-insecure-requests"} <= set(navigation) - set(call)
    sent = dict((name.lower(), value) for name, value in server.requests[1][1])
    assert (sent["sec-fetch-mode"], sent["sec-fetch-dest"], sent["sec-fetch-site"]) == ("cors", "empty", "same-origin")
    assert sent["accept"] == "application/json"


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


def test_a_compressed_body_is_kept_decoded(server: Server) -> None:
    server.route("/jobs", json_route(gzip.compress(_JSON), ("Content-Encoding", "gzip")))

    result = fetch_local(server, "/jobs")

    assert outcome(result) == (200, "ok", None)
    assert result.bundle.body == _JSON


def test_a_corrupt_content_encoding_is_a_decode_error(server: Server) -> None:
    server.route("/jobs", json_route(b"not gzip", ("Content-Encoding", "gzip")))

    assert outcome(fetch_local(server, "/jobs")) == (200, "error", "decode_error")


def test_a_body_slower_than_the_time_budget_is_a_timeout(server: Server) -> None:
    server.route("/jobs", json_route(delay_s=3.0))

    result = fetch_local(server, "/jobs", FetchPolicy(timeout_s=0.5))

    assert (result.block_class, result.attempts[0].error) == ("error", "timeout")


def test_a_refused_connection_is_a_network_error_naming_no_url() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]  # closed again before the fetch: nothing listens there
    request = JsonRequest(url=f"http://api.example.test:{port}/jobs", page_url=PAGE)

    result = asyncio.run(
        fetch_json(
            request,
            FetchPolicy(timeout_s=5),
            engine_version="test",
            impersonate=IMPERSONATE,
            connector=LoopbackConnector(port, {}),
        )
    )

    assert outcome(result) == (0, "error", "network_error: curl 7")
