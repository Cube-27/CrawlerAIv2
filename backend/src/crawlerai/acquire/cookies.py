"""The cookies of one fetch, for the HTTP and JSON rungs: a cookie one hop's response sets goes with a later
hop whose host name and path it matches (RFC 6265 §5.4), and never to another fetch.

Each request connects to the address the SSRF guard checked, so cookies are matched here, by the URL's host name,
never by the client's own jar against the address. A cookie for a public suffix is ignored (§5.3 step 5,
`public_suffix`). A site session's cookies (`acquire.session`) are seeded into the jar before
the first hop and matched by the same rules.

Several requests can be one fetch: a recipe's warm-up and the calls after it (`config_ir.api_recipe.execute`) share
one jar while it is held (`shared`), so a cookie the warm-up's answer sets goes with the calls, as the site's own page
sends it with its scripts' requests, and with no other fetch.
"""

import asyncio
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from http.cookiejar import Cookie, CookieJar

import httpx

from crawlerai.acquire.public_suffix import PublicSuffixes, SuffixCookiePolicy, default_suffixes
from crawlerai.acquire.session import SessionCookie
from crawlerai.storage.capture_bundle import HeaderList


class FetchCookies:
    def __init__(self, suffixes: PublicSuffixes) -> None:
        self._jar = httpx.Cookies(CookieJar(SuffixCookiePolicy(suffixes)))

    @classmethod
    async def new(cls) -> "FetchCookies":
        # The list is parsed on the first fetch only (cached), off the event loop.
        return cls(await asyncio.to_thread(default_suffixes))

    def held(self) -> frozenset[tuple[str, str, str]]:
        """The (name, domain, path) of each cookie the jar holds: a cookie's identity (RFC 6265 §5.3 step 11)."""
        return frozenset((c.name, c.domain, c.path) for c in self._jar.jar)

    def seed(self, cookies: Iterable[SessionCookie], keep: frozenset[tuple[str, str, str]] = frozenset()) -> None:
        """Hold `cookies` as if earlier hops had set them: a host-only cookie for its host alone, a `Domain` cookie for
        its domain and every subdomain (RFC 6265 §5.3 steps 6, 11), a later one replacing an earlier of the same name,
        domain and path, except one of `keep`: in a shared jar, an earlier request's response set it, which is newer
        than the seed (§5.3 step 11 keeps the newest)."""
        for cookie in cookies:
            domain = cookie.domain if cookie.host_only else f".{cookie.domain}"
            if (cookie.name, domain, cookie.path) in keep:
                continue
            self._jar.jar.set_cookie(
                Cookie(
                    version=0,
                    name=cookie.name,
                    value=cookie.value,
                    port=None,
                    port_specified=False,
                    domain=domain,
                    domain_specified=not cookie.host_only,
                    domain_initial_dot=not cookie.host_only,
                    path=cookie.path,
                    path_specified=True,
                    secure=cookie.secure,
                    expires=None if cookie.expires is None else int(cookie.expires),
                    discard=cookie.expires is None,
                    comment=None,
                    comment_url=None,
                    rest={},
                )
            )

    def header(self, url: str) -> str | None:
        """The `Cookie` header a request to `url` carries, if any."""
        if not self._jar:
            return None
        request = httpx.Request("GET", url)
        self._jar.set_cookie_header(request)
        cookie: str | None = request.headers.get("Cookie")
        return cookie

    def extract(self, url: str, status: int, headers: HeaderList) -> None:
        """Keep the cookies that the response from `url` sets."""
        request = httpx.Request("GET", url)
        # As bytes: httpx encodes a str header as ASCII, and a field value may hold other octets (RFC 9110 §5.5).
        raw = [(name.encode(), value.encode()) for name, value in headers]
        self._jar.extract_cookies(httpx.Response(status, headers=raw, request=request))


# The jar the requests of one fetch share while it is held (`shared`); None: each request has its own.
_SHARED: ContextVar[FetchCookies | None] = ContextVar("shared_fetch_cookies", default=None)


@contextmanager
def shared(jar: FetchCookies | None) -> Iterator[None]:
    """Send the requests made in this block with `jar` (module docstring); None: each with its own, as a request
    outside the shared fetch (a robots.txt read on the way) is sent."""
    token = _SHARED.set(jar)
    try:
        yield
    finally:
        _SHARED.reset(token)


async def fetch_jar() -> tuple[FetchCookies, bool]:
    """The jar of a request, and whether it is shared: the shared one while one is held, else a new one, which ends
    with the request."""
    held = _SHARED.get()
    return (held, True) if held is not None else (await FetchCookies.new(), False)
