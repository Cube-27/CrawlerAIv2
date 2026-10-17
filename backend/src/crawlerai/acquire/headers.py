"""Which headers a capture records (SPEC-02 §4.7): every one except credentials."""

from crawlerai.storage.capture_bundle import HeaderList

# Credentials are never stored in a capture: cookies (RFC 6265 §4), the user agent's credentials (RFC 9110 §11.6.2)
# and the proxy credentials (§11.7.2).
_UNRECORDED = frozenset({"cookie", "set-cookie", "authorization", "proxy-authorization"})


def recorded(headers: HeaderList) -> HeaderList:
    return tuple((name, value) for name, value in headers if name.lower() not in _UNRECORDED)
