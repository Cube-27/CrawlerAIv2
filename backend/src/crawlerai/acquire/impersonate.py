"""Which Chrome the HTTP and JSON rungs impersonate (acquisition spec, D-1325): the browser rung's own Chromium major,
so a site that sees both rungs sees one browser version.

At startup the configured target (`CRAWLERAI_IMPERSONATE`) is compared with the Chromium Patchright installs (its
`browsers.json`, read without launching it). Left unset, the target becomes curl_cffi's Chrome profile nearest that
major, with a warning when none matches it exactly; set by the operator, it is kept, with a warning when it differs.
"""

import json
import logging
import re
from functools import cache
from importlib.util import find_spec
from pathlib import Path
from typing import Final, cast, get_args

from curl_cffi.requests import BrowserTypeLiteral

from crawlerai.core.settings import AcquireSettings

__all__ = ["browser_major", "nearest_target", "rung_impersonation"]

log = logging.getLogger(__name__)

# curl_cffi's desktop Chrome profiles are named `chrome<major>`; lettered and Android variants are other clients.
_CHROME_PROFILE: Final = re.compile(r"chrome(\d+)")
_IMPERSONATE = "impersonate"


def rung_impersonation(settings: AcquireSettings) -> BrowserTypeLiteral:
    """The target the rungs impersonate, checked against the browser rung's Chromium (module docstring)."""
    major = browser_major()
    configured = settings.impersonate
    if major is None or _major(configured) == major:
        return configured
    if _IMPERSONATE in settings.model_fields_set:
        log.warning("CRAWLERAI_IMPERSONATE %s differs from the browser rung's Chromium %d", configured, major)
        return configured
    target = nearest_target(major)
    if _major(target) != major:
        log.warning("no curl_cffi Chrome profile for Chromium %d: impersonating %s", major, target)
    return target


def nearest_target(major: int) -> BrowserTypeLiteral:
    """curl_cffi's desktop Chrome profile whose major is nearest `major`, the newer on a tie."""
    profiles = {major_: name for name in get_args(BrowserTypeLiteral) if (major_ := _major(name)) is not None}
    nearest = min(profiles, key=lambda candidate: (abs(candidate - major), -candidate))
    return cast(BrowserTypeLiteral, profiles[nearest])


def _major(target: str) -> int | None:
    match = _CHROME_PROFILE.fullmatch(target)
    return None if match is None else int(match.group(1))


@cache
def browser_major() -> int | None:
    """The major version of the Chromium Patchright installs (its driver's `browsers.json`), or None when Patchright
    or the file is absent."""
    spec = find_spec("patchright")
    if spec is None or spec.origin is None:
        return None
    path = Path(spec.origin).parent / "driver" / "package" / "browsers.json"
    try:
        browsers = json.loads(path.read_text(encoding="utf-8"))["browsers"]
        version = next(b["browserVersion"] for b in browsers if b["name"] == "chromium")
        return int(str(version).split(".", 1)[0])
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        return None
