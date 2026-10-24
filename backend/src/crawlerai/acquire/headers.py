"""Which headers a capture records: every header field except credentials."""

from crawlerai.storage.capture_bundle import HeaderList

# Credentials are never stored in a capture: cookies (RFC 6265 §4), the user agent's credentials (RFC 9110 §11.6.2)
# and the proxy credentials.
_UNRECORDED = frozenset({"cookie", "set-cookie", "authorization", "proxy-authorization"})
# RFC 9113 §8.3, RFC 9114 §4.3: a name that starts with `:` is an HTTP/2 or HTTP/3 pseudo-header, which is not a header
# field (a field name is a token, RFC 9110 §5.1); the browser reports them with the fields it sent.
_PSEUDO = ":"


def recorded(headers: HeaderList) -> HeaderList:
    return tuple(
        (name, value) for name, value in headers if name.lower() not in _UNRECORDED and not name.startswith(_PSEUDO)
    )
