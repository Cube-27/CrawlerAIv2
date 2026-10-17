"""The `fetch` member every page request shares (scrape, batch, crawl, extract; SPEC-07 §4.4): how its pages are
fetched, and the fetch policy it makes for a page (`fetch_policy`).

Besides the method hint, robots.txt override, proxy pool and row target, it carries the caller's request context
(D-1430): `headers` and `cookies`, whose values are secrets, `wait_for` and `actions`, the page steps the browser runs
before it reads the page (`page_actions` in `config_ir`, D-1436), and `cache`, whether a stored capture is reused
(D-1435).

A secret value is shown as `**********` by every serialization (an answer, a stored scrape request, a log line), except
the one that stores an asynchronous job's request for its workers (`KEEP_SECRETS`, D-1432).
"""

import re
from collections.abc import Collection, Iterable, Mapping
from typing import Annotated, Final, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    SecretStr,
    SerializationInfo,
    field_serializer,
    field_validator,
    model_validator,
)

from crawlerai.acquire.types import REDACTED, FetchPolicy, RequestContext, check_robots_override
from crawlerai.config_ir.page_actions import MAX_ACTIONS, Action, WaitFor, to_steps, wait_for_action
from crawlerai.core.errors import Refusal
from crawlerai.db.models import PageKind

__all__ = [
    "CAPTURE_FORMATS",
    "KEEP_SECRETS",
    "CacheMode",
    "FetchOptions",
    "UnknownProxyPool",
    "check_proxy_pool",
    "fetch_policy",
    "redacted_request",
]

# The serialization context that keeps secret values: only an asynchronous job's stored request, which its workers read.
KEEP_SECRETS: Final = "keep_secrets"
# D-1435: reuse a stored capture as `max_age` allows (`default`), always fetch (`bypass`), or only serve a stored one.
CacheMode = Literal["default", "bypass", "only"]
# The formats made in the browser from the rendered page: a PNG of it and a PDF print (`FetchPolicy.screenshot`, `pdf`).
CAPTURE_FORMATS: Final = frozenset({"screenshot", "pdf"})
_MAX_PAIRS: Final = 50
# RFC 9110 §5.1, §5.6.2: a field name is a token. §5.5: a field value holds no CR, LF or NUL.
_TOKEN: Final = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_FIELD_VALUE: Final = re.compile(r"^[^\r\n\x00]*$")
# RFC 6265 §4.1.1: a cookie name is a token; its value is cookie-octets (no space, DQUOTE, comma, semicolon or
# backslash), optionally inside DQUOTEs.
_COOKIE_VALUE: Final = re.compile(
    r'^(?:[\x21\x23-\x2b\x2d-\x3a\x3c-\x5b\x5d-\x7e]*|"[\x21\x23-\x2b\x2d-\x3a\x3c-\x5b\x5d-\x7e]*")$'
)
# Fetch Standard §2.2.2: the forbidden request-header names, which a page's own script cannot set either (the
# connection's framing, cookies, the request's origin), and those starting with `proxy-` or `sec-` (Fetch Metadata,
# client hints). `User-Agent` too: the HTTP rung's identity is its impersonation's, and the browser's its own (INV-44).
_FORBIDDEN: Final = frozenset(
    {
        "accept-charset",
        "accept-encoding",
        "access-control-request-headers",
        "access-control-request-method",
        "connection",
        "content-length",
        "cookie",
        "cookie2",
        "date",
        "dnt",
        "expect",
        "host",
        "keep-alive",
        "origin",
        "referer",
        "set-cookie",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "via",
        "user-agent",
    }
)
_FORBIDDEN_PREFIXES: Final = ("proxy-", "sec-")


class UnknownProxyPool(Refusal):
    """The request names a proxy pool this deployment has not configured (`CRAWLERAI_PROXY_POOLS`)."""


Secrets = Annotated[dict[str, SecretStr], Field(max_length=_MAX_PAIRS)]


class FetchOptions(BaseModel):
    """How a request's pages are fetched. `headers` go over HTTP to the page's own host only, never in the browser
    (INV-44), and `cookies` to that host in either; `wait_for` and `actions` run in the browser, so they make the fetch
    a browser one and refuse `method_hint` `http`, and a browser fetch takes no `headers`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    method_hint: Literal["auto", "http", "browser"] = "auto"
    screenshot: Literal["viewport", "full_page"] = "viewport"  # the area a `screenshot` format shows
    respect_robots: bool = True
    robots_override_reason: str | None = None
    proxy_pool: str | None = None
    max_rows: PositiveInt | None = None  # `FetchPolicy.max_rows`
    headers: Secrets = {}
    cookies: Secrets = {}
    wait_for: WaitFor | None = None
    actions: Annotated[list[Action], Field(max_length=MAX_ACTIONS)] = []
    cache: CacheMode = "default"

    @field_validator("headers")
    @classmethod
    def _sendable_headers(cls, headers: dict[str, SecretStr]) -> dict[str, SecretStr]:
        for name, value in headers.items():
            if not _TOKEN.match(name) or not _FIELD_VALUE.match(value.get_secret_value()):
                raise ValueError(f"{name!r} is not an HTTP header field (RFC 9110 §5)")
            lowered = name.lower()
            if lowered in _FORBIDDEN or lowered.startswith(_FORBIDDEN_PREFIXES):
                raise ValueError(
                    f"{name} is a header the fetch sets itself (Fetch Standard §2.2.2); cookies go in cookies"
                )
        if len({name.lower() for name in headers}) != len(headers):
            raise ValueError("a header is named twice")
        return headers

    @field_validator("cookies")
    @classmethod
    def _cookie_pairs(cls, cookies: dict[str, SecretStr]) -> dict[str, SecretStr]:
        for name, value in cookies.items():
            if not _TOKEN.match(name) or not _COOKIE_VALUE.match(value.get_secret_value()):
                raise ValueError(f"{name!r} is not a cookie name and value (RFC 6265 §4.1.1)")
        return cookies

    @field_validator("wait_for")
    @classmethod
    def _translatable(cls, wait_for: WaitFor | None) -> WaitFor | None:
        if wait_for is not None:
            wait_for_action(wait_for)  # raises for a selector cssselect does not translate
        return wait_for

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        check_robots_override(self.respect_robots, self.robots_override_reason)
        in_browser = self.wait_for is not None or bool(self.actions)
        if in_browser and self.method_hint == "http":
            raise ValueError("wait_for and actions run in the browser, so method_hint cannot be http")
        if self.headers and (in_browser or self.method_hint == "browser"):
            raise ValueError("headers are sent over HTTP only; the browser sets none of its own (INV-44)")
        return self

    @field_serializer("headers", "cookies")
    def _redacted(self, values: dict[str, SecretStr], info: SerializationInfo) -> dict[str, str]:
        keep = isinstance(info.context, dict) and info.context.get(KEEP_SECRETS) is True
        return {name: value.get_secret_value() if keep else REDACTED for name, value in values.items()}

    @property
    def in_browser(self) -> bool:
        """Whether the pages are fetched in the browser: asked for, or for the page steps."""
        return self.method_hint == "browser" or self.wait_for is not None or bool(self.actions)

    def context(self) -> RequestContext | None:
        if not self.headers and not self.cookies:
            return None
        return RequestContext(headers=tuple(self.headers.items()), cookies=tuple(self.cookies.items()))


def check_proxy_pool(options: FetchOptions, pools: Collection[str]) -> None:
    """Raises `UnknownProxyPool` when `options` names a pool not among `pools`, the configured ones (D-1434)."""
    if options.proxy_pool is not None and options.proxy_pool not in pools:
        raise UnknownProxyPool(f"no proxy pool named {options.proxy_pool!r} is configured")


def fetch_policy(
    options: FetchOptions,
    locale: str | None,
    site_pool: str | None,
    *,
    page_kind: PageKind | None = None,
    formats: Iterable[str] = (),
) -> FetchPolicy:
    """The fetch policy of a page task. A screenshot or PDF among its `formats` is made in the browser, which then
    fetches the page whatever the site's remembered method (`FetchPolicy.screenshot`, `pdf`)."""
    wanted = set(formats)
    return FetchPolicy(
        page_kind=page_kind,
        method_hint="browser" if options.in_browser or CAPTURE_FORMATS & wanted else options.method_hint,
        screenshot=options.screenshot if "screenshot" in wanted else None,
        pdf="pdf" in wanted,
        proxy_pool=options.proxy_pool or site_pool,
        respect_robots=options.respect_robots,
        robots_override_reason=options.robots_override_reason,
        locale_hint=locale,
        max_rows=options.max_rows,
        context=options.context(),
        steps=to_steps(options.actions, options.wait_for),
    )


def redacted_request(request: Mapping[str, object]) -> dict[str, object]:
    """A stored job request with its `fetch` secrets shown as `**********` (D-1432), for every answer that shows it."""
    fetch = request.get("fetch")
    if not isinstance(fetch, Mapping):
        return dict(request)
    shown = dict(fetch)
    for member in ("headers", "cookies"):
        if isinstance(values := fetch.get(member), Mapping):
            shown[member] = dict.fromkeys(values, REDACTED)
    return {**request, "fetch": shown}
