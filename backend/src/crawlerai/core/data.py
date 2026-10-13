"""Fetch the data files that the manifest pins but the repository does not hold (SPEC-04 §4.6, INV-05, C4).

`backend/data/manifest.json` lists every data file with its source URL and sha256. An entry marked `"fetched": true`
is not committed (a third-party snapshot such as GeoNames); `fetch_data` downloads it, checks its bytes against the
pinned hash, and only then writes it. `tools/data_manifest_check.py` checks the same manifest in CI.
"""

import hashlib
import json
import os
import tempfile
import urllib.request
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

MANIFEST = "manifest.json"
_TIMEOUT_SECONDS = 120


class DataFetchError(Exception):
    """A fetched entry could not be written as the manifest pins it."""


def _download(url: str) -> bytes:
    # `fetch_data` admits only https URLs from the manifest, so no other scheme reaches urlopen.
    with urllib.request.urlopen(url, timeout=_TIMEOUT_SECONDS) as response:  # noqa: S310
        body: bytes = response.read()
    return body


def fetch_data(data_dir: Path, download: Callable[[str], bytes] = _download) -> list[str]:
    """Download each fetched entry of `data_dir`'s manifest that is missing or differs from its pinned sha256.

    Returns one line per fetched entry (`fetched <path>` or `present <path>`). Raises `DataFetchError` on an entry
    whose path leaves `data_dir`, whose URL is not https, or whose download does not match its hash; a refused
    download is not written.
    """
    root = data_dir.resolve()
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    report: list[str] = []
    for entry in manifest["entries"]:
        if entry.get("fetched") is not True:
            continue
        path, url, sha256 = str(entry["path"]), str(entry["url"]), str(entry["sha256"]).lower()
        # The manifest is data: a path that resolves outside the data directory is never written.
        target = (root / path).resolve()
        if not target.is_relative_to(root):
            raise DataFetchError(f"{path}: outside the data directory")
        if urlsplit(url).scheme != "https":
            raise DataFetchError(f"{path}: {url} is not an https URL")
        if target.is_file() and _sha256(target.read_bytes()) == sha256:
            report.append(f"present {path}")
            continue
        content = download(url)
        if (got := _sha256(content)) != sha256:
            raise DataFetchError(
                f"{path}: sha256 {got} does not match the manifest; the source changed, so the entry needs re-pinning"
            )
        _write_atomically(target, content)
        report.append(f"fetched {path}")
    return report


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write_atomically(target: Path, content: bytes) -> None:
    # A reader never sees a partial file: the bytes go to a temporary file in the same directory, then replace the
    # target in one rename (os.replace is atomic on POSIX and Windows when both are on one volume).
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(content)
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
