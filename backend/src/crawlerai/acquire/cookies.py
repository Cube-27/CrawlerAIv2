"""The cookies of one fetch (INV-29), for the HTTP and JSON rungs: a cookie one hop's response sets goes with a later
hop whose host name and path it matches (RFC 6265 §5.4), and never to another fetch.

Each request connects to the address the SSRF guard checked, so cookies are matched here, by the URL's host name,
never by the client's own jar against the address. A cookie for a public suffix is ignored (§5.3 step 5,
`public_suffix`). A site session's cookies (`acquire.session`, INV-29's one exception) are seeded into the jar before
the first hop and matched by the same rules.
"""

import asyncio
from collections.abc import Iterable
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

    def seed(self, cookies: Iterable[SessionCookie]) -> None:
        """Hold `cookies` as if earlier hops had set them: a host-only cookie for its host alone, a `Domain` cookie for
        its domain and every subdomain (RFC 6265 §5.3 steps 6, 11)."""
        for cookie in cookies:
            self._jar.jar.set_cookie(
                Cookie(
                    version=0,
                    name=cookie.name,
                    value=cookie.value,
                    port=None,
                    port_specified=False,
                    domain=cookie.domain if cookie.host_only else f".{cookie.domain}",
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
