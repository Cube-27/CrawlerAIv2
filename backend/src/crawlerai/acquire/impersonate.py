"""Which Chrome the HTTP and JSON rungs impersonate: the browser rung's own Google Chrome, so
a site that sees both rungs, and the cookies one hands the other, sees one browser on one platform.

At startup the browser rung's Chrome is started once, loading no site, to read the headers that name it on a navigation
(`browser_session.browser_identity`: its user agent as its profiles send it, its client hints, `Accept` and
`Accept-Language`) and the TLS ClientHello it opens a connection with. The rungs send those headers in place of their
impersonation's own, and impersonate curl_cffi's Chrome profile nearest its major for the TLS and HTTP/2 handshake, with
a warning when none matches it exactly, adding the trust anchors the browser's ClientHello requests (no profile sends
that extension). The HTTP rung's ClientHello is then read the same way, and a JA4 that differs from the browser's is
logged once: a Chrome update the profile does not follow. A target the operator sets (`CRAWLERAI_IMPERSONATE`) is
kept with its own headers and TLS and starts no browser. A process that runs the browser rung does not start when that
Chrome cannot be read (`BrowserUnread`): its HTTP rung would name another browser than its renders. A process without
it (`crawlerai fetch` over HTTP) keeps the default target's own headers, with a warning.
"""

import contextlib
import logging
import re
from dataclasses import dataclass
from typing import Final, cast, get_args

from curl_cffi import CurlOpt
from curl_cffi.requests import AsyncSession, BrowserTypeLiteral, Response
from curl_cffi.requests.exceptions import RequestException
from patchright.async_api import Error as PlaywrightError
from patchright.async_api import async_playwright

from crawlerai.acquire.browser_session import Identity, browser_identity
from crawlerai.acquire.client_hello import ClientHello, hello_listener, ja4
from crawlerai.core.settings import AcquireSettings
from crawlerai.storage.capture_bundle import HeaderList

__all__ = ["BrowserUnread", "Impersonation", "nearest_target", "rung_impersonation"]

log = logging.getLogger(__name__)

# curl_cffi's desktop Chrome profiles are named `chrome<major>`; lettered and Android variants are other clients.
_CHROME_PROFILE: Final = re.compile(r"chrome(\d+)")
# The product token of Chrome's user agent (Chromium's reduced user agent: `Chrome/<major>.0.0.0`).
_CHROME_PRODUCT: Final = re.compile(r"\bChrome/(\d+)\.")
_IMPERSONATE = "impersonate"
_HELLO_TIMEOUT: Final = 10  # seconds for the HTTP rung's connection to the loopback listener


class BrowserUnread(RuntimeError):
    """The browser rung's Chrome could not be read in a process that runs the browser rung (module docstring)."""


@dataclass(frozen=True)
class Impersonation:
    """The curl_cffi target whose TLS, HTTP/2 and header order the rungs send, the headers that replace the
    target's own of the same name (lowercase names; none: the target's own), and the trust anchors its ClientHello
    requests (draft-ietf-tls-trust-anchor-ids, relative OIDs; none: the target's own TLS)."""

    target: BrowserTypeLiteral
    headers: HeaderList = ()
    trust_anchors: tuple[str, ...] | None = None

    def tls_options(self) -> dict[CurlOpt, object]:
        """The curl options set over the target's TLS: CURLOPT_TLS_TRUST_ANCHORS (curl-impersonate), the anchors
        comma-separated, which curl sends in an order it draws for each connection."""
        return {} if self.trust_anchors is None else {CurlOpt.TLS_TRUST_ANCHORS: ",".join(self.trust_anchors)}


async def rung_impersonation(settings: AcquireSettings, *, browser_rung: bool) -> Impersonation:
    """The impersonation of the rungs: the browser rung's Chrome (module docstring). `browser_rung`: the process also
    renders in that browser. Raises `BrowserUnread` for such a process when its Chrome cannot be read."""
    configured = settings.impersonate
    if _IMPERSONATE in settings.model_fields_set:
        return Impersonation(configured)
    try:
        identity = await _read_identity()
    except (PlaywrightError, OSError) as e:  # the driver or the browser could not be started
        return _unread("did not start", configured, browser_rung, e)
    major = _CHROME_PRODUCT.search(identity.agent)
    if major is None:
        return _unread("names no Chrome in its user agent", configured, browser_rung)
    target = nearest_target(int(major.group(1)))
    if _major(target) != int(major.group(1)):
        log.warning("no curl_cffi Chrome profile for Chrome %s: impersonating %s", major.group(1), target)
    hello = identity.hello
    chosen = Impersonation(target, identity.headers, None if hello is None else hello.trust_anchors)
    await _compare_hellos(hello, chosen)
    return chosen


def _unread(
    why: str, configured: BrowserTypeLiteral, browser_rung: bool, cause: Exception | None = None
) -> Impersonation:
    if browser_rung:
        raise BrowserUnread(
            f"the browser rung's Chrome {why}: install it (`patchright install chrome`) or set CRAWLERAI_IMPERSONATE"
        ) from cause
    log.warning("the browser rung's Chrome %s: impersonating %s with its own headers", why, configured)
    return Impersonation(configured)


async def _read_identity() -> Identity:
    async with async_playwright() as playwright:
        return await browser_identity(playwright)


async def _compare_hellos(browser: ClientHello | None, chosen: Impersonation) -> None:
    """Log once when the HTTP rung's ClientHello has another JA4 (FoxIO JA4, TLS client) than the browser rung's."""
    if browser is None:
        log.warning("the browser rung's TLS ClientHello was not read: the HTTP rung's is not compared with it")
        return
    sent = await _sent_hello(chosen)
    browser_ja4, sent_ja4 = ja4(browser), "unread" if sent is None else ja4(sent)
    if sent_ja4 != browser_ja4:
        log.warning("TLS ClientHello JA4: the browser rung's %s, the HTTP rung's %s", browser_ja4, sent_ja4)


async def _sent_hello(chosen: Impersonation) -> ClientHello | None:
    """The ClientHello the HTTP rung's impersonation sends, read on the loopback address (`hello_listener`), with no
    proxy (CURLOPT_PROXY empty: not even the environment's)."""
    options = cast(dict[CurlOpt, str], {**chosen.tls_options(), CurlOpt.PROXY: ""})
    async with hello_listener() as (url, hello):
        async with AsyncSession[Response](impersonate=chosen.target, trust_env=False, curl_options=options) as session:
            with contextlib.suppress(RequestException):  # the listener closes the connection after the ClientHello
                await session.get(url, timeout=_HELLO_TIMEOUT)
        return hello.result() if hello.done() else None


def nearest_target(major: int) -> BrowserTypeLiteral:
    """curl_cffi's desktop Chrome profile whose major is nearest `major`, the newer on a tie."""
    profiles = {major_: name for name in get_args(BrowserTypeLiteral) if (major_ := _major(name)) is not None}
    nearest = min(profiles, key=lambda candidate: (abs(candidate - major), -candidate))
    return cast(BrowserTypeLiteral, profiles[nearest])


def _major(target: str) -> int | None:
    match = _CHROME_PROFILE.fullmatch(target)
    return None if match is None else int(match.group(1))
