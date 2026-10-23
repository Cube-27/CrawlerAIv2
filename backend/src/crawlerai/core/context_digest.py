"""The keyed digest of a caller's secret request context: what a stored
capture keeps of the header and cookie values it was fetched with, so that it stands only for a fetch with the same
values (`services.stored_captures`), while the values themselves are never stored.

The digest is HMAC-SHA256 (RFC 2104) under a key derived from the server's `CRAWLERAI_COOKIE_KEY` (`configure`, called
as a process opens its fetching): processes that share the key compute equal digests, and nobody without it can test a
guessed value against a stored digest. A process with no configured key uses a random key of its own, so a capture
fetched with secrets there stands for no fetch of another process, nor of the same one after a restart.
"""

import hashlib
import hmac
import json
import secrets
from collections.abc import Iterable

__all__ = ["configure", "context_digest"]

# Domain separation: the cookie key also encrypts the stored cookie state (`acquire.cookie_store`).
_PURPOSE = b"crawlerai capture request context v1"
_key = secrets.token_bytes(32)


def configure(server_key: str) -> None:
    """Derive this process's digest key from the server key (`Settings.cookie_key`)."""
    global _key
    _key = hmac.new(server_key.encode(), _PURPOSE, hashlib.sha256).digest()


def context_digest(headers: Iterable[tuple[str, str]], cookies: Iterable[tuple[str, str]]) -> str:
    """The digest of a context's names and values, whatever order they came in: header names compared without case
    (RFC 9110 §5.1), cookie names with it (RFC 6265 §4.1.1)."""
    canonical = {
        "headers": sorted((name.lower(), value) for name, value in headers),
        "cookies": sorted(cookies),
    }
    message = json.dumps(canonical, ensure_ascii=False, separators=(",", ":")).encode()
    return hmac.new(_key, message, hashlib.sha256).hexdigest()
