"""Which Chrome the HTTP and JSON rungs impersonate: the browser rung's own Google Chrome, so
a site that sees both rungs, and the cookies one hands the other, sees one browser on one platform.

At startup the browser rung's Chrome is started once, loading no site, to read the headers that name it on a navigation
(`browser_session.browser_identity`, in the browser rung's mode: its user agent as its profiles send it, its client
hints, `Accept` and `Accept-Language`). The rungs send those in place of their impersonation's own, and impersonate
curl_cffi's Chrome profile nearest its major for the TLS and HTTP/2 handshake, with a warning when none matches it
exactly. A target the operator sets (`CRAWLERAI_IMPERSONATE`) is kept with its own headers and starts no browser. A
process that runs the browser rung does not start when that Chrome cannot be read (`BrowserUnread`): its HTTP rung would
name another browser than its renders. A process without it (`crawlerai fetch` over HTTP) keeps the default target's own
headers, with a warning.
"""

import logging
import re
from dataclasses import dataclass
from typing import Final, cast, get_args

from curl_cffi.requests import BrowserTypeLiteral
from patchright.async_api import Error as PlaywrightError

from crawlerai.acquire.browser_session import browser_identity, open_driver
from crawlerai.core.settings import AcquireSettings
from crawlerai.storage.capture_bundle import HeaderList

__all__ = ["BrowserUnread", "Impersonation", "nearest_target", "rung_impersonation"]

log = logging.getLogger(__name__)

# curl_cffi's desktop Chrome profiles are named `chrome<major>`; lettered and Android variants are other clients.
_CHROME_PROFILE: Final = re.compile(r"chrome(\d+)")
# The product token of Chrome's user agent (Chromium's reduced user agent: `Chrome/<major>.0.0.0`).
_CHROME_PRODUCT: Final = re.compile(r"\bChrome/(\d+)\.")
_IMPERSONATE = "impersonate"


class BrowserUnread(RuntimeError):
    """The browser rung's Chrome could not be read in a process that runs the browser rung (module docstring)."""


@dataclass(frozen=True)
class Impersonation:
    """The curl_cffi target whose TLS, HTTP/2 and header order the rungs send, and the headers that replace the
    target's own of the same name (lowercase names; none: the target's own)."""

    target: BrowserTypeLiteral
    headers: HeaderList = ()


async def rung_impersonation(settings: AcquireSettings, *, browser_rung: bool) -> Impersonation:
    """The impersonation of the rungs: the browser rung's Chrome (module docstring). `browser_rung`: the process also
    renders in that browser. Raises `BrowserUnread` for such a process when its Chrome cannot be read."""
    configured = settings.impersonate
    if _IMPERSONATE in settings.model_fields_set:
        return Impersonation(configured)
    try:
        headers = await _read_headers(settings.browser_headless)
    except (PlaywrightError, OSError) as e:  # the driver or the browser could not be started
        return _unread("did not start", configured, browser_rung, e)
    agent = next((value for name, value in headers if name == "user-agent"), "")
    major = _CHROME_PRODUCT.search(agent)
    if major is None:
        return _unread("names no Chrome in its user agent", configured, browser_rung)
    target = nearest_target(int(major.group(1)))
    if _major(target) != int(major.group(1)):
        log.warning("no curl_cffi Chrome profile for Chrome %s: impersonating %s", major.group(1), target)
    return Impersonation(target, headers)


def _unread(
    why: str, configured: BrowserTypeLiteral, browser_rung: bool, cause: Exception | None = None
) -> Impersonation:
    if browser_rung:
        raise BrowserUnread(
            f"the browser rung's Chrome {why}: install it (`patchright install chrome`) or set CRAWLERAI_IMPERSONATE"
        ) from cause
    log.warning("the browser rung's Chrome %s: impersonating %s with its own headers", why, configured)
    return Impersonation(configured)


async def _read_headers(headless: bool) -> HeaderList:
    async with open_driver(headless) as playwright:
        return (await browser_identity(playwright, headless=headless)).headers


def nearest_target(major: int) -> BrowserTypeLiteral:
    """curl_cffi's desktop Chrome profile whose major is nearest `major`, the newer on a tie."""
    profiles = {major_: name for name in get_args(BrowserTypeLiteral) if (major_ := _major(name)) is not None}
    nearest = min(profiles, key=lambda candidate: (abs(candidate - major), -candidate))
    return cast(BrowserTypeLiteral, profiles[nearest])


def _major(target: str) -> int | None:
    match = _CHROME_PROFILE.fullmatch(target)
    return None if match is None else int(match.group(1))
