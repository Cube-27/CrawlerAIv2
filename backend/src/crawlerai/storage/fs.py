"""Filesystem `ObjectStore` for development and CI (persistence-storage spec): one file per key under a root
directory."""

import builtins
import os
import tempfile
from pathlib import Path

from crawlerai.storage.base import ObjectNotFound, check_key


class FsStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, key: str) -> Path:
        return self._root.joinpath(*check_key(key).split("/"))

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a dot-file beside the target, then rename: a reader or a crash never sees a partial object
        # (os.replace is atomic within one filesystem). Keys can't start with `.`, so `list` skips these files.
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".", suffix=".partial")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def get(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError:
            raise ObjectNotFound(key) from None

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def list(self, prefix: str) -> builtins.list[str]:
        # Walk only the deepest directory the prefix names fully; the rest of the prefix is a string match.
        directory = prefix.rpartition("/")[0]
        start = self._path(directory) if directory else self._root
        if not start.is_dir():
            return []
        keys = (
            path.relative_to(self._root).as_posix()
            for path in start.rglob("*")
            if path.is_file() and not path.name.startswith(".")
        )
        return sorted(key for key in keys if key.startswith(prefix))
