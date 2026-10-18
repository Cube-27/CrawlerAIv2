"""The `ObjectStore` protocol (persistence-storage spec) and the key rules every backend shares.

Methods are synchronous because boto3 is; async callers run them in a thread (`to_thread` in asyncio).
"""

import builtins
from typing import Protocol


class ObjectNotFound(Exception):
    """`get` of a key that holds no object (persistence-storage spec). The caller decides what that means."""


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes) -> None:
        """Store `data` under `key`, replacing any existing object."""

    def get(self, key: str) -> bytes:
        """Return the object's bytes; raise `ObjectNotFound` if there is none."""

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None:
        """Remove the object. Deleting a missing key is a no-op, so retention passes can be re-run."""

    def list(self, prefix: str) -> builtins.list[str]:
        """Every key that starts with `prefix` (plain string prefix, as S3 ListObjectsV2 matches), sorted."""


def check_key(key: str) -> str:
    """Keys are relative `/`-separated paths whose segments are non-empty and don't start with `.`.

    That keeps one key meaning one object on both backends: no absolute paths or `..` escaping an `fs` root, no
    empty segments S3 would keep but a filesystem would collapse, and no dot-files, which `fs` uses for
    in-progress writes. Backslash and NUL are path separators or terminators on some filesystems.
    """
    segments = key.split("/")
    if any(not s or s.startswith(".") or "\\" in s or "\x00" in s for s in segments):
        raise ValueError(f"invalid object key {key!r}: expected a relative path like 'captures/2026/10/id'")
    return key
