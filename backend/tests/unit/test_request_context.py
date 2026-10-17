"""The caller's request context and page actions as a request names them (D-1430 to D-1438): the checks of `fetch`,
the step vocabulary's translation, the redaction of secret values, and the HTTP rung sending headers and cookies to the
fetched URL's host only.

The HTTP rung runs against a local server under `.test` names (RFC 2606), as `test_http_fetch.py` does.
"""

import asyncio
import json
from collections.abc import Iterator
from typing import Any

import pytest
from cssselect import HTMLTranslator
from pydantic import SecretStr, ValidationError

from crawlerai.acquire.http import fetch_http
from crawlerai.acquire.types import REDACTED, FetchPolicy, FetchResult, RequestContext
from crawlerai.config_ir.page_actions import to_steps
from crawlerai.core.settings import IMPERSONATE_DEFAULT
from crawlerai.services.fetch_options import (
    KEEP_SECRETS,
    FetchOptions,
    UnknownProxyPool,
    check_proxy_pool,
    fetch_policy,
    redacted_request,
)
from tests.local_server import LoopbackConnector, Reply, Server, serving

_PAGE = b'<html><body><a href="/a">a</a><a href="/b">b</a><p>words of a page</p></body></html>'


@pytest.fixture
def server() -> Iterator[Server]:
    yield from serving()


def _options(**members: Any) -> FetchOptions:
    return FetchOptions.model_validate(members)


def _refused(**members: Any) -> str:
    with pytest.raises(ValidationError) as refused:
        FetchOptions.model_validate(members)
    return str(refused.value)


# --- the `fetch` member ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["User-Agent", "Cookie", "Host", "Sec-CH-UA", "sec-fetch-site", "Proxy-Authorization"])
def test_a_header_the_fetch_sets_itself_is_refused(name: str) -> None:
    assert "sets itself" in _refused(headers={name: "x"})


def test_a_header_value_with_a_line_break_is_refused() -> None:
    assert "RFC 9110" in _refused(headers={"X-Token": "a\r\nInjected: b"})


def test_a_cookie_value_outside_cookie_octets_is_refused() -> None:
    assert "RFC 6265" in _refused(cookies={"sid": "a;b"})


def test_page_steps_refuse_an_http_fetch_and_headers_refuse_a_browser_one() -> None:
    assert "method_hint cannot be http" in _refused(method_hint="http", wait_for=500)
    assert "HTTP only" in _refused(headers={"Authorization": "Bearer t"}, actions=[{"type": "scroll", "to": "bottom"}])
    assert "HTTP only" in _refused(headers={"Authorization": "Bearer t"}, method_hint="browser")


def test_more_than_twenty_actions_are_refused() -> None:
    assert "20" in _refused(actions=[{"type": "wait", "ms": 10}] * 21)


@pytest.mark.parametrize(
    "action",
    [
        {"type": "click"},  # no element
        {"type": "click", "selector": ".a", "text": "b"},  # two
        {"type": "click", "selector": "a[["},  # not CSS
        {"type": "wait", "ms": 10, "network_idle": True},
        {"type": "scroll", "to": "bottom", "by": 10},
        {"type": "press", "key": "Enter Enter"},
        {"type": "type", "text": "x"},
        {"type": "hover", "selector": "a"},
    ],
)
def test_a_malformed_action_is_refused(action: dict[str, Any]) -> None:
    _refused(actions=[action])


def test_page_steps_make_the_policy_a_browser_one_with_the_steps_in_order() -> None:
    options = _options(
        wait_for="network_idle",
        actions=[
            {"type": "click", "selector": "button.more"},
            {"type": "scroll", "by": 600},
            {"type": "wait", "ms": 800},
            {"type": "click", "text": "Next"},
        ],
    )
    policy = fetch_policy(options, None, None)

    assert policy.method_hint == "browser"
    assert [(s.action, s.network_idle, s.scroll, s.px, s.ms, s.text) for s in policy.steps] == [
        ("wait", True, None, None, None, None),
        ("click", False, None, None, None, None),
        ("scroll", False, "by", 600, None, None),
        ("wait", False, None, None, 800, None),
        ("click", False, None, None, None, "Next"),
    ]
    # A CSS selector runs as its XPath 1.0 translation, as an IR `css` step does (SPEC-08 §4.2).
    assert policy.steps[1].xpath == HTMLTranslator().css_to_xpath("button.more")


def test_wait_for_milliseconds_lasts_as_long_as_it_says() -> None:
    (step,) = to_steps([], 12_000)

    assert (step.action, step.ms, step.timeout_ms) == ("wait", 12_000, 12_000)


def test_secret_values_are_redacted_except_in_a_stored_job_request() -> None:
    options = _options(headers={"Authorization": "Bearer t0ken"}, cookies={"sid": "s3cret"})

    shown = options.model_dump(mode="json")
    kept = options.model_dump(mode="json", context={KEEP_SECRETS: True})

    assert shown["headers"] == {"Authorization": REDACTED}
    assert shown["cookies"] == {"sid": REDACTED}
    assert kept["headers"] == {"Authorization": "Bearer t0ken"}
    assert kept["cookies"] == {"sid": "s3cret"}
    assert FetchOptions.model_validate(kept) == options  # the worker reads back what was submitted
    assert "t0ken" not in repr(options)
    assert "s3cret" not in repr(options)


def test_a_policys_context_is_redacted_wherever_it_is_serialized() -> None:
    policy = fetch_policy(_options(cookies={"sid": "s3cret"}), None, None)

    assert policy.model_dump(mode="json")["context"] == {"headers": [], "cookies": [["sid", REDACTED]]}
    assert "s3cret" not in repr(policy)


def test_a_stored_request_is_answered_redacted() -> None:
    cookies = {"sid": "s3cret"}
    stored = {"urls": ["https://shop.example.test/"], "fetch": {"cookies": cookies, "headers": {}}}

    assert redacted_request(stored)["fetch"] == {"cookies": {"sid": REDACTED}, "headers": {}}
    assert cookies == {"sid": "s3cret"}  # the stored row itself is not changed


def test_only_a_configured_proxy_pool_is_taken() -> None:
    check_proxy_pool(_options(proxy_pool="eu"), {"eu"})
    options = _options(proxy_pool="us")

    with pytest.raises(UnknownProxyPool):
        check_proxy_pool(options, {"eu"})


# --- the HTTP rung -----------------------------------------------------------------------------------------------


def _fetch(server: Server, url: str, context: RequestContext) -> FetchResult:
    return asyncio.run(
        fetch_http(
            url,
            FetchPolicy(context=context),
            engine_version="test",
            impersonate=IMPERSONATE_DEFAULT,
            connector=LoopbackConnector(server.port, {}),
        )
    )


def _context(headers: dict[str, str] | None = None, cookies: dict[str, str] | None = None) -> RequestContext:
    return RequestContext(
        headers=tuple((k, SecretStr(v)) for k, v in (headers or {}).items()),
        cookies=tuple((k, SecretStr(v)) for k, v in (cookies or {}).items()),
    )


def _sent(server: Server, at: str) -> dict[str, str]:
    return next({name.lower(): value for name, value in headers} for path, headers in server.requests if path == at)


def test_the_callers_header_and_cookie_go_to_the_pages_host_and_stay_out_of_the_capture(server: Server) -> None:
    server.route("/p", Reply(200, (("Content-Type", "text/html"),), _PAGE))
    result = _fetch(server, server.url("/p"), _context({"Authorization": "Bearer t0ken"}, {"sid": "s3cret"}))

    sent = _sent(server, "shop.example.test/p")
    assert sent["authorization"] == "Bearer t0ken"
    assert sent["cookie"] == "sid=s3cret"
    stored = result.bundle.manifest.model_dump_json()
    assert "t0ken" not in stored
    assert "s3cret" not in stored


def test_a_redirect_to_another_host_carries_neither_the_header_nor_the_cookie(server: Server) -> None:
    server.route("/p", Reply(302, (("Location", server.url("/q", "cdn.example.test")),)))
    server.route("/q", Reply(200, (("Content-Type", "text/html"),), _PAGE))
    _fetch(server, server.url("/p"), _context({"X-Api-Key": "k3y"}, {"sid": "s3cret"}))

    assert _sent(server, "shop.example.test/p")["x-api-key"] == "k3y"
    elsewhere = _sent(server, "cdn.example.test/q")
    assert "x-api-key" not in elsewhere
    assert "cookie" not in elsewhere


def test_a_header_the_caller_names_replaces_the_impersonations(server: Server) -> None:
    server.route("/p", Reply(200, (("Content-Type", "text/html"),), _PAGE))
    _fetch(server, server.url("/p"), _context({"Accept-Language": "de-CH"}))

    assert _sent(server, "shop.example.test/p")["accept-language"] == "de-CH"
    assert json.dumps(server.requests).count("Accept-Language") == 1
