"""Which responses redirect, and where to, for the fetchers that follow redirects by hand so the SSRF guard checks
every hop (acquisition spec)."""

from crawlerai.storage.capture_bundle import HeaderList

# RFC 9110 §15.4: the redirect status codes that carry a Location to follow (300 and 304 do not redirect by
# themselves, 305 and 306 are deprecated).
_REDIRECTS = frozenset({301, 302, 303, 307, 308})
MAX_REDIRECTS = 5  # acquisition spec


def location(status: int, headers: HeaderList) -> str | None:
    """The Location to follow, or None when the response is not a redirect."""
    if status not in _REDIRECTS:
        return None
    # RFC 9110 §10.2.2: one Location value; when repeated, the last one received is used.
    values = [value for name, value in headers if name.lower() == "location"]
    return values[-1] if values else None
