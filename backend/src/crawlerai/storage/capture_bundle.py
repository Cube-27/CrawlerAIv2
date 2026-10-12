"""The capture bundle (SPEC-01 §4.5, ARCHITECTURE §15): everything replay needs, in one zstd-compressed tar.

```
manifest.json      # CaptureManifest
body.html          # response body as received (transfer/content encoding removed); body.json for API captures
network/0001.json  # captured JSON bodies in request order (browser captures only)
```

`encode` and `decode` are pure and `decode(encode(b)) == b` (INV-10). Replay reads nothing but the bundle.
"""

import hashlib
import io
import tarfile
from datetime import UTC, datetime
from typing import Annotated, Literal, Self
from uuid import UUID

import zstandard
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, ValidationError, model_validator

CaptureMethod = Literal["http", "browser", "api"]
BlockClass = Literal["ok", "blocked", "shell", "not_found", "error"]  # ARCHITECTURE §7.1
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
# A header list, not a mapping: HTTP allows a field name to repeat (RFC 9110 §5.3, e.g. Set-Cookie), and the
# bundle keeps headers as received.
HeaderList = tuple[tuple[str, str], ...]

_MANIFEST = "manifest.json"


class CorruptBundle(Exception):
    """The bytes are not a valid bundle (SPEC-01 §4.8)."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Headers(_Frozen):
    request: HeaderList
    response: HeaderList


class NetworkBody(_Frozen):
    """Manifest entry for one captured network body; the bytes sit at the same index of the bundle's `network`."""

    url: str
    status: int
    content_type: str | None
    sha256: Sha256
    file: str


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
    network_bodies: tuple[NetworkBody, ...]
    fetch_policy: dict[str, JsonValue]
    engine_version: str


class CaptureBundle(_Frozen):
    manifest: CaptureManifest
    body: bytes
    network: tuple[bytes, ...]

    @model_validator(mode="after")
    def _matches_manifest(self) -> Self:
        entries = self.manifest.network_bodies
        if _sha256(self.body) != self.manifest.html_sha256:
            raise ValueError("body does not match manifest html_sha256")
        if entries and self.manifest.method != "browser":
            raise ValueError(f"network bodies are captured by the browser only, not by method {self.manifest.method}")
        if len(self.network) != len(entries):
            raise ValueError(f"network has {len(self.network)} bodies but the manifest lists {len(entries)}")
        for i, (data, entry) in enumerate(zip(self.network, entries, strict=True)):
            if entry.file != _network_file(i):
                raise ValueError(f"network_bodies[{i}].file is {entry.file!r}, expected {_network_file(i)!r}")
            if _sha256(data) != entry.sha256:
                raise ValueError(f"network[{i}] does not match network_bodies[{i}].sha256")
        return self


def encode(bundle: CaptureBundle) -> bytes:
    """Deterministic: equal bundles give equal bytes (tar headers carry no time, owner or mode of their own)."""
    members = [
        (_MANIFEST, bundle.manifest.model_dump_json().encode()),
        (_body_file(bundle.manifest.method), bundle.body),
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
    expected = {body_file, *(entry.file for entry in manifest.network_bodies)}
    if members.keys() != expected:
        raise CorruptBundle(f"unexpected members {sorted(members)}; the manifest names {sorted(expected)}")
    try:
        return CaptureBundle(
            manifest=manifest,
            body=members[body_file],
            network=tuple(members[entry.file] for entry in manifest.network_bodies),
        )
    except ValidationError as e:
        raise CorruptBundle(str(e)) from e


def capture_key(capture_id: UUID, fetched_at: datetime) -> str:
    """Production captures, which expire after 30 days (SPEC-01 §4.4). `fetched_at` must be timezone-aware."""
    month = fetched_at.astimezone(UTC)
    return f"captures/{month:%Y}/{month:%m}/{capture_id}.bundle.zst"


def dev_eval_capture_key(capture_id: UUID) -> str:
    """Dev eval captures, which never expire (SPEC-01 §4.4). Hidden and fresh bundles use another store (INV-01)."""
    return f"eval/dev/{capture_id}.bundle.zst"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _body_file(method: CaptureMethod) -> str:
    return "body.json" if method == "api" else "body.html"


def _network_file(index: int) -> str:
    return f"network/{index + 1:04d}.json"
