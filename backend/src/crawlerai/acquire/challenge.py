"""Challenge labels on attempts (D-1326): which anti-bot challenge, if any, a `blocked` or `shell` response presents
(`CHALLENGED`: a site's missing page or failure is no challenge, whatever cookies its edge sets). The label is the
vendor whose signature the response shows (`adapters.challenges`, site data), else `STRUCTURAL` when the generic
signal holds, else none.

INV-24 holds: the block class comes from status and structure alone (`classify`), and a label changes neither it nor
the remembered fetch method. Labels are recorded on the attempt (its manifest and `capture` row keep them), counted in
the log per label and rung, and slow a host's adaptive rate as a 429 does (`politeness`).
"""

import logging
from typing import Final

from crawlerai.acquire.classify import interstitial
from crawlerai.acquire.types import BlockClass
from crawlerai.adapters.challenges import vendor_of
from crawlerai.core.capture import CaptureMethod
from crawlerai.storage.capture_bundle import HeaderList

__all__ = ["CHALLENGED", "STRUCTURAL", "challenge_label", "challenge_signal", "count"]

log = logging.getLogger(__name__)

# The label of a challenge no vendor signature names.
STRUCTURAL: Final = "structural"
_SET_COOKIE = "set-cookie"  # RFC 6265 §4.1
# The classes a challenge takes (`classify`): a refusal, or a document with nothing of the page in it.
CHALLENGED: Final[frozenset[BlockClass]] = frozenset({"blocked", "shell"})


def challenge_signal(status: int, headers: HeaderList, body: bytes, url: str) -> bool:
    """The generic, structural signal: a refusal a page's own script or refresh may lift, served by a document that
    stands in for the page (`classify.interstitial`: 403, 429 or 503; a script or refresh; no page of the site)."""
    return interstitial(status, headers, body, url)


def challenge_label(status: int, headers: HeaderList, body: bytes, url: str) -> str | None:
    """The label of a response in a `CHALLENGED` class. `headers` are as received, `Set-Cookie` included: only
    the cookie names are read (RFC 6265 §4.1.1, the name before the first `=`), never a value."""
    signature = vendor_of((name for name, _ in headers), _cookie_names(headers), body)
    if signature is not None:
        return signature.vendor
    return STRUCTURAL if challenge_signal(status, headers, body, url) else None


def _cookie_names(headers: HeaderList) -> tuple[str, ...]:
    return tuple(value.split("=", 1)[0].strip() for name, value in headers if name.lower() == _SET_COOKIE)


def count(label: str | None, method: CaptureMethod) -> None:
    """Count one labelled attempt: one log record per label and rung, which the log pipeline aggregates."""
    if label is not None:
        log.info("challenge attempt", extra={"challenge": label, "method": method})
