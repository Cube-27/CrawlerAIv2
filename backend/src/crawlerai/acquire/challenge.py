"""Challenge labels on attempts (D-1326): which anti-bot challenge, if any, a `blocked` or `shell` response presents
(`CHALLENGED`: a site's missing page or failure is no challenge, whatever cookies its edge sets). The label is the
vendor whose signature the response shows (`adapters.challenges`, site data), else `STRUCTURAL` when the generic
signal holds, else none.

INV-24 (amended, D-1470): the block class comes from status and structure (`classify`) and, for a 2xx HTML document,
from a vendor's stand-in marker (`block_class_of`), the only site data that selects it; a label changes neither it nor
the remembered fetch method. Labels are recorded on the attempt (its manifest and `capture` row keep them), counted in
the log per label and rung, and slow a host's adaptive rate as a 429 does (`politeness`).
"""

import logging
from collections.abc import Iterable
from typing import Final

from crawlerai.acquire.classify import Redirect, classify, fetched_as, interstitial, is_html, usable_content
from crawlerai.acquire.types import BlockClass, FetchResult
from crawlerai.adapters.challenges import stand_in_vendor, vendor_of
from crawlerai.core.capture import CaptureMethod
from crawlerai.db.models import PageKind
from crawlerai.storage.capture_bundle import HeaderList

__all__ = [
    "CHALLENGED",
    "LEGAL",
    "STRUCTURAL",
    "block_class_of",
    "challenge_label",
    "challenge_signal",
    "count",
    "vendor_block",
]

log = logging.getLogger(__name__)

# The label of a challenge no vendor signature names.
STRUCTURAL: Final = "structural"
# The label of a 451, a refusal for legal reasons (RFC 7725 §3): the page is withheld where the request came from, no
# vendor's challenge; its page ends `geo_blocked` (jobs spec).
LEGAL: Final = "legal"
_UNAVAILABLE_FOR_LEGAL_REASONS = 451
_SET_COOKIE = "set-cookie"  # RFC 6265 §4.1
# The classes a challenge takes (`classify`): a refusal, or a document with nothing of the page in it.
CHALLENGED: Final[frozenset[BlockClass]] = frozenset({"blocked", "shell"})


def block_class_of(
    status: int,
    headers: HeaderList,
    text: str,
    page_kind: PageKind | None = None,
    redirect: Redirect | None = None,
) -> BlockClass:
    """The block class of a response whose body decoded to `text` (`classify`, with the `redirect` the rung followed),
    except that a 2xx HTML document (RFC 9110 §15.3) showing a vendor's stand-in marker (`adapters.challenges`) is
    `blocked`: the vendor served it in place of the page, whatever its status says, and the browser may pass it where
    HTTP did not. The marker needs corroboration: a document that carries the page's structured data
    (`classify.usable_content`) is the page, whatever vendor markup it also holds."""
    block_class = classify(status, headers, text, page_kind, redirect)
    if block_class == "ok" and 200 <= status < 300 and is_html(headers) and stand_in_vendor(text) is not None:
        return "ok" if usable_content(text, fetched_as(page_kind, redirect)) else "blocked"
    return block_class


def challenge_signal(status: int, headers: HeaderList, text: str, url: str) -> bool:
    """The generic, structural signal: a refusal a page's own script or refresh may lift, served by a document that
    stands in for the page (`classify.interstitial`: 403, 429 or 503; a script or refresh; no page of the site)."""
    return interstitial(status, headers, text, url)


def challenge_label(
    status: int, headers: HeaderList, text: str, url: str, cookie_names: Iterable[str] = ()
) -> str | None:
    """The label of a response in a `CHALLENGED` class. `headers` are as received, `Set-Cookie` included: only
    the cookie names are read (RFC 6265 §4.1.1, the name before the first `=`), never a value. `cookie_names` adds the
    names a browser holds for the page, whose capture records no `Set-Cookie`. A 451 is `LEGAL`, whatever else it
    shows."""
    if status == _UNAVAILABLE_FOR_LEGAL_REASONS:
        return LEGAL
    names = (*_cookie_names(headers), *cookie_names)
    signature = vendor_of((name for name, _ in headers), names, text)
    if signature is not None:
        return signature.vendor
    return STRUCTURAL if challenge_signal(status, headers, text, url) else None


def vendor_block(result: FetchResult) -> str | None:
    """The vendor whose challenge kept a `blocked` fetch from its page: the label of the latest attempt of the kept
    outcome's method that names one (not `STRUCTURAL` nor `LEGAL`; a rejected attempt of another rung is not what the
    kept capture shows); None for any other fetch. Such a page is a `blocked` outcome naming the vendor, never an engine
    failure to retry as one (master plan 2026-10-18 §3.1; owner #50: nothing is evaded)."""
    if result.block_class != "blocked":
        return None
    kept = (a for a in reversed(result.attempts) if a.method == result.method)
    return next((a.challenge for a in kept if a.challenge not in (None, STRUCTURAL, LEGAL)), None)


def _cookie_names(headers: HeaderList) -> tuple[str, ...]:
    return tuple(value.split("=", 1)[0].strip() for name, value in headers if name.lower() == _SET_COOKIE)


def count(label: str | None, method: CaptureMethod) -> None:
    """Count one labelled attempt: one log record per label and rung, which the log pipeline aggregates."""
    if label is not None:
        log.info("challenge attempt", extra={"challenge": label, "method": method})
