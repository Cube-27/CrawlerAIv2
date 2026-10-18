"""The capture bundle (SPEC-01 §4.5, ARCHITECTURE §15): everything replay needs, in one zstd-compressed tar.

```
manifest.json      # CaptureManifest
body.html          # response body as received (transfer/content encoding removed); body.json for API captures;
                   # for browser captures, the rendered DOM
body.raw.html      # browser captures only: the navigation response body as the server sent it (SPEC-02 §4.8)
network/0001.json  # captured JSON bodies in response order, as received (browser captures only)
```

`encode` and `decode` are pure and `decode(encode(b)) == b` (INV-10). Replay reads nothing but the bundle.
"""

import hashlib
import io
import json
import re
import tarfile
from datetime import UTC, datetime
from email.message import Message
from typing import Annotated, Final, Literal, Self
from uuid import UUID

import webencodings
import zstandard
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, ValidationError, model_validator

from crawlerai.core.capture import BlockClass, CaptureMethod

SHA256_PATTERN = r"^[0-9a-f]{64}$"
Sha256 = Annotated[str, Field(pattern=SHA256_PATTERN)]
# A header list, not a mapping: HTTP allows a field name to repeat (RFC 9110 §5.3, e.g. Set-Cookie), and the
# bundle keeps headers as received.
HeaderList = tuple[tuple[str, str], ...]

_MANIFEST = "manifest.json"
_RAW_BODY = "body.raw.html"


class CorruptBundle(Exception):
    """The bytes are not a valid bundle (SPEC-01 §4.8)."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Headers(_Frozen):
    request: HeaderList
    response: HeaderList


class NetworkBody(_Frozen):
    """Manifest entry for one captured network body; the bytes sit at the same index of the bundle's `network`.

    `method`, `request_body` and `request_headers` describe the request the body answered, which API discovery groups
    and binds by (SPEC-09 §4.3) and header minimization replays (§4.6); bundles written before they were kept decode
    with None. `request_body` is None also for a request without a body or with one that is not UTF-8 text.
    `request_headers` are recorded as the page's are (SPEC-02 §4.7: no cookies), in the order sent.

    `response_headers` are recorded the same way, in the order received; `resource_type` is the request's Fetch
    destination as the browser names it (`fetch`, `xhr`, `document`); `action` is how many browser actions the page
    had performed when the response arrived (0: the page's own load). Bundles written before they were kept decode
    with None."""

    url: str
    status: int
    content_type: str | None
    sha256: Sha256
    file: str
    method: str | None = None
    request_body: str | None = None
    request_headers: HeaderList | None = None
    response_headers: HeaderList | None = None
    resource_type: str | None = None
    action: int | None = Field(default=None, ge=0)


class CaptureManifest(_Frozen):
    bundle_version: Literal[1] = 1
    capture_id: UUID
    url: str
    final_url: str
    fetched_at: AwareDatetime
    method: CaptureMethod
    status_code: int
    block_class: BlockClass
    headers: Headers
    timings_ms: dict[str, int]
    html_sha256: Sha256
    # Absent from bundles written before raw bodies were kept: those decode with None.
    raw_html_sha256: Sha256 | None = None
    network_bodies: tuple[NetworkBody, ...]
    fetch_policy: dict[str, JsonValue]
    engine_version: str


class CaptureBundle(_Frozen):
    manifest: CaptureManifest
    body: bytes
    network: tuple[bytes, ...]
    raw_body: bytes | None = None

    @model_validator(mode="after")
    def _matches_manifest(self) -> Self:
        entries = self.manifest.network_bodies
        if sha256_hex(self.body) != self.manifest.html_sha256:
            raise ValueError("body does not match manifest html_sha256")
        if self.raw_body is not None and self.manifest.method != "browser":
            raise ValueError(f"a raw body is kept by the browser only, not by method {self.manifest.method}")
        raw_sha256 = None if self.raw_body is None else sha256_hex(self.raw_body)
        if raw_sha256 != self.manifest.raw_html_sha256:
            raise ValueError("raw_body does not match manifest raw_html_sha256")
        if entries and self.manifest.method != "browser":
            raise ValueError(f"network bodies are captured by the browser only, not by method {self.manifest.method}")
        if len(self.network) != len(entries):
            raise ValueError(f"network has {len(self.network)} bodies but the manifest lists {len(entries)}")
        for i, (data, entry) in enumerate(zip(self.network, entries, strict=True)):
            if entry.file != network_file(i):
                raise ValueError(f"network_bodies[{i}].file is {entry.file!r}, expected {network_file(i)!r}")
            if sha256_hex(data) != entry.sha256:
                raise ValueError(f"network[{i}] does not match network_bodies[{i}].sha256")
        return self


def encode(bundle: CaptureBundle) -> bytes:
    """Deterministic: equal bundles give equal bytes (tar headers carry no time, owner or mode of their own)."""
    members = [
        (_MANIFEST, bundle.manifest.model_dump_json().encode()),
        (_body_file(bundle.manifest.method), bundle.body),
        *(() if bundle.raw_body is None else ((_RAW_BODY, bundle.raw_body),)),
        *((entry.file, data) for entry, data in zip(bundle.manifest.network_bodies, bundle.network, strict=True)),
    ]
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return zstandard.ZstdCompressor().compress(raw.getbuffer())


def decode(blob: bytes) -> CaptureBundle:
    """Raise `CorruptBundle` unless `blob` holds exactly the members its manifest names, with matching hashes."""
    members: dict[str, bytes] = {}
    try:
        raw = zstandard.ZstdDecompressor().decompress(blob)
        # Members are read into memory, never extracted, so their names can't touch the filesystem.
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tar:
            for info in tar.getmembers():
                file = tar.extractfile(info) if info.isfile() else None
                if file is None or info.name in members:
                    raise CorruptBundle(f"unexpected member {info.name!r}")
                members[info.name] = file.read()
    except (zstandard.ZstdError, tarfile.TarError) as e:
        raise CorruptBundle(f"not a zstd-compressed tar: {e}") from e

    if _MANIFEST not in members:
        raise CorruptBundle(f"missing {_MANIFEST}")
    try:
        manifest = CaptureManifest.model_validate_json(members.pop(_MANIFEST))
    except ValidationError as e:
        raise CorruptBundle(f"invalid {_MANIFEST}: {e}") from e

    body_file = _body_file(manifest.method)
    raw_file = () if manifest.raw_html_sha256 is None else (_RAW_BODY,)
    expected = {body_file, *raw_file, *(entry.file for entry in manifest.network_bodies)}
    if members.keys() != expected:
        raise CorruptBundle(f"unexpected members {sorted(members)}; the manifest names {sorted(expected)}")
    try:
        return CaptureBundle(
            manifest=manifest,
            body=members[body_file],
            network=tuple(members[entry.file] for entry in manifest.network_bodies),
            raw_body=members[_RAW_BODY] if raw_file else None,
        )
    except ValidationError as e:
        raise CorruptBundle(str(e)) from e


CAPTURES_PREFIX: Final = "captures/"


def capture_key(capture_id: UUID, fetched_at: datetime) -> str:
    """Production captures, which expire after 30 days (SPEC-01 §4.4). `fetched_at` must be timezone-aware."""
    month = fetched_at.astimezone(UTC)
    return f"{CAPTURES_PREFIX}{month:%Y}/{month:%m}/{capture_id}.bundle.zst"


def dev_eval_capture_key(capture_id: UUID) -> str:
    """Eval captures, which never expire (SPEC-01 §4.4)."""
    return f"eval/dev/{capture_id}.bundle.zst"


# HTML Standard §13.2.3.2: the prescan reads at most the first 1024 bytes for a `meta` element's `charset` attribute,
# or the `charset` parameter of its `content` (§2.6.7 "extracting a character encoding from a meta element"): the
# value runs to a quote, whitespace, `;` or the tag's end.
_PRESCAN_BYTES: Final = 1024
_META_CHARSET: Final = re.compile(rb"""<meta[\s/][^>]*?charset\s*=\s*["']?\s*([^\s"';>/]+)""", re.IGNORECASE)
_UTF8: Final = webencodings.UTF8
_META_UTF16: Final = frozenset({"utf-16be", "utf-16le"})
_USER_DEFINED: Final = "x-user-defined"
_WINDOWS_1252: Final = "windows-1252"
# WHATWG MIME Sniffing §4.6: the JSON MIME types, `application/json`, `text/json` and any `+json` structured syntax
# suffix (RFC 6839 §3.1); and the HTML ones (HTML Standard §16.1, RFC 3236), which an API answer may be when refused.
_JSON_TYPES: Final = frozenset({"application/json", "text/json"})
_JSON_SUFFIX: Final = "+json"
_HTML_TYPES: Final = frozenset({"text/html", "application/xhtml+xml"})


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_body(bundle: CaptureBundle) -> str:
    """The bundle's body as text (`decode_html`)."""
    return decode_html(bundle.body, bundle.manifest.headers.response, bundle.manifest.method)


def decode_html(body: bytes, headers: HeaderList, method: CaptureMethod) -> str:
    """A response body as text; undecodable bytes become U+FFFD. Acquisition decodes a body once with it, and every
    reader of the body reads that text. A browser body is the rendered DOM, which the browser fetcher serializes as
    UTF-8, whatever the server declared for the bytes it sent. Any other body is decoded as HTML encoding sniffing says
    (HTML Standard §13.2.3.2): a byte order mark, else the charset its Content-Type names (RFC 9110 §8.3.2), else a
    `meta` declaration in its first bytes, else UTF-8; a label names its encoding as the Encoding Standard §4.2 says
    (`iso-8859-1` is windows-1252), and an unknown label is skipped. A JSON body (`_is_json`) is UTF-8 (RFC 8259
    §8.1; its media type has no charset parameter, §11), whatever charset its label names; the UTF-16 and UTF-32
    forms are told from its first bytes as `core.json_text` reads them (RFC 4627 §3)."""
    if method == "browser":
        return body.decode(_UTF8.codec_info.name, errors="replace")
    if _is_json(headers, method):
        return body.decode(json.detect_encoding(body), errors="replace")
    encoding = _transport_encoding(headers) or _meta_encoding(body) or _UTF8
    text, _ = webencodings.decode(body, encoding, errors="replace")  # a byte order mark outranks `encoding`
    return text


def _is_json(headers: HeaderList, method: CaptureMethod) -> bool:
    """Whether a body is a JSON text: labelled with a JSON MIME type, or an API capture's (`body.json`; acquisition
    spec, "Structural outcome classification (INV-24)") not labelled HTML. The essence is the last Content-Type's,
    lower-cased, parameters dropped (RFC 9110 §8.3.1)."""
    types = [value.split(";", 1)[0].strip().lower() for name, value in headers if name.lower() == "content-type"]
    essence = types[-1] if types else ""
    if essence in _JSON_TYPES or essence.endswith(_JSON_SUFFIX):
        return True
    return method == "api" and essence not in _HTML_TYPES


def _transport_encoding(headers: HeaderList) -> webencodings.Encoding | None:
    header = Message()
    for name, value in headers:
        if name.lower() == "content-type":
            header["content-type"] = value
            break
    label = header.get_content_charset()
    return None if label is None else webencodings.lookup(label)


def _meta_encoding(body: bytes) -> webencodings.Encoding | None:
    match = _META_CHARSET.search(body, 0, _PRESCAN_BYTES)
    # A label that is not ASCII names no encoding (Encoding Standard §4.2): `lookup` finds none, and it is skipped.
    label = None if match is None else match.group(1).decode("ascii", errors="replace")
    encoding = None if label is None else webencodings.lookup(label)
    if encoding is None:
        return None
    # HTML Standard §13.2.3.2 prescan: a `meta` declaration of UTF-16 means UTF-8 (the bytes it was read from are
    # ASCII-compatible), and of x-user-defined means windows-1252.
    if encoding.name in _META_UTF16:
        return _UTF8
    return webencodings.lookup(_WINDOWS_1252) if encoding.name == _USER_DEFINED else encoding


def _body_file(method: CaptureMethod) -> str:
    return "body.json" if method == "api" else "body.html"


# RFC 8259 §2: a JSON text is one value; the data a page loads is an object or an array, which open with these.
_OPENERS: Final = ("{", "[")
# A JSON body may open with a short prefix that makes it no script a page of another origin could run (a
# cross-site script inclusion guard: an endless loop or unbalanced brackets, then the JSON text). Such a prefix holds
# no object or array opener, so the JSON text starts at the first one; a prefix longer than this is not one.
_GUARD_PREFIX_MAX: Final = 16


def network_json(data: bytes) -> JsonValue:
    """A captured network body as JSON (RFC 8259): UTF-8 text (§8.1; a byte order mark is ignored, as §8.1 allows),
    either one JSON text or a short guard prefix followed by an object or array (`_GUARD_PREFIX_MAX`). Raises
    `ValueError` when it is neither. The browser reads bodies to keep with it and every reader of the bundle's
    network bodies parses them with it, so the two agree."""
    text = data.decode("utf-8-sig")  # UnicodeDecodeError is a ValueError
    try:
        return _loads(text)
    except ValueError:
        starts = [i for i in (text.find(opener) for opener in _OPENERS) if i > 0]
        if not starts or min(starts) > _GUARD_PREFIX_MAX:
            raise
    value = _loads(text[min(starts) :])
    if not isinstance(value, (dict, list)):
        raise ValueError("a guard prefix is followed by an object or an array")
    return value


def _not_json(constant: str) -> JsonValue:
    raise ValueError(f"{constant} is not JSON (RFC 8259 §6)")


_DECODER: Final = json.JSONDecoder(parse_constant=_not_json)


def _loads(text: str) -> JsonValue:
    try:
        value: JsonValue = _DECODER.decode(text)
    except RecursionError:
        raise ValueError("nested too deeply") from None
    return value


def network_file(index: int) -> str:
    return f"network/{index + 1:04d}.json"
