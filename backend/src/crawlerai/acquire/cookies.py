"""The cookies of one fetch (INV-29), for the HTTP and JSON rungs: a cookie one hop's response sets goes with a later
hop whose host name and path it matches (RFC 6265 §5.4), and never to another fetch.

Each request connects to the address the SSRF guard checked, so cookies are matched here, by the URL's host name,
never by the client's own jar against the address. A cookie for a public suffix is ignored (§5.3 step 5,
`public_suffix`).
"""

import asyncio
from http.cookiejar import CookieJar

import httpx

from crawlerai.acquire.public_suffix import PublicSuffixes, SuffixCookiePolicy, default_suffixes
from crawlerai.storage.capture_bundle import HeaderList


class FetchCookies:
    def __init__(self, suffixes: PublicSuffixes) -> None:
        self._jar = httpx.Cookies(CookieJar(SuffixCookiePolicy(suffixes)))

    @classmethod
    async def new(cls) -> "FetchCookies":
        # The list is parsed on the first fetch only (cached), off the event loop.
        return cls(await asyncio.to_thread(default_suffixes))

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
