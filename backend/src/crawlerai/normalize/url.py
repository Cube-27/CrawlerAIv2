"""URL and image_url normalizer (SPEC-04 §4.4, ARCHITECTURE §9): an absolute, canonical http(s) URL.

Accepts a string, from the DOM, an LLM or a structured source (JSON-LD `url` and `image` values are strings). Any
other JSON value is `Invalid("not_a_string")`. A relative reference resolves against `ctx.base_url`.

`equal` is a stub until SPEC-04 PR 9 implements §4.5.
"""

import re
import string
from urllib.parse import SplitResult, quote, urljoin, urlsplit

from pydantic import JsonValue

from crawlerai.normalize.base import Context, Invalid, NormalizeResult, Ok, Raw
from crawlerai.schemas.types import FieldSpec, FieldType

# WHATWG URL Standard, basic URL parser: strip leading and trailing C0 controls and spaces, and remove every ASCII
# tab or newline.
_C0_AND_SPACE = "".join(chr(c) for c in range(0x21))
_TAB_OR_NEWLINE = re.compile(r"[\t\n\r]")
# RFC 3986 §2.1 and §6.2.2.1: percent-encoding triplets; hex digits compare case-insensitively, uppercase is
# canonical.
_PERCENT_TRIPLET = re.compile(r"%([0-9A-Fa-f]{2})")
# RFC 3986 §2.3: unreserved characters. Percent-encoded, they are equivalent to the character (§6.2.2.2).
_UNRESERVED = frozenset(string.ascii_letters + string.digits + "-._~")
# RFC 3986 §3.3 `pchar` without the unreserved set (which `quote` never encodes), plus `/`; §3.4 adds `?` for the
# query. `%` stays, so existing triplets and a bare `%` (a WHATWG validation error, not a failure) are kept.
_PATH_SAFE = "!$&'()*+,;=:@/%"
_QUERY_SAFE = _PATH_SAFE + "?"
# RFC 9110 §4.2.1 and §4.2.2: the default ports of http and https, the only schemes of the type.
_DEFAULT_PORT = {"http": 80, "https": 443}


def normalize(raw: Raw, spec: FieldSpec, ctx: Context) -> NormalizeResult:
    """Normalize a url or image_url field (SPEC-04 §4.4)."""
    if spec.type not in (FieldType.URL, FieldType.IMAGE_URL):
        raise TypeError(f"the url normalizer does not handle type {spec.type}")
    if not isinstance(raw, str):
        return Invalid("not_a_string")
    result = _canonical(raw, ctx.base_url)
    if (
        spec.type is FieldType.IMAGE_URL
        and isinstance(result, Ok)
        and ctx.page_url is not None
        and _canonical(ctx.page_url, None) == result
    ):
        # SPEC-04 §4.4: without a fetch there is no content-type evidence, so the one structural check is that an
        # image is not the page it appears on.
        return Invalid("page_url")
    return result


def _canonical(raw: str, base: str | None) -> NormalizeResult:
    # INV-06: input of whitespace only is empty, whatever the base (an empty reference would resolve to the base).
    if not raw.strip():
        return Invalid("empty")
    reference = _TAB_OR_NEWLINE.sub("", raw.strip(_C0_AND_SPACE))
    try:
        parts = urlsplit(reference)
        if not parts.scheme:
            if base is None:
                return Invalid("relative_without_base")
            # RFC 3986 §5.2: reference resolution against the base URI.
            reference = urljoin(base, reference)
            parts = urlsplit(reference)
        port = parts.port
    except ValueError:
        return Invalid("unparsable")
    # SPEC-04 §4.4 and ARCHITECTURE §9: only http(s) URLs are values of the type. `urlsplit` lowercases the scheme
    # (RFC 3986 §3.1: schemes are case-insensitive).
    if parts.scheme not in _DEFAULT_PORT:
        return Invalid("not_http")
    if not parts.hostname:
        return Invalid("no_host")
    # RFC 3986 §6.2.3: an empty path with an authority is "/". Dot segments are removed after percent-normalization,
    # so `%2E` counts as a dot (WHATWG URL Standard, single- and double-dot segments).
    path = _remove_dot_segments(quote(_normalize_triplets(parts.path) or "/", safe=_PATH_SAFE))
    # The fragment is dropped: it names a part of the document, not a different resource (RFC 3986 §3.5).
    # An empty query keeps its `?`: RFC 3986 §6.2.3 removes an empty component's delimiter only where the scheme
    # allows it, and http does not.
    query = (
        f"?{quote(_normalize_triplets(parts.query), safe=_QUERY_SAFE)}" if "?" in reference.partition("#")[0] else ""
    )
    return Ok(f"{parts.scheme}://{_authority(parts, parts.hostname, port)}{path}{query}")


def _authority(parts: SplitResult, hostname: str, port: int | None) -> str:
    # RFC 3986 §3.2.2: the host is case-insensitive; `hostname` is lowercased and has no IPv6 brackets.
    host = f"[{hostname}]" if ":" in hostname else hostname
    userinfo, at, _ = parts.netloc.rpartition("@")
    # RFC 9110 §4.2: the scheme's default port is the same as no port.
    shown_port = f":{port}" if port is not None and port != _DEFAULT_PORT[parts.scheme] else ""
    return f"{userinfo}{at}{host}{shown_port}"


def _normalize_triplets(component: str) -> str:
    return _PERCENT_TRIPLET.sub(_normalize_triplet, component)


def _normalize_triplet(match: re.Match[str]) -> str:
    char = chr(int(match.group(1), 16))
    return char if char in _UNRESERVED else f"%{match.group(1).upper()}"


def _remove_dot_segments(path: str) -> str:
    """RFC 3986 §5.2.4, for an absolute path."""
    segments = path.split("/")
    out: list[str] = []
    for segment in segments:
        if segment == ".":
            continue
        if segment == "..":
            if len(out) > 1:
                out.pop()
            continue
        out.append(segment)
    if segments[-1] in (".", ".."):
        out.append("")
    return "/".join(out)


def equal(a: JsonValue, b: JsonValue) -> bool:
    """Stub until SPEC-04 PR 9 implements §4.5 (equal after canonicalization).

    Exact equality of two normalized values, which labels and engine output both hold (SPEC-03 §4.3).
    """
    return a == b
